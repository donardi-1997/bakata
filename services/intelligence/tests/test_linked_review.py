import hashlib
import json
import sqlite3
import unittest
from datetime import datetime, timezone, timedelta

from intelligence.commercial import Capture
from intelligence.dropify_bridge import BridgeArchive
from intelligence.linked_review import get_dossier
from intelligence.scoring import UnitEconomics, CriterionReview, REVIEW_CRITERIA
from intelligence.sources import SourceKind, SourceSpec, SourceRegistry
from intelligence.storage import CommercialStore


class LinkedReviewTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.commercial_db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.addCleanup(self.commercial_db.close)
        self.bridge=BridgeArchive(self.db)
        self.commercial=CommercialStore(self.commercial_db)
        self.now=datetime(2026,11,26,20,tzinfo=timezone.utc)
        self.at=self.now-timedelta(hours=1)
        self.key=("7","96",self.at.isoformat())
        self.row={"external_id":"96","sku":"025216","title":"Fixture","type":"simple",
                  "base_price":"7000.25","suggested_price":"17000","simple_stock":412,
                  "categories":["Cocina"],"warehouse":"Fixture"}
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
        self.bridge.link_score("link-1",self.key,self.commercial,"eval-1",mapping_ref="map",cost_ref="reviewed-cost",
                               actor_ref="reviewer",reviewed_cost_minor=2500000,now=self.now)

    def ingest(self,at,row):
        raw=json.dumps({"schema":"bakata-dropify-bridge-v1","captured_at":at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "store_id":"7","page":1,"page_size":10,"offset":0,"possible_next":False,
            "approval_ref":"fixture-approval","query_sha256":hashlib.sha256(b"").hexdigest(),"rows":[row]}).encode()
        self.bridge.ingest(raw,"reviewer",self.now)

    def dossier(self,now=None,link="link-1"):
        return get_dossier(self.db,self.commercial_db,link,now=now or self.now)

    def test_exact_economics_and_read_only(self):
        result=self.dossier()
        self.assertEqual(result["catalog"]["base_price_reported"],"7000.25")
        evaluation=result["evaluation"]
        self.assertEqual(evaluation["economics"]["supplier_cost_minor"],2500000)
        self.assertEqual(evaluation["contribution_minor"],1472000)
        self.assertEqual(evaluation["margin_pct"],"25.82")
        self.assertEqual(evaluation["score"],"77.77")
        self.assertEqual(result["valid_until"],(self.at+timedelta(days=1)).isoformat())
        self.assertFalse(result["approval_granted"])
        self.assertFalse(result["woo_mutation"])
        self.assertEqual(self.db.execute("PRAGMA query_only").fetchone()[0],1)
        self.assertEqual(self.commercial_db.execute("PRAGMA query_only").fetchone()[0],1)
        self.assertFalse(self.db.in_transaction)
        self.assertFalse(self.commercial_db.in_transaction)

    def test_stale_and_unknown(self):
        with self.assertRaisesRegex(ValueError,"Stale"):
            self.dossier(self.now+timedelta(days=1))
        with self.assertRaisesRegex(ValueError,"Unknown score link"):
            self.dossier(link="missing")

    def test_superseded_even_if_price_unchanged(self):
        self.ingest(self.now,self.row)
        with self.assertRaisesRegex(ValueError,"superseded"):
            self.dossier()

    def test_changed_cost_and_evaluation_digest(self):
        raw=self.db.execute("SELECT payload FROM score_links").fetchone()[0]
        link=json.loads(raw)
        link["reviewed_cost_minor"]=700025
        self.db.execute("UPDATE score_links SET payload=?",(json.dumps(link),))
        self.db.commit()
        with self.assertRaisesRegex(ValueError,"reviewed cost"):
            self.dossier()

    def test_corrupted_evaluation(self):
        self.commercial_db.execute("UPDATE evaluations SET payload=payload||' '")
        self.commercial_db.commit()
        with self.assertRaisesRegex(ValueError,"digest mismatch"):
            self.dossier()
