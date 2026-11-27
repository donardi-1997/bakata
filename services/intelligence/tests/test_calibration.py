import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
import unittest

from intelligence.calibration import Calibration, WINDOW, MATURITY
from intelligence.commercial import Capture
from intelligence.scoring import CriterionReview, UnitEconomics, REVIEW_CRITERIA
from intelligence.sources import SourceKind, SourceRegistry, SourceSpec
from intelligence.storage import CommercialStore, APPLICATION_ID, SCHEMA


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,1,1,tzinfo=timezone.utc)
        self.start=self.now+timedelta(hours=1)
        self.mature=self.start+WINDOW+MATURITY
        self.db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.archive=CommercialStore(self.db)
        self.cal=Calibration(self.archive)
        self.registry=SourceRegistry((SourceSpec("fixture-a","a.invalid",SourceKind.AUTHORIZED_CSV,
                                                 "fixture-permission",self.now+timedelta(days=1)),))
        self.cal.create("cohort",starts_at=self.start,minimum_orders=10,
                        exposure_ref="fixture-exposure",actor_ref="reviewer",now=self.now)

    def evaluation(self,index,score=75,currency="COP",age=timedelta(days=1),complete=True):
        ident=str(index)
        body=("external_id,title,url,currency,price_minor\n"
              f"{ident},Synthetic,https://a.invalid/item/{ident},{currency},4990000\n").encode()
        self.archive.ingest(self.registry,Capture("fixture-a","https://a.invalid/export/"+ident,self.now,body),now=self.now)
        key=("fixture-a",ident,self.now.isoformat())
        econ=UnitEconomics(key,"cost",self.now,currency,5700000,2500000,1200000,100000,200000,0,400)
        reviews=tuple(CriterionReview(key,k,score,"ev-"+k,self.now,"Fixture evidence") for k in REVIEW_CRITERIA)
        self.archive.record_evaluation("eval-"+ident,key,econ,reviews if complete else reviews[:-1],
                                       actor_ref="reviewer",as_of=self.now,max_age=age,now=self.now)
        return "eval-"+ident

    def enroll(self,index,score=75):
        self.cal.enroll("cohort","product-"+str(index),self.evaluation(index,score),now=self.now)

    def outcome(self,index,success=True,now=None,**changes):
        data=dict(fulfilled_orders=12 if success else 4,returned_orders=1,gross_minor=10000000,
                  contribution_minor=2000000 if success else -100000,evidence_ref="actuals",
                  actor_ref="reviewer",complete=True,now=now or self.mature)
        self.cal.outcome("cohort","product-"+str(index),**dict(data,**changes))

    def test_v1_migration_preserves_records_and_reopens(self):
        with closing(sqlite3.connect(":memory:")) as db:
            for statement in SCHEMA:
                db.execute(statement)
            db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            db.execute("PRAGMA user_version=1")
            db.execute("INSERT INTO sources VALUES ('old','old.invalid','authorized-csv')")
            db.commit()
            CommercialStore(db)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0],2)
            self.assertEqual(db.execute("SELECT source FROM sources").fetchone()[0],"old")
            CommercialStore(db)
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(),[])

    def test_prospective_only_and_unique_identity(self):
        eid=self.evaluation(1)
        self.cal.enroll("cohort","group-1",eid,now=self.now)
        with self.assertRaises(sqlite3.IntegrityError):
            self.cal.enroll("cohort","group-2",eid,now=self.now)
        with self.assertRaises(ValueError):
            self.cal.enroll("cohort","group-3",eid,now=self.start)
        with self.assertRaises(ValueError):
            self.cal.create("late",starts_at=self.now,minimum_orders=10,
                            exposure_ref="exposure",actor_ref="reviewer",now=self.now)

    def test_unusable_baselines(self):
        for index,kwargs in enumerate(({"complete":False},{"currency":"USD"},{"age":timedelta(minutes=30)})):
            eid=self.evaluation(index,**kwargs)
            with self.assertRaises(ValueError):
                self.cal.enroll("cohort","group-"+str(index),eid,now=self.now)

    def test_outcome_maturity_and_invalid_values(self):
        self.enroll(1)
        with self.assertRaises(ValueError):
            self.outcome(1,now=self.mature-timedelta(seconds=1))
        for changes in ({"complete":False},{"returned_orders":13},{"fulfilled_orders":0},{"contribution_minor":10000001}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                self.outcome(1,**changes)
        self.outcome(1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.outcome(1)

    def test_missing_is_not_failure_and_as_of(self):
        self.enroll(1)
        self.enroll(2)
        self.outcome(1)
        early=self.cal.report("cohort",as_of=self.mature-timedelta(seconds=1))
        self.assertEqual(early["missing"],2)
        result=self.cal.report("cohort",as_of=self.mature)
        self.assertEqual(result["observed"],1)
        self.assertEqual(result["missing"],1)
        self.assertEqual(result["failures"],0)
        self.assertEqual(result["coverage_pct"],"50.00")
        self.assertIsNone(result["rank_concordance_pct"])

    def test_rank_concordance_and_margin_error(self):
        for i in range(30):
            success=i>=15
            self.enroll(i,score=100 if success else 25)
            self.outcome(i,success=success)
        result=self.cal.report("cohort",as_of=self.mature)
        self.assertEqual(result["status"],"descriptive-review-ready")
        self.assertEqual(result["rank_concordance_pct"],"100.00")
        self.assertEqual(result["criterion_concordance_pct"]["profitability"],"50.00")
        self.assertEqual(result["criterion_concordance_pct"]["demand"],"100.00")
        self.assertEqual(result["observed_return_rate_pct"],"12.50")
        self.assertEqual(result["successes"],15)
        self.assertEqual(result["failures"],15)
        self.assertEqual(result["bands"][3]["success_rate_pct"],"100.00")
        self.assertEqual(result["bands"][1]["success_rate_pct"],"0.00")
        self.assertIsNotNone(result["mean_absolute_margin_error_pp"])

    def test_tied_scores_and_zero_sales(self):
        for i in range(30):
            self.enroll(i)
            self.outcome(i,success=i>=15,**({"fulfilled_orders":0,"returned_orders":0,
                         "gross_minor":0,"contribution_minor":-100} if i<15 else {}))
        result=self.cal.report("cohort",as_of=self.mature)
        self.assertEqual(result["rank_concordance_pct"],"50.00")
        self.assertEqual(result["margin_error_sample"],15)
        self.assertIsNone(result["mean_absolute_margin_error_pp"])

    def test_all_success_insufficient_for_rank_validation(self):
        for i in range(30):
            self.enroll(i)
            self.outcome(i)
        result=self.cal.report("cohort",as_of=self.mature)
        self.assertEqual(result["status"],"insufficient-evidence")
        self.assertIsNone(result["rank_concordance_pct"])

    def test_changed_baseline_detected(self):
        self.enroll(1)
        self.outcome(1)
        with self.db:
            self.db.execute("UPDATE evaluations SET payload='{}' WHERE id='eval-1'")
        with self.assertRaises(ValueError):
            self.cal.report("cohort",as_of=self.mature)
