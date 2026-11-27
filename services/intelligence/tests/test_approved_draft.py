import hashlib
import json
import sqlite3
import unittest
from datetime import datetime, timezone, timedelta
from contextlib import ExitStack, closing
from intelligence.commercial import Capture
from intelligence.dropify_bridge import BridgeArchive
from intelligence.decisions import DecisionLedger
from intelligence.approved_draft import prepare
from intelligence.scoring import UnitEconomics, CriterionReview, REVIEW_CRITERIA
from intelligence.sources import SourceKind, SourceSpec, SourceRegistry
from intelligence.storage import CommercialStore


def fixture(stack, now):
    db,commercial_db,ledger_db=[stack.enter_context(closing(sqlite3.connect(":memory:"))) for _ in range(3)]
    bridge=BridgeArchive(db)
    commercial=CommercialStore(commercial_db)
    ledger=DecisionLedger(ledger_db,"fixture-approved")
    at=now-timedelta(hours=1)
    row={"external_id":"96","sku":"025216","title":"Fixture","type":"simple",
         "base_price":"7000.25","suggested_price":"17000","simple_stock":412,
         "categories":["Cocina"],"warehouse":"Fixture"}
    raw=json.dumps({"schema":"bakata-dropify-bridge-v1","captured_at":at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "store_id":"7","page":1,"page_size":10,"offset":0,"possible_next":False,
        "approval_ref":"fixture-approval","query_sha256":hashlib.sha256(b"").hexdigest(),"rows":[row]}).encode()
    bridge.ingest(raw,"fixture-operator",now)
    registry=SourceRegistry((SourceSpec("fixture-a","a.invalid",SourceKind.AUTHORIZED_CSV,
                                       "fixture-approval",now+timedelta(days=1)),))
    capture=Capture("fixture-a","https://a.invalid/export",at,
                    b"external_id,title,url,currency,price_minor\n001,Fixture,https://a.invalid/item,COP,4990000\n")
    commercial.ingest(registry,capture,now=now)
    key=("fixture-a","001",at.isoformat())
    econ=UnitEconomics(key,"reviewed-cost",now,"COP",5700000,2500000,1200000,100000,200000,0,400)
    reviews=tuple(CriterionReview(key,k,75,"ev-"+k,now,"Fixture") for k in REVIEW_CRITERIA)
    commercial.record_evaluation("eval-1",key,econ,reviews,actor_ref="reviewer",
                                 as_of=now,max_age=timedelta(days=1),now=now)
    bridge.link_score("link-1",("7","96",at.isoformat()),commercial,"eval-1",mapping_ref="map",cost_ref="reviewed-cost",
                      actor_ref="reviewer",reviewed_cost_minor=2500000,now=now)
    preview=ledger.preview(db,commercial_db,"link-1",now=now)
    event=ledger.record(db,commercial_db,"link-1",event_id="decision-1",action="approve-for-draft-review",
                        actor_ref="reviewer",reason_ref="ticket",expected_dossier_sha256=preview["dossier_sha256"],
                        expected_previous_sha256=preview["previous_sha256"],now=now)
    return ledger,db,commercial_db,event


class ApprovedDraftTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack()
        self.addCleanup(self.stack.close)
        self.now=datetime(2026,11,26,20,tzinfo=timezone.utc)
        self.ledger,self.bridge,self.commercial,self.event=fixture(self.stack,self.now)

    def plan(self,**changes):
        args=dict(decision_sha256=self.event["sha256"],reviewer_id=1,category_id=2,mapping_ref="map",
                  title="CI Approved Draft",target_bps=2500,step_minor=100000,ceiling_minor=20000000,now=self.now)
        args.update(changes)
        return prepare(self.ledger,self.bridge,self.commercial,"7","96",**args)

    def test_inert_and_independent_cost(self):
        result=self.plan()
        p=result["plan"]
        self.assertEqual(p["economics"]["supplier_cost_minor"],2500000)
        self.assertEqual(p["contribution_minor"],1472000)
        self.assertEqual(p["sellable_stock"],0)
        self.assertFalse(p["sale_price_active"])
        self.assertFalse(p["publication_authorized"])
        self.assertEqual(self.plan(),result)

    def test_reject_bad_policy_identity_and_expiry(self):
        for changes in ({"target_bps":3000},{"category_id":0},{"reviewer_id":0},{"mapping_ref":"other"},
                        {"decision_sha256":"a"*64},{"now":self.now+timedelta(days=1)}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                self.plan(**changes)

    def test_rejection_supersedes(self):
        p=self.ledger.preview(self.bridge,self.commercial,"link-1",now=self.now)
        self.ledger.record(self.bridge,self.commercial,"link-1",event_id="decision-2",action="reject",
            actor_ref="reviewer",reason_ref="ticket-2",expected_dossier_sha256=p["dossier_sha256"],
            expected_previous_sha256=p["previous_sha256"],now=self.now)
        with self.assertRaises(ValueError):
            self.plan()
