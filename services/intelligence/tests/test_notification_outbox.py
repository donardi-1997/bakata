import os
import sqlite3
import unittest
from datetime import timedelta
from unittest.mock import patch
import test_commercial_priority as priority_fixture
from intelligence.notification_outbox import Outbox


class OutboxTests(unittest.TestCase):
    def setUp(self):
        self.f=priority_fixture.PriorityTests()
        self.addCleanup(self.f.doCleanups)
        self.f.setUp()
        self.db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.out=Outbox(self.db,archive_ref="fixture-priority",threshold=500,
            min_score_bps=7500,min_margin_bps=2500,daily_limit=1)
        self.sources=(self.f.adb,self.f.db,self.f.cdb)
        self.now=self.f.now

    def collect(self,now=None):
        return self.out.collect(*self.sources,store="7",now=now or self.now)

    def item(self):
        return self.out.list(store="7")["items"][0]

    def rehearse(self,now=None):
        h=self.item()
        with patch.dict(os.environ,{"BAKATA_CI_FIXTURES":"1"}):
            return self.out.rehearse(*self.sources,nid=h["intent"]["id"],
                expected_sha256=h["intent_sha256"],now=now or self.now)

    def test_dedup_and_minimized_payload(self):
        self.assertEqual(self.collect()["counts"]["inserted"],1)
        self.assertEqual(self.collect()["counts"]["duplicates"],1)
        p=self.item()["intent"]
        self.assertEqual(p["bucket"],"candidate-for-review")
        self.assertNotIn("title",p)
        self.assertNotIn("economics",p)
        self.assertFalse(p["delivery_enabled"])
        self.assertEqual(self.item()["state"],"pending")

    def test_rehearsal_receipt_once(self):
        self.collect()
        h=self.item()
        with patch.dict(os.environ,{"BAKATA_CI_FIXTURES":"0"}),self.assertRaises(ValueError):
            self.out.rehearse(*self.sources,nid=h["intent"]["id"],expected_sha256=h["intent_sha256"],now=self.now)
        receipt=self.rehearse()
        self.assertEqual(receipt["result"],"simulated")
        self.assertFalse(receipt["external_delivery"])
        with self.assertRaisesRegex(ValueError,"already handled"):
            self.rehearse()

    def test_changed_evidence_suppresses(self):
        self.collect()
        self.f.ingest(self.now,dict(self.f.row,simple_stock=0))
        self.assertEqual(self.rehearse()["result"],"suppressed")

    def test_expired(self):
        self.collect()
        self.assertEqual(self.rehearse(self.now+timedelta(hours=1))["result"],"expired")

    def test_daily_limit_and_new_risk(self):
        self.collect()
        self.f.ingest(self.now,dict(self.f.row,simple_stock=0))
        result=self.collect()
        self.assertEqual(result["counts"]["rate_limited"],1)
        # The next day the stale observation is itself a review risk.
        self.assertEqual(self.collect(self.now+timedelta(days=1))["counts"]["inserted"],1)
        self.assertEqual(len(self.out.list(store="7")["items"]),2)

    def test_policy_and_append_only(self):
        self.collect()
        with self.assertRaises(ValueError):
            Outbox(self.db,archive_ref="fixture-priority",threshold=500,min_score_bps=8000,min_margin_bps=2500,daily_limit=1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("DELETE FROM intents")
        self.db.rollback()
        self.rehearse()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE receipts SET payload='{}'")
        self.db.rollback()
