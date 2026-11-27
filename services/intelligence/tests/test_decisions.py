import hashlib
import json
import sqlite3
import unittest
from datetime import datetime, timezone, timedelta

from intelligence.commercial import Capture
from intelligence.dropify_bridge import BridgeArchive
from intelligence.decisions import DecisionLedger, ZERO
from intelligence.scoring import UnitEconomics, CriterionReview, REVIEW_CRITERIA
from intelligence.sources import SourceKind, SourceSpec, SourceRegistry
from intelligence.storage import CommercialStore


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.commercial_db=sqlite3.connect(":memory:")
        self.ledger_db=sqlite3.connect(":memory:")
        for db in (self.db,self.commercial_db,self.ledger_db):
            self.addCleanup(db.close)
        self.bridge=BridgeArchive(self.db)
        self.commercial=CommercialStore(self.commercial_db)
        self.ledger=DecisionLedger(self.ledger_db,"fixture-archive")
        self.now=datetime(2026,11,26,20,tzinfo=timezone.utc)
        self.at=self.now-timedelta(hours=1)
        self.key=("7","96",self.at.isoformat())
        row={"external_id":"96","sku":"025216","title":"Fixture","type":"simple",
             "base_price":"7000.25","suggested_price":"17000","simple_stock":412,
             "categories":["Cocina"],"warehouse":"Fixture"}
        raw=json.dumps({"schema":"bakata-dropify-bridge-v1","captured_at":self.at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "store_id":"7","page":1,"page_size":10,"offset":0,"possible_next":False,
            "approval_ref":"fixture-approval","query_sha256":hashlib.sha256(b"").hexdigest(),"rows":[row]}).encode()
        self.bridge.ingest(raw,"fixture-operator",self.now)
        registry=SourceRegistry((SourceSpec("fixture-a","a.invalid",SourceKind.AUTHORIZED_CSV,
                                            "fixture-approval",self.now+timedelta(days=1)),))
        capture=Capture("fixture-a","https://a.invalid/export",self.at,
                        b"external_id,title,url,currency,price_minor\n001,Fixture,https://a.invalid/item,COP,4990000\n")
        self.commercial.ingest(registry,capture,now=self.now)
        key=("fixture-a","001",self.at.isoformat())
        econ=UnitEconomics(key,"reviewed-cost",self.now,"COP",5700000,2500000,1200000,100000,200000,0,400)
        reviews=tuple(CriterionReview(key,k,75,"ev-"+k,self.now,"Fixture") for k in REVIEW_CRITERIA)
        self.commercial.record_evaluation("eval-1",key,econ,reviews,actor_ref="reviewer",
                                          as_of=self.now,max_age=timedelta(days=1),now=self.now)
        self.bridge.link_score("link-1",self.key,self.commercial,"eval-1",mapping_ref="map",cost_ref="reviewed-cost",
                               actor_ref="reviewer",reviewed_cost_minor=2500000,now=self.now)

    def preview(self):
        return self.ledger.preview(self.db,self.commercial_db,"link-1",now=self.now)

    def record(self,preview=None,**changes):
        preview=preview or self.preview()
        args=dict(event_id="decision-1",action="approve-for-draft-review",actor_ref="reviewer",
                  reason_ref="review-ticket",expected_dossier_sha256=preview["dossier_sha256"],
                  expected_previous_sha256=preview["previous_sha256"],now=self.now)
        args.update(changes)
        return self.ledger.record(self.db,self.commercial_db,"link-1",**args)

    def status(self,now=None):
        return self.ledger.status(self.db,self.commercial_db,"7","96",now=now or self.now)

    def test_approval_only_for_draft_review(self):
        p=self.preview()
        self.assertEqual(p["previous_sha256"],ZERO)
        event=self.record(p,now=self.now+timedelta(seconds=1))
        self.assertEqual(event["evaluation_id"],"eval-1")
        self.assertEqual(event["contribution_minor"],1472000)
        self.assertFalse(event["publication_authorized"])
        self.assertFalse(event["woo_mutation"])
        self.assertTrue(self.status(self.now+timedelta(seconds=2))["draft_review_eligible"])
        self.assertEqual(self.db.execute("PRAGMA query_only").fetchone()[0],1)
        self.assertEqual(self.commercial_db.execute("PRAGMA query_only").fetchone()[0],1)

    def test_reject_and_defer_supersede_approval(self):
        a=self.record()
        b=self.record(event_id="decision-2",action="reject")
        c=self.record(event_id="decision-3",action="defer")
        self.assertEqual(b["previous_sha256"],a["sha256"])
        self.assertEqual(c["previous_sha256"],b["sha256"])
        self.assertEqual(len(self.ledger.history("7","96")),3)
        self.assertEqual(self.status()["state"],"defer")
        self.assertFalse(self.status()["draft_review_eligible"])

    def test_conflicts_and_replay(self):
        p=self.preview()
        with self.assertRaisesRegex(ValueError,"Evidence differs"):
            self.record(p,expected_dossier_sha256="a"*64)
        self.record(p)
        with self.assertRaisesRegex(ValueError,"Decision changed"):
            self.record(p,event_id="other")
        with self.assertRaisesRegex(ValueError,"already used"):
            self.record()
        self.assertEqual(len(self.ledger.history("7","96")),1)

    def test_expiry_and_append_only(self):
        self.record()
        self.assertEqual(self.status(self.now+timedelta(days=1))["state"],"requires-revalidation")
        with self.assertRaises(sqlite3.IntegrityError):
            self.ledger_db.execute("DELETE FROM decisions")
        self.ledger_db.rollback()
        with self.assertRaises(sqlite3.IntegrityError):
            self.ledger_db.execute("UPDATE decisions SET payload='{}'")
        self.ledger_db.rollback()
        with self.assertRaises(ValueError):
            DecisionLedger(self.ledger_db,"other-archive")

    def test_invalid_action_and_no_decision(self):
        self.assertEqual(self.status()["state"],"undecided")
        with self.assertRaises(ValueError):
            self.record(action="publish")
        self.assertEqual(self.ledger.history("7","96"),[])
