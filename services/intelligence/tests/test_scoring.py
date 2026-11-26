from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from intelligence.models import Observation
from intelligence.scoring import (WEIGHTS, REVIEW_CRITERIA, RUBRIC_VERSION, UnitEconomics,
                                  CriterionReview, ScreeningStatus, evaluate, rank_review_ready)


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 1, 2, tzinfo=timezone.utc)
        self.row = Observation("fixture-a", "001", "Fixture", "https://a.invalid/item",
                               self.now-timedelta(hours=1), "COP", 2500000)
        self.econ = UnitEconomics(self.row.key, "cost-review", self.now, "COP",
                                  5700000, 2500000, 1200000, 100000, 200000, 0, 400)
        self.reviews = tuple(CriterionReview(self.row.key, name, 75, "evidence-"+name,
                                            self.now, "Synthetic review at rubric level 75")
                             for name in REVIEW_CRITERIA)

    def score(self, economics=None, reviews=None, row=None, **kwargs):
        opts = dict(as_of=self.now, max_age=timedelta(days=1))
        opts.update(kwargs)
        return evaluate(row or self.row, economics if economics is not None else self.econ,
                        self.reviews if reviews is None else reviews, **opts)

    def test_weights_and_exact_contribution(self):
        self.assertEqual(sum(WEIGHTS.values()), 100)
        self.assertEqual(self.econ.contribution_minor, 1472000)
        result = self.score()
        self.assertEqual(result.total, Decimal("77.77"))
        self.assertEqual(result.status, ScreeningStatus.REVIEW_READY)
        self.assertEqual(result.coverage_pct,100)
        self.assertEqual(result.rubric_version,RUBRIC_VERSION)
        self.assertEqual(len(result.components),7)

    def test_missing_evidence_is_not_zero(self):
        result = self.score(reviews=self.reviews[:-1])
        self.assertEqual(result.coverage_pct,95)
        self.assertIsNone(result.total)
        self.assertEqual(result.status,ScreeningStatus.INCOMPLETE)
        self.assertIsNone(result.components[-1].score)
        self.assertIsNone(result.components[-1].points)

    def test_missing_cost_and_explicit_zero(self):
        result = self.score(economics=replace(self.econ, shipping_minor=None))
        self.assertEqual(result.coverage_pct,75)
        self.assertIsNone(result.total)
        self.assertIsNone(result.contribution_minor)
        self.assertEqual(result.components[0].reason,"unknown-costs")
        self.assertIsNotNone(self.score(economics=replace(self.econ,shipping_minor=0)).total)
        self.assertIsNone(evaluate(self.row,None,self.reviews,as_of=self.now,max_age=timedelta(days=1)).total)

    def test_nonpositive_contribution_blocks_even_complete(self):
        result = self.score(economics=replace(self.econ,sale_price_minor=1000000))
        self.assertEqual(result.status,ScreeningStatus.BLOCKED)
        self.assertIn("nonpositive-contribution",result.blockers)
        self.assertEqual(result.components[0].score,0)
        self.assertEqual(rank_review_ready((result,)),())

    def test_critical_reviews_block(self):
        for name in ("supplier_reliability","return_risk"):
            reviews=tuple(replace(r,score=0) if r.criterion==name else r for r in self.reviews)
            result=self.score(reviews=reviews)
            self.assertEqual(result.status,ScreeningStatus.BLOCKED)
            self.assertIn("critical-review:"+name,result.blockers)

    def test_stale_observation_and_review(self):
        result=self.score(as_of=self.now+timedelta(days=2))
        self.assertEqual(result.status,ScreeningStatus.BLOCKED)
        self.assertIsNone(result.total)
        self.assertIn("stale-observation",result.blockers)
        self.assertEqual(result.coverage_pct,0)

    def test_wrong_identity_currency_duplicate_and_future(self):
        with self.assertRaises(ValueError):
            self.score(economics=replace(self.econ,currency="USD"))
        with self.assertRaises(ValueError):
            self.score(reviews=(self.reviews[0],self.reviews[0]))
        with self.assertRaises(ValueError):
            self.score(reviews=(replace(self.reviews[0],observation_key=("x","y","z")),))
        with self.assertRaises(ValueError):
            self.score(reviews=(replace(self.reviews[0],reviewed_at=self.now+timedelta(seconds=1)),))
        with self.assertRaises(ValueError):
            self.score(reviews=(replace(self.reviews[0],reviewed_at=self.row.observed_at-timedelta(seconds=1)),))

    def test_validation_and_no_manual_profitability(self):
        for changes in ({"score":True},{"score":51},{"criterion":"profitability"},
                        {"rubric_version":"other"},{"rationale":""}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                replace(self.reviews[0],**changes)
        for changes in ({"sale_price_minor":0},{"supplier_cost_minor":-1},
                        {"variable_deduction_bps":10001},{"shipping_minor":True}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                replace(self.econ,**changes)

    def test_cap_and_aggregate_rounding(self):
        econ=replace(self.econ,sale_price_minor=101,supplier_cost_minor=0,shipping_minor=0,
                     fixed_fee_minor=0,return_reserve_minor=0,other_cost_minor=0,
                     variable_deduction_bps=1)
        self.assertEqual(econ.contribution_minor,100)
        self.assertEqual(self.score(economics=econ).components[0].score,100)

    def test_deterministic_rank_excludes_incomplete(self):
        complete=self.score()
        row=replace(self.row,external_id="002")
        econ=replace(self.econ,observation_key=row.key)
        reviews=tuple(replace(r,observation_key=row.key,score=100) for r in self.reviews)
        higher=self.score(row=row,economics=econ,reviews=reviews)
        missing=replace(higher,observation_key=("fixture-a","003",row.key[2]),
                        status=ScreeningStatus.INCOMPLETE,total=None)
        self.assertEqual(rank_review_ready((complete,missing,higher)),(higher,complete))
        with self.assertRaises(ValueError):
            rank_review_ready((complete,complete))
        with self.assertRaises(ValueError):
            rank_review_ready((complete,replace(higher,as_of=self.now+timedelta(seconds=1))))
        with self.assertRaises(ValueError):
            rank_review_ready((complete,replace(higher,max_age=timedelta(days=2))))
