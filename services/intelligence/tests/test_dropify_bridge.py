import json
import sqlite3
import unittest
from datetime import datetime, timezone, timedelta

from intelligence.dropify_bridge import BridgeArchive
from intelligence.storage import CommercialStore
from intelligence.sources import SourceKind, SourceSpec, SourceRegistry
from intelligence.commercial import Capture
from intelligence.scoring import UnitEconomics, CriterionReview, REVIEW_CRITERIA


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.bridge=BridgeArchive(self.db)
        self.now=datetime(2026,11,26,20,tzinfo=timezone.utc)
        self.row={"external_id":"96","sku":"025216","title":"Fixture",
                  "type":"simple","base_price":"7000.25","suggested_price":"17000",
                  "simple_stock":412,"categories":["Cocina"],"warehouse":"Fixture"}

    def raw(self,rows=None,**changes):
        return json.dumps(dict({"schema":"bakata-dropify-bridge-v1","captured_at":"2026-11-26T19:00:00Z",
            "store_id":"7","page":2,"page_size":10,"offset":10,"possible_next":False,
            "rows":rows if rows is not None else [self.row]},**changes)).encode()

    def ingest(self,raw):
        return self.bridge.ingest(raw,"reviewer",self.now)

    def test_archive_replay_history_and_filters(self):
        raw=self.raw()
        self.assertEqual(self.ingest(raw)["inserted"],1)
        self.assertEqual(self.ingest(raw)["inserted"],0)
        self.assertEqual(self.bridge.candidates(store="7",query="025216",category="Cocina",in_stock=True)[0]["base_price"],"7000.25")
        self.ingest(self.raw([dict(self.row,simple_stock=0)],captured_at="2026-11-26T19:30:00Z"))
        self.assertEqual(self.bridge.candidates(store="7",in_stock=True),[])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0],2)
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(),[])
        BridgeArchive(self.db)

    def test_invalid_contract_and_conflicts(self):
        for raw in (self.raw(offset=20),self.raw(possible_next=True),
                    self.raw([dict(self.row,token="secret")]),self.raw([dict(self.row,base_price=7000.25)]),
                    self.raw([dict(self.row,type="unresolved")]),self.raw([self.row,self.row])):
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                self.ingest(raw)
        self.ingest(self.raw())
        with self.assertRaisesRegex(ValueError,"Conflicting"):
            self.ingest(self.raw([dict(self.row,external_id="97"),dict(self.row,base_price="1")]))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0],1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM pages").fetchone()[0],1)

    def test_empty_page_is_not_coverage(self):
        self.assertEqual(self.ingest(self.raw([]))["inserted"],0)
        self.assertEqual(self.db.execute("SELECT rows FROM pages").fetchone()[0],0)

    def test_score_link_requires_independent_reviewed_cost(self):
        self.ingest(self.raw())
        db=sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        commercial=CommercialStore(db)
        at=self.now-timedelta(hours=1)
        registry=SourceRegistry((SourceSpec("fixture-a","a.invalid",SourceKind.AUTHORIZED_CSV,
                                            "fixture-approval",self.now+timedelta(days=1)),))
        capture=Capture("fixture-a","https://a.invalid/export",at,
                        b"external_id,title,url,currency,price_minor\n001,Fixture,https://a.invalid/item,COP,4990000\n")
        commercial.ingest(registry,capture,now=self.now)
        key=("fixture-a","001",at.isoformat())
        econ=UnitEconomics(key,"reviewed-cost",self.now,"COP",5700000,2500000,1200000,100000,200000,0,400)
        reviews=tuple(CriterionReview(key,k,75,"ev-"+k,self.now,"Fixture") for k in REVIEW_CRITERIA)
        commercial.record_evaluation("eval-1",key,econ,reviews,actor_ref="reviewer",
                                     as_of=self.now,max_age=timedelta(days=1),now=self.now)
        bridge_key=("7","96",at.isoformat())
        kwargs=dict(mapping_ref="map",cost_ref="reviewed-cost",actor_ref="reviewer",reviewed_cost_minor=2500000,now=self.now)
        with self.assertRaisesRegex(ValueError,"independently reviewed"):
            self.bridge.link_score("bad",bridge_key,commercial,"eval-1",**dict(kwargs,reviewed_cost_minor=700025))
        with self.assertRaisesRegex(ValueError,"independently reviewed"):
            self.bridge.link_score("bad",bridge_key,commercial,"eval-1",**dict(kwargs,cost_ref="unverified"))
        result=self.bridge.link_score("link-1",bridge_key,commercial,"eval-1",**kwargs)
        self.assertEqual(result["score"],"77.77")
        self.assertEqual(result["mode"],"review-reference-only")
        with self.assertRaises(ValueError):
            self.bridge.link_score("stale",bridge_key,commercial,"eval-1",**dict(kwargs,now=self.now+timedelta(days=2)))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM score_links").fetchone()[0],1)
