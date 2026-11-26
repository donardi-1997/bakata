import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from intelligence.models import Observation
from intelligence.normalization import ReviewedAttributes, normalize_product
from intelligence.matching import compare, approve_pair
from intelligence.prices import (ReviewedPriceContext, Quote, price_history,
                                 market_comparison, percent_change)


class PriceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 1, 2, tzinfo=timezone.utc)
        self.a = Observation("fixture-a", "001", "Fixture", "https://a.invalid/item",
                             self.now-timedelta(hours=2), "COP", 4990000)
        self.b = replace(self.a, source="fixture-b", url="https://b.invalid/item",
                         price_minor=4500000, observed_at=self.now-timedelta(hours=1))

    def quote(self, row, **kwargs):
        fields = dict(observation_key=row.key, evidence_ref="synthetic-costs", destination="CO:bogota",
                      price_kind="retail", condition="new", tax_included=True,
                      additional_tax_minor=0, shipping_minor=100000)
        fields.update(kwargs)
        return Quote(row, ReviewedPriceContext(**fields))

    def link(self, a, b):
        left = normalize_product(a, ReviewedAttributes(a.key, "fixture-review", gtin="036000291452"))
        right = normalize_product(b, ReviewedAttributes(b.key, "fixture-review", gtin="036000291452"))
        return approve_pair(compare(left,right), "review-1", variant_equivalence_confirmed=True)

    def market(self, quotes, links, **kwargs):
        options = dict(as_of=self.now, max_age=timedelta(days=1), max_skew=timedelta(hours=3))
        options.update(kwargs)
        return market_comparison(quotes,links,**options)

    def test_history_order_dedup_and_exact_median(self):
        earlier = replace(self.a, observed_at=self.a.observed_at-timedelta(hours=1), price_minor=5000001)
        history = price_history((self.a, earlier, self.a), as_of=self.now)
        self.assertEqual(history.observations, (earlier,self.a))
        self.assertEqual(history.stats.median_minor, Decimal("4995000.5"))
        self.assertEqual(history.latest_change_pct, Decimal("-0.20"))
        self.assertEqual(history.latest_age, timedelta(hours=2))

    def test_unknown_latest_never_bridged_and_zero_baseline(self):
        unknown = replace(self.a, observed_at=self.now, price_minor=None)
        history = price_history((self.a,unknown), as_of=self.now)
        self.assertEqual(history.unknown_count, 1)
        self.assertIsNone(history.latest_change_pct)
        self.assertIsNone(percent_change(0, 100))
        self.assertEqual(percent_change(100,0), Decimal("-100.00"))
        self.assertIsNone(price_history((unknown,),as_of=self.now).stats.median_minor)

    def test_history_rejects_mixed_conflicts_future(self):
        for rows in ((self.a,self.b), (self.a,replace(self.a,currency="USD")),
                     (self.a,replace(self.a,price_minor=1)),
                     (replace(self.a,observed_at=self.now+timedelta(seconds=1)),), ()):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                price_history(rows, as_of=self.now)

    def test_reviewed_landed_price_comparison(self):
        a = self.quote(self.a, shipping_minor=0)
        b = self.quote(self.b, tax_included=False, additional_tax_minor=200000, shipping_minor=100000)
        result = self.market((b,a),(self.link(self.a,self.b),))
        self.assertEqual(result.stats.minimum_minor,4800000)
        self.assertEqual(result.stats.maximum_minor,4990000)
        self.assertEqual(result.stats.median_minor,Decimal("4895000"))
        self.assertEqual(result.spread_minor,190000)
        self.assertEqual(result.lowest_vs_highest_pct,Decimal("-3.81"))
        self.assertEqual(result.totals[0][0],self.a.key)

    def test_unknown_costs_and_contradictory_tax(self):
        for changes in ({"shipping_minor":None}, {"tax_included":None},
                        {"tax_included":False,"additional_tax_minor":None}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.market((self.quote(self.a,**changes),self.quote(self.b)),(self.link(self.a,self.b),))
        with self.assertRaises(ValueError):
            self.quote(self.a,additional_tax_minor=1)
        with self.assertRaises(ValueError):
            self.quote(self.a,shipping_minor=True)

    def test_mixed_currency_destination_condition_and_kind(self):
        for changes in ({"destination":"CO:medellin"},{"condition":"used"},{"price_kind":"supplier"}):
            with self.assertRaises(ValueError):
                self.market((self.quote(self.a,**changes),self.quote(self.b)),(self.link(self.a,self.b),))
        usd = replace(self.b,currency="USD")
        with self.assertRaises(ValueError):
            self.market((self.quote(self.a),self.quote(usd)),(self.link(self.a,usd),))

    def test_freshness_and_skew(self):
        quotes = self.quote(self.a),self.quote(self.b)
        links = (self.link(self.a,self.b),)
        with self.assertRaises(ValueError):
            self.market(quotes,links,max_age=timedelta(hours=1),max_skew=timedelta(hours=1))
        with self.assertRaises(ValueError):
            self.market(quotes,links,max_skew=timedelta(minutes=30))
        with self.assertRaises(ValueError):
            self.market(quotes,links,as_of=self.a.observed_at)

    def test_no_transitive_or_stale_review(self):
        c = replace(self.b,source="fixture-c",url="https://c.invalid/item")
        quotes = self.quote(self.a),self.quote(self.b),self.quote(c)
        ab,bc,ac = self.link(self.a,self.b),self.link(self.b,c),self.link(self.a,c)
        with self.assertRaises(ValueError):
            self.market(quotes,(ab,bc))
        with self.assertRaises(ValueError):
            self.market(quotes,(ab,ab,ac))
        self.assertEqual(self.market(quotes,(ab,bc,ac)).stats.count,3)
        newer = replace(self.b,observed_at=self.now)
        with self.assertRaises(ValueError):
            self.market((self.quote(self.a),self.quote(newer)),(ab,))

    def test_context_exact_key_and_single_source(self):
        with self.assertRaises(ValueError):
            Quote(self.b,self.quote(self.a).context)
        other = replace(self.a,external_id="002")
        with self.assertRaises(ValueError):
            self.market((self.quote(self.a),self.quote(other)),())
        with self.assertRaises(ValueError):
            self.quote(self.a,quantity=2)
