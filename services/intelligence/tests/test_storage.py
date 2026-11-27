import hashlib
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from intelligence.commercial import Capture
from intelligence.normalization import ReviewedAttributes
from intelligence.matching import ReviewedLink, approve_pair, compare
from intelligence.normalization import normalize_product
from intelligence.prices import Quote, ReviewedPriceContext, market_comparison
from intelligence.scoring import CriterionReview, REVIEW_CRITERIA, UnitEconomics
from intelligence.sources import SourceKind, SourceRegistry, SourceSpec
from intelligence.storage import CommercialStore, APPLICATION_ID, SCHEMA_VERSION, MAX_DB_BYTES


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.at=datetime(2026,1,1,tzinfo=timezone.utc)
        self.now=self.at+timedelta(hours=2)
        self.specs=tuple(SourceSpec("fixture-"+k,k+".invalid",SourceKind.AUTHORIZED_CSV,
                                   "review-"+k,self.now+timedelta(days=1)) for k in ("a","b"))
        self.registry=SourceRegistry(self.specs)
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/"commercial.sqlite"
        self.db=sqlite3.connect(self.path)
        self.addCleanup(self.db.close)
        self.store=CommercialStore(self.db)

    def capture(self,index=0,amount="4990000",at=None,path="/export",extra=""):
        spec=self.specs[index]
        body=("external_id,title,url,currency,price_minor\n"
              f"001,Fixture,https://{spec.host}/item,COP,{amount}\n"+extra).encode()
        return Capture(spec.source,"https://"+spec.host+path,at or self.at,body)

    def ingest(self,capture):
        return self.store.ingest(self.registry,capture,now=self.now)

    def key(self,index=0,at=None):
        return self.specs[index].source,"001",(at or self.at).isoformat()

    def test_reopen_schema_and_provenance(self):
        capture=self.capture()
        cid,count=self.ingest(capture)
        self.assertEqual(count,1)
        self.assertEqual(self.ingest(capture),(cid,0))
        with closing(sqlite3.connect(self.path)) as db:
            store=CommercialStore(db)
            self.assertEqual(db.execute("PRAGMA application_id").fetchone()[0],APPLICATION_ID)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0],SCHEMA_VERSION)
            self.assertLessEqual(db.execute("PRAGMA max_page_count").fetchone()[0]*
                                 db.execute("PRAGMA page_size").fetchone()[0],MAX_DB_BYTES)
            row=store.observation(self.key())
            self.assertEqual(row.price_minor,4990000)
            evidence=store.provenance(row.key)
            self.assertEqual(evidence[0]["sha256"],hashlib.sha256(capture.body).hexdigest())
            self.assertEqual(evidence[0]["approval_ref"],"review-a")
            self.assertNotIn("body",evidence[0])
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(),[])

    def test_history_window_unknown_and_no_silent_truncation(self):
        later=self.at+timedelta(hours=1)
        self.ingest(self.capture())
        self.ingest(self.capture(amount="",at=later))
        self.ingest(self.capture(1))
        history=self.store.history("fixture-a","001",start=self.at,end=self.now)
        self.assertEqual([r.price_minor for r in history],[4990000,None])
        self.assertEqual(len(self.store.history("fixture-a","001",start=self.at,end=later)),1)
        with self.assertRaises(ValueError):
            self.store.history("fixture-a","001",start=self.at,end=self.now,limit=1)

    def test_conflicting_capture_and_atomic_rollback(self):
        self.ingest(self.capture())
        with self.assertRaisesRegex(ValueError,"Conflicting capture"):
            self.ingest(self.capture(amount="1"))
        body=b"external_id,title,url,currency,price_minor\n002,New,https://a.invalid/new,COP,100\n001,Changed,https://a.invalid/item,COP,1\n"
        with self.assertRaisesRegex(ValueError,"Conflicting observation"):
            self.ingest(Capture("fixture-a","https://a.invalid/other",self.at,body))
        for table in ("captures","products","observations","capture_observations"):
            self.assertEqual(self.db.execute("SELECT COUNT(*) FROM "+table).fetchone()[0],1)

    def test_same_observation_multiple_capture_provenance(self):
        first,_=self.ingest(self.capture())
        second,count=self.ingest(self.capture(path="/other"))
        self.assertNotEqual(first,second)
        self.assertEqual(count,0)
        self.assertEqual(len(self.store.provenance(self.key())),2)

    def test_capacity_and_source_identity(self):
        with patch("intelligence.storage.MAX_OBSERVATIONS",0),self.assertRaises(ValueError):
            self.ingest(self.capture())
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM sources").fetchone()[0],0)
        self.ingest(self.capture())
        other=SourceSpec("fixture-a","other.invalid",SourceKind.AUTHORIZED_CSV,"other-review",self.now+timedelta(days=1))
        capture=Capture(other.source,"https://other.invalid/export",self.at,
                        b"external_id,title,url,currency,price_minor\n001,Fixture,https://other.invalid/item,COP,100\n")
        with self.assertRaisesRegex(ValueError,"Source identity"):
            self.store.ingest(SourceRegistry((other,)),capture,now=self.now)

    def test_unknown_database_and_schema_rejected(self):
        with closing(sqlite3.connect(":memory:")) as db:
            db.execute("CREATE TABLE unrelated (id INTEGER)")
            with self.assertRaisesRegex(ValueError,"unrecognized"):
                CommercialStore(db)
            self.assertIsNotNone(db.execute("SELECT name FROM sqlite_master WHERE name='unrelated'").fetchone())
        self.db.execute("PRAGMA user_version=99")
        with self.assertRaisesRegex(ValueError,"Unsupported"):
            CommercialStore(self.db)

    def test_evaluation_recomputed_and_immutable(self):
        self.ingest(self.capture())
        key=self.key()
        economics=UnitEconomics(key,"costs",self.now,"COP",5700000,2500000,1200000,100000,200000,0,400)
        reviews=tuple(CriterionReview(key,k,75,"evidence-"+k,self.now,"Synthetic review") for k in REVIEW_CRITERIA)
        kwargs=dict(actor_ref="fixture-reviewer",as_of=self.now,max_age=timedelta(days=1),now=self.now)
        self.assertTrue(self.store.record_evaluation("evaluation-1",key,economics,reviews,**kwargs))
        self.assertFalse(self.store.record_evaluation("evaluation-1",key,economics,tuple(reversed(reviews)),**kwargs))
        record=self.store.review("evaluation","evaluation-1")
        self.assertEqual(record["payload"]["result"]["total"],"77.77")
        self.assertEqual(record["actor_ref"],"fixture-reviewer")
        with self.assertRaisesRegex(ValueError,"Review ID conflict"):
            self.store.record_evaluation("evaluation-1",key,economics,reviews[:-1],**kwargs)
        self.assertTrue(self.store.record_evaluation("evaluation-2",key,economics,reviews[:-1],**kwargs))
        self.assertIsNone(self.store.review("evaluation","evaluation-2")["payload"]["result"]["total"])

    def test_equivalence_requires_evidence_and_exact_observations(self):
        self.ingest(self.capture())
        self.ingest(self.capture(1))
        left,right=self.key(),self.key(1)
        a=ReviewedAttributes(left,"gtin-a",gtin="036000291452")
        b=ReviewedAttributes(right,"gtin-b",gtin="036000291452")
        kwargs=dict(actor_ref="fixture-reviewer",review_ref="review-1",reviewed_at=self.now,now=self.now,
                    variant_equivalence_confirmed=True)
        self.assertTrue(self.store.record_equivalence("link-1",left,right,a,b,**kwargs))
        self.assertFalse(self.store.record_equivalence("link-1",right,left,b,a,**kwargs))
        self.assertEqual(self.store.review("equivalence","link-1")["payload"]["kind"],"gtin-review")
        with self.assertRaises(ValueError):
            self.store.record_equivalence("link-2",left,right,None,None,**kwargs)
        with self.assertRaises(ValueError):
            self.store.record_equivalence("link-3",left,right,a,b,**dict(kwargs,variant_equivalence_confirmed=False))

    def test_review_reference_contract_across_approval_archive_and_market(self):
        self.ingest(self.capture())
        self.ingest(self.capture(1))
        left, right = self.key(), self.key(1)
        a = ReviewedAttributes(left, "gtin-a", gtin="036000291452")
        b = ReviewedAttributes(right, "gtin-b", gtin="036000291452")
        rows = self.store.observation(left), self.store.observation(right)
        proposal = compare(normalize_product(rows[0], a), normalize_product(rows[1], b))
        quotes = tuple(Quote(row, ReviewedPriceContext(
            observation_key=row.key, evidence_ref="costs", destination="CO:bogota",
            price_kind="retail", condition="new", tax_included=True,
            additional_tax_minor=0, shipping_minor=0)) for row in rows)
        options = dict(as_of=self.now, max_age=timedelta(days=1), max_skew=timedelta(0))
        invalid = ("", " ", "\u034f", "\ufe0f", "\u2800", "\u3164",
                   "revisión", "a b", "x" * 129, None)
        for value in invalid:
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValueError):
                    approve_pair(proposal, value, variant_equivalence_confirmed=True)
                with self.assertRaises(ValueError):
                    ReviewedLink(left, right, value)
                with self.assertRaises(ValueError):
                    self.store.record_equivalence(
                        "invalid", left, right, a, b, actor_ref="actor", review_ref=value,
                        reviewed_at=self.now, now=self.now, variant_equivalence_confirmed=True)
                # Defend the consuming boundary even if a caller bypasses frozen dataclass checks.
                forged = ReviewedLink(left, right, "valid")
                object.__setattr__(forged, "review_ref", value)
                with self.assertRaises(ValueError):
                    market_comparison(quotes, (forged,), **options)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM equivalences").fetchone()[0], 0)
        for i, value in enumerate(("A", "A_z.9-", "x" * 128)):
            with self.subTest(value=value):
                link = approve_pair(proposal, value, variant_equivalence_confirmed=True)
                self.assertEqual(market_comparison(quotes, (link,), **options).stats.count, 2)
                review_id = f"valid-{i}"
                self.assertTrue(self.store.record_equivalence(
                    review_id, left, right, a, b, actor_ref="actor", review_ref=value,
                    reviewed_at=self.now, now=self.now, variant_equivalence_confirmed=True))
                saved = self.store.review("equivalence", review_id)["payload"]["link"]
                restored = ReviewedLink(tuple(saved["left_key"]), tuple(saved["right_key"]), saved["review_ref"])
                self.assertEqual(restored, link)
                self.assertEqual(market_comparison(quotes, (restored,), **options).stats.count, 2)

    def test_foreign_key_and_review_payload_integrity(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db:
                self.db.execute("INSERT INTO products VALUES ('missing','001')")
        self.ingest(self.capture())
        self.store.record_evaluation("eval",self.key(),None,(),actor_ref="fixture-reviewer",
                                     as_of=self.now,max_age=timedelta(days=1),now=self.now)
        with self.db:
            self.db.execute("UPDATE evaluations SET payload='{}' WHERE id='eval'")
        with self.assertRaisesRegex(ValueError,"integrity"):
            self.store.review("evaluation","eval")
