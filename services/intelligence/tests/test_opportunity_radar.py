import hashlib
import json
import sqlite3
import unittest
from datetime import datetime,timedelta,timezone
from intelligence.dropify_bridge import BridgeArchive
from intelligence.opportunity_radar import scan,price_change


class RadarTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.archive=BridgeArchive(self.db)
        self.now=datetime(2026,11,26,20,tzinfo=timezone.utc)
        self.row={"external_id":"96","sku":"025216","title":"Fixture",
            "type":"simple","base_price":"7000.25","suggested_price":"17000",
            "simple_stock":412,"categories":["Cocina"],"warehouse":"Fixture"}

    def ingest(self,age,rows,store="7"):
        at=self.now-timedelta(hours=age)
        raw=json.dumps({"schema":"bakata-dropify-bridge-v1","captured_at":at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "store_id":store,"page":1,"page_size":10,"offset":0,"possible_next":len(rows)==10,
            "approval_ref":"fixture-"+str(age),"query_sha256":hashlib.sha256(b"").hexdigest(),"rows":rows}).encode()
        return self.archive.ingest(raw,"fixture-operator",self.now)["sha256"]

    def scan(self,**changes):
        args=dict(store="7",now=self.now,price_threshold_bps=500)
        args.update(changes)
        return scan(self.db,**args)

    def test_changes_with_provenance(self):
        old=self.ingest(2,[self.row])
        new=self.ingest(1,[dict(self.row,base_price="6300.22",simple_stock=0)])
        result=self.scan()
        self.assertEqual(result["counts"]["comparable_pairs"],1)
        self.assertEqual([s["code"] for s in result["signals"]],["stock-zero","price-decreased"])
        price=result["signals"][1]
        self.assertEqual(price["change_pct"],"-10.00")
        self.assertEqual(price["current_pages"][0]["page_sha256"],new)
        self.assertEqual(price["previous_pages"][0]["page_sha256"],old)
        self.assertEqual(self.scan(),result)
        self.assertFalse(result["profitability_verified"])
        self.assertFalse(result["availability_verified"])
        self.assertEqual(self.db.execute("PRAGMA query_only").fetchone()[0],1)

    def test_threshold_zero_and_unknown(self):
        self.assertIsNone(price_change("1.00","1",500))
        self.assertIsNone(price_change("100","104.99",500))
        self.assertEqual(price_change("100","105",500),("price-increased","5.00"))
        self.assertEqual(price_change("0","1",500),("price-from-zero",None))
        self.assertEqual(price_change("1",None,500),("price-unknown",None))
        self.ingest(2,[self.row])
        self.ingest(1,[dict(self.row,base_price=None,simple_stock=None)])
        self.assertEqual({s["code"] for s in self.scan()["signals"]},{"price-unknown","stock-unknown"})

    def test_scope_change_suppresses_comparison(self):
        self.ingest(2,[self.row])
        self.ingest(1,[dict(self.row,sku="changed",warehouse="Other",base_price="1",simple_stock=0)])
        r=self.scan()
        self.assertEqual(r["counts"]["identity_changed"],1)
        self.assertEqual({s["code"] for s in r["signals"]},{"comparison-scope-changed"})
        self.assertEqual({s["field"] for s in r["signals"]},{"sku","warehouse"})

    def test_stale_baseline_and_missing_rows(self):
        self.ingest(24*31,[dict(self.row,external_id="97")])
        self.ingest(30,[dict(self.row,external_id="98")])
        self.ingest(1,[self.row,dict(self.row,external_id="97")])
        self.ingest(0,[])
        r=self.scan()
        self.assertEqual({s["code"] for s in r["signals"]},{"first-observation","baseline-too-old","capture-stale"})
        self.assertEqual(r["counts"]["scanned"],3)
        self.assertFalse(r["coverage_verified"])

    def test_pagination_and_store_isolation(self):
        self.ingest(1,[self.row,dict(self.row,external_id="100"),dict(self.row,external_id="99")])
        self.ingest(1,[self.row],store="8")
        a=self.scan(limit=2)
        b=self.scan(after=a["next_after"],limit=2)
        self.assertEqual(a["next_after"],"96")
        self.assertIsNone(b["next_after"])
        self.assertEqual({s["external_id"] for s in a["signals"]+b["signals"]},{"96","99","100"})
        self.assertTrue(all(s["store_id"]=="7" for s in a["signals"]+b["signals"]))

    def test_superseded_link_and_restock(self):
        self.ingest(2,[dict(self.row,simple_stock=0)])
        at=(self.now-timedelta(hours=2)).isoformat()
        # Simulate an archived historical reference; not evidence of a valid review.
        self.db.execute("INSERT INTO score_links VALUES (?,?,?,?,?,?,?)",
            ("old","7","96",at,"eval","a"*64,"{}"))
        self.db.commit()
        self.ingest(1,[self.row])
        self.assertEqual({s["code"] for s in self.scan()["signals"]},
                         {"evaluation-observation-superseded","stock-reappeared"})

    def test_corrupt_provenance_rejected(self):
        self.ingest(1,[self.row])
        self.db.execute("DELETE FROM page_rows")
        self.db.commit()
        with self.assertRaisesRegex(ValueError,"provenance"):
            self.scan()
