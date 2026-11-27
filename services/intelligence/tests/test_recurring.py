import hashlib
import json
import sqlite3
import subprocess
import sys
import threading
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from intelligence.pilot import PilotLedger, execute, utcnow
from intelligence.recurring import RecurringCapture, MIN_INTERVAL, inspect_interrupted
from intelligence.storage import CommercialStore, APPLICATION_ID
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
        self.now=utcnow()

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
        with self.assertRaisesRegex(PolicyError,"already registered"):
            self.configure()
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

    def test_inspect_before_archive_does_not_infer_no_request_or_mutate(self):
        self.pilot()
        self.configure()
        self.transport.side_effect=KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.tick(6)
        before=(list(self.db.iterdump()),list(self.archive_db.iterdump()))
        self.transport.reset_mock()
        with patch("intelligence.recurring.https_get",side_effect=AssertionError("network")):
            result=inspect_interrupted(self.db,self.archive_db)
        self.assertEqual(result[0]["evidence"],"absent")
        self.assertEqual(result[0]["candidates"],[])
        self.assertEqual(result[0]["remaining"],1)
        self.assertEqual(before,(list(self.db.iterdump()),list(self.archive_db.iterdump())))
        self.transport.assert_not_called()
        self.assertEqual(self.scheduler.list()[0]["state"],"running")

    def test_inspect_after_archive_and_ambiguous_candidates(self):
        self.pilot()
        self.configure()
        with patch.object(self.scheduler,"_finish",side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.tick(6)
        before=(list(self.db.iterdump()),list(self.archive_db.iterdump()))
        result=inspect_interrupted(self.db,self.archive_db)
        self.assertEqual(result[0]["evidence"],"unique")
        self.assertEqual(len(result[0]["candidates"]),1)
        self.assertEqual(before,(list(self.db.iterdump()),list(self.archive_db.iterdump())))
        row=list(self.archive_db.execute("SELECT * FROM captures ORDER BY observed_at DESC LIMIT 1").fetchone())
        row[0]="a"*64
        row[3]=(self.now+timedelta(hours=7)).isoformat()
        self.archive_db.execute("INSERT INTO captures VALUES (?,?,?,?,?,?,?,?,?,?,?)",row)
        self.archive_db.commit()
        before=(list(self.db.iterdump()),list(self.archive_db.iterdump()))
        result=inspect_interrupted(self.db,self.archive_db)
        self.assertEqual(result[0]["evidence"],"ambiguous")
        self.assertEqual(len(result[0]["candidates"]),2)
        self.assertEqual(before,(list(self.db.iterdump()),list(self.archive_db.iterdump())))
        self.assertEqual(self.scheduler.list()[0]["state"],"running")

    def test_inspect_inconsistent_reservation(self):
        self.pilot()
        self.configure()
        self.transport.side_effect=KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.tick(6)
        self.db.execute("UPDATE int_recurring_events SET state='failed-review'")
        self.db.commit()
        self.assertEqual(inspect_interrupted(self.db,self.archive_db)[0]["evidence"],"inconsistent")

    def test_inspect_rejects_missing_archive_columns_even_without_running(self):
        self.pilot()
        self.configure()
        self.archive_db.execute("ALTER TABLE captures RENAME TO missing_captures")
        self.archive_db.commit()
        with self.assertRaisesRegex(ValueError,"Inspection failed"):
            inspect_interrupted(self.db,self.archive_db)
        process=subprocess.run([sys.executable,"-m","intelligence.recurring",
            "--ledger",str(self.ledger_path),"--archive",str(self.archive_path),"inspect"],
            capture_output=True,text=True)
        self.assertNotEqual(process.returncode,0)
        self.assertNotIn("Traceback",process.stderr)

    def test_inspect_reserved_event_before_finished_attempt_is_inconsistent(self):
        self.pilot()
        self.configure()
        self.transport.side_effect=KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.tick(6)
        self.db.execute("INSERT INTO int_recurring_events VALUES (?,?,?,'succeeded',?)",
                        (self.data["host"],2,(self.now+timedelta(hours=7)).isoformat(),"a"*64))
        self.db.commit()
        before=(list(self.db.iterdump()),list(self.archive_db.iterdump()))
        result=inspect_interrupted(self.db,self.archive_db)
        self.assertEqual(result[0]["evidence"],"inconsistent")
        self.assertEqual(result[0]["candidates"],[])
        self.assertEqual(before,(list(self.db.iterdump()),list(self.archive_db.iterdump())))

    def test_inspect_prior_failure_or_excess_budget_is_inconsistent(self):
        self.pilot()
        self.configure()
        self.transport.side_effect=KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.tick(6)
        host=self.data["host"]
        started=(self.now+timedelta(hours=6)).isoformat()
        earlier=(self.now+timedelta(hours=5)).isoformat()
        self.db.execute("UPDATE int_recurring_events SET attempt=2")
        self.db.execute("INSERT INTO int_recurring_events VALUES (?,1,?,'failed-review',NULL)",(host,earlier))
        self.db.execute("UPDATE int_recurring SET remaining=1")
        self.db.commit()
        self.assertEqual(inspect_interrupted(self.db,self.archive_db)[0]["evidence"],"inconsistent")
        self.db.execute("UPDATE int_recurring_events SET state='succeeded' WHERE attempt=1")
        self.db.execute("UPDATE int_recurring SET remaining=3")
        self.db.commit()
        self.assertEqual(inspect_interrupted(self.db,self.archive_db)[0]["evidence"],"inconsistent")
        self.db.execute("UPDATE int_recurring SET remaining=2,last_attempt=?",(started,))
        self.db.commit()
        self.assertEqual(inspect_interrupted(self.db,self.archive_db)[0]["evidence"],"absent")

    def test_inspect_concurrent_capture_and_cli_read_only(self):
        self.pilot()
        self.configure()
        entered=threading.Event()
        release=threading.Event()
        errors=[]
        def transport(*args,**kwargs):
            entered.set()
            if not release.wait(10):
                raise RuntimeError("test timeout")
            return self.response()
        def worker():
            try:
                with closing(sqlite3.connect(self.ledger_path)) as db, closing(sqlite3.connect(self.archive_path)) as archive:
                    scheduler=RecurringCapture(db,CommercialStore(archive))
                    with patch.object(scheduler,"_finish",side_effect=KeyboardInterrupt):
                        scheduler.tick(self.raw(),transport=transport)
            except KeyboardInterrupt:
                pass
            except BaseException as exc:
                errors.append(exc)
        with patch("intelligence.recurring.utcnow",return_value=self.now+timedelta(hours=6)):
            thread=threading.Thread(target=worker)
            thread.start()
            try:
                self.assertTrue(entered.wait(10))
                before=(list(self.db.iterdump()),list(self.archive_db.iterdump()))
                process=subprocess.run([sys.executable,"-m","intelligence.recurring",
                    "--ledger",str(self.ledger_path),"--archive",str(self.archive_path),"inspect"],
                    capture_output=True,text=True,check=True)
                self.assertEqual(json.loads(process.stdout)[0]["evidence"],"absent")
                self.assertEqual(before,(list(self.db.iterdump()),list(self.archive_db.iterdump())))
            finally:
                release.set()
                thread.join(10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors,[])
        self.assertEqual(inspect_interrupted(self.db,self.archive_db)[0]["evidence"],"unique")

    def test_inspection_tampered_data_never_discloses_canary(self):
        self.pilot()
        self.configure()
        with patch.object(self.scheduler,"_finish",side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.tick(6)
        canary="SECRET_CANARY_TOKEN"
        self.archive_db.execute("UPDATE captures SET url=? WHERE observed_at>?",(
            "https://catalog.example.com/?token="+canary,self.now.isoformat()))
        self.archive_db.commit()
        def cli():
            return subprocess.run([sys.executable,"-m","intelligence.recurring",
                "--ledger",str(self.ledger_path),"--archive",str(self.archive_path),"inspect"],
                capture_output=True,text=True)
        before=(list(self.db.iterdump()),list(self.archive_db.iterdump()))
        with patch("intelligence.recurring.https_get",side_effect=AssertionError("network")):
            self.assertNotIn(canary,repr(inspect_interrupted(self.db,self.archive_db)))
            process=cli()
        self.assertEqual(process.returncode,0)
        self.assertNotIn(canary,process.stdout+process.stderr)
        self.assertEqual(before,(list(self.db.iterdump()),list(self.archive_db.iterdump())))
        self.db.execute("UPDATE int_recurring_events SET started=?",(canary,))
        self.db.execute("UPDATE int_recurring SET last_attempt=?",(canary,))
        self.db.commit()
        process=cli()
        self.assertNotEqual(process.returncode,0)
        self.assertNotIn(canary,process.stdout+process.stderr)
        self.assertNotIn("Traceback",process.stderr)
        with self.assertRaisesRegex(ValueError,"Inspection failed") as error:
            inspect_interrupted(self.db,self.archive_db)
        self.assertNotIn(canary,str(error.exception))
        self.db.execute("UPDATE int_recurring_events SET started=(SELECT last_attempt FROM int_recurring)")
        self.db.execute("UPDATE int_recurring SET last_attempt=?",
                        ((self.now+timedelta(hours=6)).isoformat(),))
        self.db.execute("UPDATE int_recurring_events SET started=(SELECT last_attempt FROM int_recurring)")
        self.db.commit()
        self.archive_db.execute("UPDATE captures SET observed_at=? WHERE observed_at>?",(canary,self.now.isoformat()))
        self.archive_db.commit()
        process=cli()
        self.assertNotEqual(process.returncode,0)
        self.assertNotIn(canary,process.stdout+process.stderr)

    def test_inspection_rejects_wrong_and_corrupt_databases(self):
        self.pilot()
        self.configure()
        self.archive_db.execute("PRAGMA application_id=123")
        with self.assertRaisesRegex(ValueError,"Inspection failed"):
            inspect_interrupted(self.db,self.archive_db)
        self.archive_db.execute(f"PRAGMA application_id={APPLICATION_ID}")
        self.archive_db.execute("PRAGMA user_version=99")
        with self.assertRaisesRegex(ValueError,"Inspection failed"):
            inspect_interrupted(self.db,self.archive_db)
        self.archive_db.execute("PRAGMA user_version=2")
        self.db.execute("PRAGMA user_version=1")
        with self.assertRaisesRegex(ValueError,"Inspection failed"):
            inspect_interrupted(self.db,self.archive_db)
        bad=Path(self.temp.name)/"SECRET_CANARY_CORRUPT.sqlite"
        bad.write_bytes(b"SECRET_CANARY_NOT_A_SQLITE_DATABASE")
        process=subprocess.run([sys.executable,"-m","intelligence.recurring","--ledger",str(self.ledger_path),
            "--archive",str(bad),"inspect"],capture_output=True,text=True)
        self.assertNotEqual(process.returncode,0)
        self.assertNotIn("SECRET_CANARY",process.stdout+process.stderr)
        self.assertNotIn("Traceback",process.stderr)

    def test_inspection_truncation_cannot_report_unique(self):
        self.pilot()
        self.configure()
        with patch.object(self.scheduler,"_finish",side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.tick(6)
        row=list(self.archive_db.execute("SELECT * FROM captures ORDER BY observed_at DESC LIMIT 1").fetchone())
        for i in range(101):
            row[0]=f"{i:064x}"
            row[3]=(self.now+timedelta(hours=7,microseconds=i)).isoformat()
            self.archive_db.execute("INSERT INTO captures VALUES (?,?,?,?,?,?,?,?,?,?,?)",row)
        self.archive_db.commit()
        result=inspect_interrupted(self.db,self.archive_db)
        self.assertEqual(result[0]["evidence"],"truncated")
        self.assertLessEqual(len(result[0]["candidates"]),100)
