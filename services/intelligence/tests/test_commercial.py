import hashlib
import json
import sqlite3
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from intelligence.commercial import Capture, import_capture
from intelligence.repository import ObservationStore
from intelligence.sources import SourceKind, SourceRegistry, SourceSpec


class CommercialTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 1, 2, tzinfo=timezone.utc)
        self.at = self.now - timedelta(hours=1)
        self.spec = SourceSpec("fixture-woo", "catalog.invalid", SourceKind.STORE_API,
                               "synthetic-review", self.now + timedelta(days=1))
        self.url = "https://catalog.invalid/wp-json/wc/store/v1/products"
        self.item = {"id": 123, "name": "Fixture", "permalink": "https://catalog.invalid/product/fixture",
                     "type": "simple", "is_password_protected": False,
                     "prices": {"price": "4990000", "currency_code": "COP", "currency_minor_unit": 2, "price_range": None}}

    def run_capture(self, body, spec=None, url=None, **kwargs):
        spec = spec or self.spec
        return import_capture(SourceRegistry((spec,)), Capture(spec.source, url or self.url, self.at, body),
                              now=self.now, **kwargs)

    def test_store_api_exact_minor_units_and_evidence(self):
        body = json.dumps([self.item]).encode()
        batch = self.run_capture(body)
        self.assertEqual(batch.observations[0].price_minor, 4990000)
        self.assertEqual(batch.observations[0].external_id, "123")
        self.assertEqual(batch.evidence.sha256, hashlib.sha256(body).hexdigest())
        self.assertEqual(batch.evidence.approval_ref, "synthetic-review")
        with sqlite3.connect(":memory:") as db:
            store = ObservationStore(db)
            self.assertEqual(store.ingest(batch.observations), 1)
            self.assertEqual(store.ingest(batch.observations), 0)

    def test_variable_price_is_unknown(self):
        item = dict(self.item, type="variable")
        self.assertIsNone(self.run_capture(json.dumps([item]).encode()).observations[0].price_minor)

    def test_source_approval_fail_closed(self):
        for spec in (replace(self.spec, approval_ref=None), replace(self.spec, approved_until=self.now)):
            with self.assertRaises(ValueError):
                self.run_capture(b"[]", spec)
        with self.assertRaises(ValueError):
            import_capture(SourceRegistry(), Capture(self.spec.source, self.url, self.at, b"[]"), now=self.now)

    def test_duplicate_sources_and_products(self):
        with self.assertRaises(ValueError):
            SourceRegistry((self.spec, self.spec))
        with self.assertRaises(ValueError):
            self.run_capture(json.dumps([self.item, self.item]).encode())

    def test_reject_wrong_host_private_path_and_currency(self):
        for item in (dict(self.item, permalink="https://other.invalid/product"),
                     dict(self.item, is_password_protected=True),
                     dict(self.item, prices=dict(self.item["prices"], currency_minor_unit=0)),
                     dict(self.item, prices=dict(self.item["prices"], currency_code="XXX"))):
            with self.assertRaises(ValueError):
                self.run_capture(json.dumps([item]).encode())
        for url in ("https://catalog.invalid/wp-json/wc/v3/orders", self.url+"?token=secret"):
            with self.assertRaises(ValueError):
                self.run_capture(b"[]", url=url)

    def test_capture_limits(self):
        for body in (b"x"*524289, json.dumps([self.item]*101).encode()):
            with self.assertRaises(ValueError):
                self.run_capture(body)
        with self.assertRaises(ValueError):
            import_capture(SourceRegistry((self.spec,)), Capture(self.spec.source, self.url,
                self.now+timedelta(seconds=1), b"[]"), now=self.now)

    def test_authorized_csv_unknown_and_zero(self):
        spec = replace(self.spec, source="fixture-export", kind=SourceKind.AUTHORIZED_CSV)
        body = b"external_id,title,url,currency,price_minor\na,Fixture,https://catalog.invalid/a,COP,\nb,Fixture B,https://catalog.invalid/b,COP,0\n"
        batch = self.run_capture(body, spec, "https://catalog.invalid/export")
        self.assertEqual([o.price_minor for o in batch.observations], [None, 0])
        with self.assertRaises(ValueError):
            self.run_capture(body+b"c,Fixture C,https://catalog.invalid/c,COP,12.5\n", spec, "https://catalog.invalid/export")

    def test_jsonld_requires_stable_id_and_single_product(self):
        spec = replace(self.spec, source="fixture-html", kind=SourceKind.JSON_LD)
        url = "https://catalog.invalid/item"
        item = {"@type":"Product","name":"Fixture","sku":"not-global","offers":{"@type":"Offer","priceCurrency":"COP","price":"49900"}}
        body = ('<script type="application/ld+json">'+json.dumps(item)+'</script>').encode()
        with self.assertRaises(ValueError):
            self.run_capture(body, spec, url)
        result = self.run_capture(body, spec, url, external_id="reviewed-123")
        self.assertEqual(result.observations[0].external_id, "reviewed-123")
        self.assertEqual(result.observations[0].price_minor, 4990000)
        second = dict(item, name="Other")
        ambiguous = ('<script type="application/ld+json">'+json.dumps([item, second])+'</script>').encode()
        with self.assertRaises(ValueError):
            self.run_capture(ambiguous, spec, url, external_id="reviewed-123")
