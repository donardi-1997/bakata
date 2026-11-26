import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from intelligence.models import Observation
from intelligence.normalization import (ReviewedAttributes, latest_observations, normalize_product,
                                        normalize_gtin, normalize_label, normalize_code)
from intelligence.matching import MatchKind, compare, propose, approve_pair


class NormalizationTests(unittest.TestCase):
    def setUp(self):
        at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.a = Observation("fixture-a", "0001", "Lámpara LED — Modelo X-1", "https://a.invalid/product", at, "COP", 4990000)
        self.b = replace(self.a, source="fixture-b", title="lampara led modelo x-1",
                         url="https://b.invalid/item", price_minor=4500000)

    def attrs(self, row, **kwargs):
        return ReviewedAttributes(row.key, "synthetic-evidence", **kwargs)

    def test_normalization_preserves_original_and_model_punctuation(self):
        self.assertEqual(normalize_label(self.a.title), normalize_label(self.b.title))
        self.assertNotEqual(normalize_code("X-01"), normalize_code("X01"))
        self.assertNotEqual(normalize_code("001"), normalize_code("1"))
        item = normalize_product(self.a)
        self.assertEqual(item.observation.title, self.a.title)
        self.assertEqual(item.identity, ("fixture-a", "0001"))

    def test_gtin_validation_and_padding(self):
        self.assertEqual(normalize_gtin("036000291452"), normalize_gtin("0036000291452"))
        for invalid in ("036000291453", "00000000", "03600029145", "03600029145A"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                normalize_gtin(invalid)

    def test_title_and_same_sku_not_approval(self):
        p = compare(normalize_product(self.a), normalize_product(self.b))
        self.assertEqual(p.kind, MatchKind.TITLE)
        with self.assertRaises(ValueError):
            approve_pair(p, "review-1", variant_equivalence_confirmed=True)
        other = replace(self.a, external_id="0002")
        self.assertEqual(compare(normalize_product(self.a), normalize_product(other)).kind, MatchKind.NONE)

    def test_gtin_and_manual_pair_review(self):
        a = normalize_product(self.a, self.attrs(self.a, gtin="036000291452"))
        b = normalize_product(self.b, self.attrs(self.b, gtin="0036000291452"))
        p = compare(a, b)
        self.assertEqual(p.kind, MatchKind.GTIN)
        self.assertIn("variant-coverage-incomplete", p.reasons)
        with self.assertRaises(ValueError):
            approve_pair(p, "review-1", variant_equivalence_confirmed=False)
        link = approve_pair(p, "review-1", variant_equivalence_confirmed=True)
        self.assertEqual(link.left_key, self.a.key)
        self.assertEqual(link.right_key, self.b.key)

    def test_variant_conflict_overrides_gtin(self):
        a = normalize_product(self.a, self.attrs(self.a, gtin="036000291452", variants=(("color","Negro"),)))
        b = normalize_product(self.b, self.attrs(self.b, gtin="036000291452", variants=(("Color","Blanco"),)))
        p = compare(a,b)
        self.assertEqual(p.kind, MatchKind.CONFLICT)
        self.assertIn("variant-conflict:color", p.reasons)
        self.assertEqual(propose((a,b)), ())

    def test_brand_model_and_model_conflict(self):
        a = normalize_product(self.a, self.attrs(self.a, brand="Acme", model="X-01"))
        b = normalize_product(self.b, self.attrs(self.b, brand="ACME", model="x-01"))
        self.assertEqual(compare(a,b).kind, MatchKind.BRAND_MODEL)
        c = normalize_product(self.b, self.attrs(self.b, brand="Acme", model="X01"))
        self.assertEqual(compare(a,c).kind, MatchKind.CONFLICT)

    def test_stale_or_wrong_attribute_evidence(self):
        with self.assertRaises(ValueError):
            normalize_product(self.b, self.attrs(self.a, brand="Acme"))
        with self.assertRaises(ValueError):
            self.attrs(self.a, variants=(("color","red"),("Color","blue")))
        with self.assertRaises(ValueError):
            self.attrs(self.a, model="X\u200b1")

    def test_latest_view_keeps_source_identity_and_detects_conflicts(self):
        newer = replace(self.a, observed_at=self.a.observed_at + timedelta(days=1), price_minor=0)
        self.assertEqual(latest_observations((newer,self.b,self.a,self.a)), (newer,self.b))
        with self.assertRaises(ValueError):
            latest_observations((self.a,replace(self.a, price_minor=1),newer))

    def test_proposal_order_and_limits(self):
        a,b = normalize_product(self.a),normalize_product(self.b)
        self.assertEqual(propose((a,b)), propose((b,a)))
        with self.assertRaises(ValueError):
            propose((a,a))
        with self.assertRaises(ValueError):
            propose((a,)*201)
        with self.assertRaises(ValueError):
            latest_observations((self.a,)*1001)
