import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from intelligence.dropify_bridge import BridgeArchive
from intelligence.dropify_capture import capture,policy,approval


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.root=tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.workspace=Path(self.root.name)/"run"
        self.db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.archive=BridgeArchive(self.db)
        self.now=1795748400
        self.plan=policy("fixture","7",1,3,self.now+1200,"reviewer","fixture-files")
        self.calls=[]
        self.partial=True
        self.overlap=False
        self.fail=False

    def pause(self,seconds):
        self.now+=seconds

    def fetch(self,run,store,page):
        self.calls.append(page)
        if self.fail:
            raise ValueError("Fixture failure")
        start=1+(page-1)*10
        if self.overlap and page==2:
            start=1
        rows=[{"external_id":str(i),"sku":str(i),"title":"Fixture","type":"simple",
            "base_price":"7000.25","suggested_price":None,"simple_stock":5,"categories":[],"warehouse":"Fixture"}
            for i in range(start,start+(3 if self.partial and page==2 else 10))]
        return json.dumps({"schema":"bakata-dropify-bridge-v1","captured_at":datetime.fromtimestamp(self.now,timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "store_id":store,"page":page,"page_size":10,"offset":(page-1)*10,"possible_next":len(rows)==10,
            "approval_ref":approval(run,page),"query_sha256":hashlib.sha256(b"").hexdigest(),"rows":rows}).encode()

    def run_capture(self):
        return capture(self.workspace,self.archive,self.plan,self.fetch,clock=lambda:self.now,pause=self.pause)

    def test_partial_and_replay(self):
        result=self.run_capture()
        self.assertEqual(result["unique_ids_in_window"],13)
        self.assertEqual(result["stop_reason"],"partial-or-empty-page")
        self.assertEqual(self.calls,[1,2])
        self.assertEqual(self.run_capture()["connector_calls_this_execution"],0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0],13)
        self.assertFalse(result["coverage_verified"])

    def test_uncertain_attempt_never_retried(self):
        self.fail=True
        with self.assertRaises(ValueError):
            self.run_capture()
        self.fail=False
        with self.assertRaisesRegex(ValueError,"Uncertain"):
            self.run_capture()
        self.assertEqual(self.calls,[1])

    def test_overlap_stops_and_preserves_evidence(self):
        self.overlap=True
        with self.assertRaisesRegex(ValueError,"Pagination anomaly"):
            self.run_capture()
        self.assertEqual(self.calls,[1,2])
        self.assertTrue((self.workspace/"page-002.json").is_file())
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM pages").fetchone()[0],1)
        with self.assertRaisesRegex(ValueError,"Pagination anomaly"):
            self.run_capture()
        self.assertEqual(self.calls,[1,2])

    def test_durable_page_before_archive_recovery(self):
        from unittest.mock import patch
        with patch.object(self.archive,"ingest",side_effect=RuntimeError("interrupted")):
            with self.assertRaises(RuntimeError):
                self.run_capture()
        self.assertTrue((self.workspace/"page-001.json").is_file())
        self.assertEqual(self.run_capture()["pages_archived"],2)
        self.assertEqual(self.calls,[1,2])

    def test_bounded_run_and_changed_scope(self):
        self.partial=False
        result=self.run_capture()
        self.assertEqual(result["unique_ids_in_window"],30)
        self.assertEqual(result["next_page"],4)
        self.plan=dict(self.plan,store="8")
        with self.assertRaisesRegex(ValueError,"scope changed"):
            self.run_capture()
        self.assertEqual(self.calls,[1,2,3])

    def test_expiry_during_pause(self):
        self.plan=dict(self.plan,until=self.now+5)
        result=self.run_capture()
        self.assertEqual(result["stop_reason"],"authorization-expired")
        self.assertEqual(result["next_page"],2)
        self.assertEqual(self.calls,[1])
        self.assertEqual(self.run_capture()["connector_calls_this_execution"],0)
