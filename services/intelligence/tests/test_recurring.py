import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from intelligence.pilot import PilotLedger, execute, utcnow
from intelligence.recurring import RecurringCapture, MIN_INTERVAL
from intelligence.storage import CommercialStore
from intelligence.transport import Response, PolicyError, FetchError


class RecurringTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger_path=Path(self.temp.name)/"pilot.sqlite"
        self.archive_path=Path(self.temp.name)/"archive.sqlite"
        self.db=sqlite3.connect(self.ledger_path)
        self.addCleanup(self.db.close)
        self.archive_db=sqlite3.connect(self.archive_path)
        self.addCleanup(self.archive_db.close)
        self.archive=CommercialStore(self.archive_db)
        self.ledger=PilotLedger(self.db)
        self.now=utcnow()
        self.data={"version":"int11-v1","enabled":True,"source":"pilot-store",
                   "host":"catalog.example.com","expected_ip":"8.8.8.8",
                   "reviewed_at":(self.now-timedelta(minutes=1)).isoformat(),
                   "approved_until":(self.now+timedelta(days=1)).isoformat(),
                   "robots_valid_until":(self.now+timedelta(hours=23)).isoformat(),
                   "robots_text":"User-agent: *\nDisallow: /private",
                   "owner_permission_ref":"synthetic-owner","terms_ref":"synthetic-terms",
                   "robots_ref":"synthetic-robots","egress_ref":"synthetic-egress"}
        self.item={"id":7,"name":"Synthetic","type":"simple","is_password_protected":False,
                   "permalink":"https://catalog.example.com/product/demo",
                   "prices":{"currency_code":"COP","currency_minor_unit":2,"price":"4990000","price_range":None}}
        self.transport=Mock(return_value=self.response())
        self.scheduler=RecurringCapture(self.db,self.archive)

    def response(self):
        return Response(200,{"content-type":"application/json"},json.dumps([self.item]).encode())

    def raw(self,**changes):
        return json.dumps(dict(self.data,**changes)).encode()

    def pilot(self):
        raw=self.raw()
        execute(raw,hashlib.sha256(raw).hexdigest(),self.ledger,transport=self.transport,archive=self.archive)
        self.transport.reset_mock()

    def configure(self,raw=None,attempts=2,interval=MIN_INTERVAL):
        raw=raw or self.raw()
        with patch("intelligence.recurring.utcnow",return_value=self.now):
            self.scheduler.configure(raw,hashlib.sha256(raw).hexdigest(),approval_ref="recurring-owner",
                                     interval=interval,attempts=attempts)

    def tick(self,hours,raw=None):
        with patch("intelligence.recurring.utcnow",return_value=self.now+timedelta(hours=hours)):
            return self.scheduler.tick(raw or self.raw(),transport=self.transport)

    def test_requires_completed_archived_pilot(self):
        with self.assertRaises(PolicyError):
            self.configure()
        self.transport.assert_not_called()
        self.pilot()
        self.configure()
        self.assertEqual(self.scheduler.list()[0]["state"],"enabled")
        self.transport.assert_not_called()

    def test_missing_archive_evidence(self):
        raw=self.raw()
        execute(raw,hashlib.sha256(raw).hexdigest(),self.ledger,transport=self.transport)
        self.transport.reset_mock()
        with self.assertRaisesRegex(PolicyError,"archive evidence"):
            self.configure()
        self.transport.assert_not_called()

    def test_frequency_history_and_exhaustion(self):
        self.pilot()
        self.configure()
        self.assertIsNone(self.tick(5))
        self.item["prices"]["price"]="4500000"
        self.transport.return_value=self.response()
        first=self.tick(6)
        self.assertEqual(first["new_observations"],1)
        self.assertEqual(first["state"],"enabled")
        self.assertIsNone(self.tick(7))
        self.assertEqual(self.tick(12)["state"],"exhausted")
        self.assertIsNone(self.tick(18))
        self.assertEqual(self.transport.call_count,2)
        history=self.archive.history("pilot-store","7",start=self.now-timedelta(minutes=1),end=self.now+timedelta(hours=13))
        self.assertEqual([r.price_minor for r in history],[4990000,4500000,4500000])

    def test_late_tick_coalesces_missed_intervals(self):
        self.pilot()
        self.configure()
        self.assertIsNotNone(self.tick(13))
        self.assertIsNone(self.tick(13))
        self.assertIsNone(self.tick(18))
        self.assertEqual(self.transport.call_count,1)

    def test_error_blocks_no_retry(self):
        self.pilot()
        self.configure()
        self.transport.return_value=Response(429,{"retry-after":"1"},b"")
        with self.assertRaises(FetchError):
            self.tick(6)
        self.assertEqual(self.scheduler.list()[0]["state"],"blocked")
        self.assertIsNone(self.tick(12))
        self.assertEqual(self.transport.call_count,1)

    def test_interrupted_reservation_not_replayed(self):
        self.pilot()
        self.configure()
        self.transport.side_effect=KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.tick(6)
        self.transport.side_effect=None
        with closing(sqlite3.connect(self.ledger_path)) as db, closing(sqlite3.connect(self.archive_path)) as archive:
            other=RecurringCapture(db,CommercialStore(archive))
            self.assertEqual(other.list()[0]["state"],"running")
            with patch("intelligence.recurring.utcnow",return_value=self.now+timedelta(hours=12)):
                self.assertIsNone(other.tick(self.raw(),transport=self.transport))
            with self.assertRaises(PolicyError):
                other.disable("catalog.example.com")
        self.assertEqual(self.transport.call_count,1)

    def test_manifest_change_disable_and_expiry(self):
        self.pilot()
        self.configure()
        with self.assertRaises(PolicyError):
            self.tick(6,self.raw(terms_ref="changed"))
        self.scheduler.disable("catalog.example.com")
        self.assertIsNone(self.tick(6))
        self.transport.assert_not_called()

    def test_expiry_before_network(self):
        self.pilot()
        self.configure()
        with patch("intelligence.recurring.load_manifest",side_effect=PolicyError("expired")):
            with self.assertRaises(PolicyError):
                self.tick(6)
        self.transport.assert_not_called()

    def test_policy_limits(self):
        self.pilot()
        for kwargs in ({"attempts":5},{"interval":300},{"interval":86401},
                       {"raw":self.raw(robots_text="User-agent: *\nCrawl-delay: 43200")},
                       {"raw":self.raw(robots_valid_until=(self.now+timedelta(hours=1)).isoformat())}):
            with self.subTest(kwargs=kwargs),self.assertRaises((PolicyError,ValueError)):
                self.configure(**kwargs)
        self.transport.assert_not_called()

    def test_archive_failure_blocks_schedule(self):
        self.pilot()
        self.configure()
        with patch.object(self.archive,"ingest",side_effect=RuntimeError("storage unavailable")):
            with self.assertRaises(RuntimeError):
                self.tick(6)
        self.assertEqual(self.scheduler.list()[0]["state"],"blocked")
        self.assertIsNone(self.tick(12))
        self.assertEqual(self.transport.call_count,1)
