import hashlib
import json
import sqlite3
import unittest
from datetime import datetime, timezone
from intelligence.catalog_review import export_page
from intelligence.dropify_bridge import BridgeArchive


class CatalogReviewTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.archive=BridgeArchive(self.db)
        self.now=datetime(2026,11,26,20,tzinfo=timezone.utc)
        self.row={"external_id":"96","sku":"025216","title":"Fixture <script>unsafe</script>",
            "type":"simple","base_price":"7000.25","suggested_price":None,"simple_stock":0,
            "categories":["Cocina"],"warehouse":"Fixture"}

    def ingest(self, rows):
        raw=json.dumps({"schema":"bakata-dropify-bridge-v1","captured_at":"2026-11-26T19:00:00Z",
            "store_id":"7","page":1,"page_size":10,"offset":0,"possible_next":False,
            "approval_ref":"fixture-approval","query_sha256":hashlib.sha256(b"").hexdigest(),"rows":rows}).encode()
        return self.archive.ingest(raw,"fixture-reviewer",self.now)["sha256"]

    def test_roundtrip_and_read_only(self):
        sha=self.ingest([self.row])
        raw=export_page(self.db,sha,now=self.now)
        data=json.loads(raw)
        self.assertEqual(data["snapshot"]["rows"],[self.row])
        self.assertEqual(data["source_page_sha256"],sha)
        self.assertEqual(data["operator_ref"],"fixture-reviewer")
        self.assertNotIn("score",data["snapshot"]["rows"][0])
        self.assertEqual(self.db.execute("PRAGMA query_only").fetchone()[0],1)
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(export_page(self.db,sha,now=self.now),raw)

    def test_empty_page_preserved(self):
        sha=self.ingest([])
        self.assertEqual(json.loads(export_page(self.db,sha,now=self.now))["snapshot"]["rows"],[])

    def test_missing_and_corrupt(self):
        sha=self.ingest([self.row])
        self.db.execute("UPDATE pages SET rows=2")
        self.db.commit()
        with self.assertRaises(ValueError):
            export_page(self.db,sha,now=self.now)
        with self.assertRaises(ValueError):
            export_page(self.db,"b"*64,now=self.now)
