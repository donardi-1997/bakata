import os
import sqlite3
import tempfile
import threading
import unittest

from intelligence.research_pair_ledger import Conflict, Ledger


AUTH = {"type": "authorize", "run": "fixture-test", "at": 100, "until": 400}
CLAIM = {"type": "claim-launch", "role": "proxy", "at": 101}


class PairLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "ledger.sqlite")
        self.ledger = Ledger.initialize(self.path, AUTH)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.ledger.close)

    def test_restart_and_stale_compare_and_swap(self):
        second = Ledger(self.path)
        try:
            revision, events = second.snapshot()
            self.assertEqual((revision, events), (1, [AUTH]))
            self.ledger.append(1, CLAIM)
            with self.assertRaises(Conflict):
                second.append(revision, CLAIM)
            self.assertEqual(second.snapshot(), (2, [AUTH, CLAIM]))
        finally:
            second.close()

    def test_competing_connections_only_one_wins(self):
        barrier = threading.Barrier(2)
        outcomes = []

        def attempt():
            db = Ledger(self.path)
            try:
                barrier.wait()
                try:
                    db.append(1, CLAIM)
                    outcomes.append("won")
                except Conflict:
                    outcomes.append("conflict")
            finally:
                db.close()

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertCountEqual(outcomes, ["won", "conflict"])
        self.assertEqual(self.ledger.snapshot(), (2, [AUTH, CLAIM]))

    def test_ambiguous_committed_response_never_permits_repeat(self):
        def lost_response():
            self.ledger.append(1, CLAIM)
            raise OSError("response lost after commit")

        with self.assertRaises(OSError):
            lost_response()
        reopened = Ledger(self.path)
        try:
            with self.assertRaises(Conflict):
                reopened.append(1, CLAIM)
            with self.assertRaises(ValueError):
                reopened.append(2, CLAIM)
            self.assertEqual(reopened.snapshot(), (2, [AUTH, CLAIM]))
        finally:
            reopened.close()

    def test_failed_transaction_and_immutable_history(self):
        with self.assertRaises(ValueError):
            self.ledger.append(1, {"type": "release", "role": "proxy", "at": 101})
        self.assertEqual(self.ledger.snapshot(), (1, [AUTH]))
        for sql in ("DELETE FROM pair_events", "UPDATE pair_events SET event='{}'",
                    "INSERT OR REPLACE INTO pair_events VALUES (1, '{}')"):
            with self.assertRaises(sqlite3.IntegrityError):
                self.ledger.db.execute(sql)
        self.assertEqual(self.ledger.snapshot(), (1, [AUTH]))

    def test_ambiguous_stop_claim_retained(self):
        self.ledger.append(1, CLAIM)
        self.ledger.append(2, {"type": "bind", "role": "proxy", "at": 102,
                               "identity": "proxy-task"})
        stop = {"type": "claim-stop", "role": "proxy", "at": 103}
        self.ledger.append(3, stop)
        with self.assertRaises(Conflict):
            self.ledger.append(3, stop)
        with self.assertRaises(ValueError):
            self.ledger.append(4, stop)
        self.assertEqual(self.ledger.snapshot()[0], 4)

    def test_explicit_create_and_missing_open_fail_closed(self):
        missing = os.path.join(self.temp.name, "missing.sqlite")
        with self.assertRaises(sqlite3.OperationalError):
            Ledger(missing)
        self.assertFalse(os.path.exists(missing))
        with self.assertRaises(FileExistsError):
            Ledger.initialize(self.path, AUTH)
        for path in (":memory:", "", "file::memory:?cache=shared"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                Ledger(path)
            with self.subTest(path=path), self.assertRaises(ValueError):
                Ledger.initialize(path, AUTH)

    def test_missing_schema_and_empty_database_fail_closed(self):
        path = os.path.join(self.temp.name, "empty.sqlite")
        sqlite3.connect(path).close()
        with self.assertRaises(ValueError):
            Ledger(path)
        self.ledger.db.execute("DROP TRIGGER pair_no_replace")
        with self.assertRaises(ValueError):
            self.ledger.snapshot()
        with self.assertRaises(ValueError):
            Ledger(self.path)

    def test_corrupt_oversized_and_excess_rows_rejected(self):
        # A client able to alter the schema can bypass these safeguards; this
        # tests detection, not protection against an adversary.
        self.ledger.db.execute("DROP TRIGGER pair_no_update")
        self.ledger.db.execute("UPDATE pair_events SET event = ?", ("x" * 4097,))
        from intelligence.research_pair_ledger import _SCHEMA
        self.ledger.db.execute(_SCHEMA["pair_no_update"])
        with self.assertRaises(ValueError):
            self.ledger.snapshot()
        self.ledger.db.execute("DROP TRIGGER pair_no_update")
        import json
        self.ledger.db.execute("UPDATE pair_events SET event = ?",
                               (json.dumps(AUTH, sort_keys=True, separators=(",", ":")),))
        self.ledger.db.execute(_SCHEMA["pair_no_update"])
        for revision in range(2, 34):
            self.ledger.db.execute("INSERT INTO pair_events VALUES (?, '{}')", (revision,))
        with self.assertRaises(ValueError):
            self.ledger.snapshot()

    def test_noncanonical_or_missing_revision_rejected(self):
        self.ledger.db.execute("INSERT INTO pair_events VALUES (3, '{}')")
        with self.assertRaises(ValueError):
            self.ledger.snapshot()


if __name__ == "__main__":
    unittest.main()
