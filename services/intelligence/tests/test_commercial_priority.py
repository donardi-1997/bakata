import hashlib
import json
import sqlite3
import unittest
from datetime import datetime,timedelta,timezone
from intelligence.alert_ledger import AlertLedger,ZERO
from intelligence.commercial import Capture
from intelligence.commercial_priority import prioritize
from intelligence.dropify_bridge import BridgeArchive
from intelligence.scoring import UnitEconomics,CriterionReview,REVIEW_CRITERIA
from intelligence.sources import SourceKind,SourceSpec,SourceRegistry
from intelligence.storage import CommercialStore


class PriorityTests(unittest.TestCase):
    def setUp(self):
        self.db,self.cdb,self.adb=[sqlite3.connect(":memory:") for _ in range(3)]
        for db in (self.db,self.cdb,self.adb):
            self.addCleanup(db.close)
        self.bridge=BridgeArchive(self.db)
        self.commercial=CommercialStore(self.cdb)
        self.ledger=AlertLedger(self.adb,"fixture-priority",500)
        self.now=datetime(2026,11,26,20,tzinfo=timezone.utc)
        self.at=self.now-timedelta(hours=1)
        self.row={"external_id":"96","sku":"025216","title":"Fixture","type":"simple",
                  "base_price":"6300.22","suggested_price":"17000","simple_stock":412,
                  "categories":["Cocina"],"warehouse":"Fixture"}
        self.ingest(self.now-timedelta(hours=2),dict(self.row,base_price="7000.25"))
        self.ingest(self.at,self.row)
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
        self.link("link-1")
        self.ledger.collect(self.db,store="7",now=self.now)

    def ingest(self,at,row,store="7"):
        self.db.execute("PRAGMA query_only=OFF")
        raw=json.dumps({"schema":"bakata-dropify-bridge-v1","captured_at":at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "store_id":store,"page":1,"page_size":10,"offset":0,"possible_next":False,
            "approval_ref":"fixture-approval","query_sha256":hashlib.sha256(b"").hexdigest(),"rows":[row]}).encode()
        self.bridge.ingest(raw,"fixture",self.now)

    def link(self,id):
        self.db.execute("PRAGMA query_only=OFF")
        self.bridge.link_score(id,("7","96",self.at.isoformat()),self.commercial,"eval-1",mapping_ref="map",
            cost_ref="reviewed-cost",actor_ref="reviewer",reviewed_cost_minor=2500000,now=self.now)

    def report(self,**changes):
        args=dict(archive_ref="fixture-priority",threshold=500,store="7",now=self.now,
                  min_score_bps=7500,min_margin_bps=2500)
        args.update(changes)
        return prioritize(self.adb,self.db,self.cdb,**args)

    def test_revalidated_candidate_and_read_only(self):
        r=self.report()
        item=r["items"][0]
        self.assertEqual(item["bucket"],"candidate-for-review")
        self.assertEqual(item["evaluation"]["contribution_minor"],1472000)
        self.assertEqual(item["evaluation"]["score"],"77.77")
        self.assertFalse(r["approval_granted"])
        self.assertFalse(r["global_ranking"])
        for db in (self.adb,self.db,self.cdb):
            self.assertEqual(db.execute("PRAGMA query_only").fetchone()[0],1)
            self.assertFalse(db.in_transaction)

    def test_policy_uses_unrounded_contribution(self):
        self.assertEqual(self.report(min_margin_bps=2583)["items"][0]["bucket"],"below-policy")
        self.assertEqual(self.report(min_score_bps=8000)["items"][0]["bucket"],"below-policy")

    def test_multiple_links_never_pick_highest(self):
        self.link("link-2")
        item=self.report()["items"][0]
        self.assertEqual(item["bucket"],"evidence-review")
        self.assertEqual(item["reasons"],["multiple-current-links"])
        self.assertIsNone(item["evaluation"])

    def test_stock_zero_overrides_potential(self):
        self.ingest(self.now,dict(self.row,simple_stock=0))
        item=self.report()["items"][0]
        self.assertEqual(item["bucket"],"urgent-review")
        self.assertIn("positive-simple-stock-not-reported",item["reasons"])
        self.assertFalse(item["current_opportunity_signal"])
        self.assertIsNone(item["evaluation"])

    def test_old_signal_not_current(self):
        self.ingest(self.now,self.row)
        item=self.report()["items"][0]
        self.assertEqual(item["bucket"],"monitor")
        self.assertFalse(item["current_opportunity_signal"])

    def test_resolved_excluded_and_scope(self):
        sid=self.ledger.list(store="7")["items"][0]["alert"]["signal"]["signal_id"]
        self.ledger.transition(sid,event_id="resolved",to="resolved",actor_ref="fixture",
            reason_ref="ticket",expected_previous_sha256=ZERO,now=self.now)
        self.assertEqual(self.report()["items"],[])
        self.assertEqual(self.report(store="8")["items"],[])

    def test_expired_and_corrupt_review(self):
        self.assertEqual(self.report(now=self.now+timedelta(days=1))["items"][0]["bucket"],"urgent-review")
        self.cdb.execute("PRAGMA query_only=OFF")
        self.cdb.execute("UPDATE evaluations SET payload=payload||' '")
        self.cdb.commit()
        item=self.report()["items"][0]
        self.assertEqual(item["bucket"],"evidence-review")
        self.assertIsNone(item["evaluation"])

    def test_unresolved_current_risk_overrides_score(self):
        # New observation includes a price decrease and a suggested-price increase.
        self.ingest(self.now,dict(self.row,base_price="5000",suggested_price="20000"))
        self.ledger.collect(self.db,store="7",now=self.now)
        item=self.report()["items"][0]
        self.assertEqual(item["bucket"],"urgent-review")
        self.assertIn("unresolved-current-risk",item["reasons"])
        self.assertTrue(item["current_opportunity_signal"])
