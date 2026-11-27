import sqlite3
import unittest
from datetime import timedelta
from unittest.mock import patch
import test_commercial_priority as fixture
from intelligence.batch_runs import BatchRuns,ZERO


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.PriorityTests()
        self.addCleanup(self.f.doCleanups)
        self.f.setUp()
        self.db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.runs=BatchRuns(self.db)
        self.sources=(self.f.adb,self.f.db,self.f.cdb)
        self.now=self.f.now
        self.create()

    def create(self,**changes):
        args=dict(archive_ref="fixture-priority",store="7",threshold=500,min_score_bps=7500,
                  min_margin_bps=2500,batch_size=1,source_ref="fixture-files",now=self.now)
        args.update(changes)
        return self.runs.create("run-1",**args)

    def step(self,checkpoint=ZERO,**changes):
        args=dict(run_id="run-1",source_ref="fixture-files",expected_checkpoint_sha256=checkpoint,now=self.now)
        args.update(changes)
        return self.runs.step(*self.sources,**args)

    def test_completed_checkpoint_and_page(self):
        self.assertFalse(self.create())
        result=self.step()
        self.assertEqual(result["state"],"completed")
        h=self.runs.status("run-1")
        self.assertEqual(h["checkpoint_sha256"],result["checkpoint_sha256"])
        page=self.runs.page("run-1",1)
        self.assertEqual(page["report"]["items"][0]["bucket"],"candidate-for-review")
        self.assertEqual(page["sha256"],result["checkpoint_sha256"])
        self.assertFalse(h["global_snapshot"])
        with self.assertRaisesRegex(ValueError,"already completed"):
            self.step(result["checkpoint_sha256"])

    def test_failure_rolls_back_and_can_resume(self):
        with patch("intelligence.batch_runs.prioritize",side_effect=RuntimeError("fixture interruption")):
            with self.assertRaises(RuntimeError):
                self.step()
        self.assertEqual(self.runs.status("run-1")["checkpoint_sha256"],ZERO)
        self.assertEqual(self.runs.status("run-1")["pages"],0)
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(self.step()["state"],"completed")

    def test_multiple_pages_and_stale_checkpoint(self):
        self.f.ingest(self.f.at,dict(self.f.row,external_id="97"))
        self.f.ledger.collect(self.f.db,store="7",now=self.now)
        first=self.step()
        self.assertEqual(first["next_after"],"96")
        with self.assertRaisesRegex(ValueError,"Checkpoint changed"):
            self.step()
        second=self.step(first["checkpoint_sha256"],now=self.now+timedelta(seconds=1))
        self.assertEqual(second["state"],"completed")
        self.assertEqual(self.runs.page("run-1",2)["previous_sha256"],first["checkpoint_sha256"])
        self.assertEqual(self.runs.status("run-1")["pages"],2)

    def test_empty_filtered_page_still_advances(self):
        from intelligence.alert_ledger import ZERO as ALERT_ZERO
        sid=self.f.ledger.list(store="7")["items"][0]["alert"]["signal"]["signal_id"]
        self.f.ledger.transition(sid,event_id="resolved",to="resolved",actor_ref="fixture",
            reason_ref="ticket",expected_previous_sha256=ALERT_ZERO,now=self.now)
        self.f.ingest(self.f.at,dict(self.f.row,external_id="97"))
        self.f.ledger.collect(self.f.db,store="7",now=self.now)
        result=self.step()
        self.assertEqual(result["next_after"],"96")
        self.assertEqual(self.runs.page("run-1",1)["report"]["items"],[])
        self.assertEqual(self.step(result["checkpoint_sha256"])["state"],"completed")

    def test_policy_binding_and_clock(self):
        with self.assertRaises(ValueError):
            self.create(batch_size=2)
        with self.assertRaisesRegex(ValueError,"Source binding"):
            self.step(source_ref="different")
        with self.assertRaisesRegex(ValueError,"clock"):
            self.step(now=self.now-timedelta(seconds=1))
        self.assertEqual(self.runs.status("run-1")["pages"],0)

    def test_append_only_and_read_only_sources(self):
        self.step()
        for db in self.sources:
            self.assertEqual(db.execute("PRAGMA query_only").fetchone()[0],1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("DELETE FROM pages")
        self.db.rollback()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE runs SET payload='{}'")
        self.db.rollback()

    def test_invalid_cursor_rejects_without_commit(self):
        report={"next_after":"0","scanned_products":1,"items":[],"counts":{}}
        with patch("intelligence.batch_runs.prioritize",return_value=report):
            with self.assertRaises(ValueError):
                self.step()
        self.assertEqual(self.runs.status("run-1")["pages"],0)
