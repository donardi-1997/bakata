from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest

from intelligence.admin_export import fixture_snapshot
from intelligence.jobs import JobQueue
from intelligence.scheduler import run_once


class JobTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "jobs.sqlite")
        self.db = sqlite3.connect(self.path)
        self.addCleanup(self.db.close)
        self.queue = JobQueue(self.db)
        self.now = 1000

    def test_idempotent_enqueue_and_conflicting_schedule(self):
        self.assertTrue(self.queue.enqueue("demo",1000,1000))
        self.assertFalse(self.queue.enqueue("demo",1000,1001))
        with self.assertRaises(ValueError):
            self.queue.enqueue("demo",1001,1001)
        self.assertIsNone(self.queue.claim(999))
        claim = self.queue.claim(1000)
        self.queue.fail(claim,1001)
        self.assertFalse(self.queue.enqueue("demo",1000,1002))

    def test_persistence_and_atomic_result(self):
        self.queue.enqueue("demo",1000,1000)
        self.assertEqual(run_once(self.queue,lambda:1000),"demo")
        with closing(sqlite3.connect(self.path)) as db:
            other=JobQueue(db)
            self.assertEqual(other.list_jobs()[0]["status"],"succeeded")
            self.assertEqual(other.result("demo"),fixture_snapshot())
            self.assertEqual([e["event"] for e in other.events("demo")],["queued","claimed","succeeded"])
            self.assertIsNone(run_once(other,lambda:1001))

    def test_concurrent_claim_is_exclusive(self):
        self.queue.enqueue("a",1000,1000)
        self.queue.enqueue("b",1000,1000)
        barrier=Barrier(2)
        def claim():
            with closing(sqlite3.connect(self.path)) as db:
                queue=JobQueue(db)
                barrier.wait(timeout=10)
                return queue.claim(1000)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:claim(),range(2)))
        self.assertEqual(sum(c is not None for c in results),1)
        self.assertEqual(sum(j["status"]=="running" for j in self.queue.list_jobs()),1)

    def test_expired_lease_fences_old_worker(self):
        self.queue.enqueue("demo",1000,1000)
        first=self.queue.claim(1000)
        self.assertIsNone(self.queue.claim(1060))
        with self.assertRaises(ValueError):
            self.queue.succeed(first,fixture_snapshot(),1060)
        second=self.queue.claim(1090)
        self.assertEqual(second.attempt,2)
        self.assertNotEqual(first.token,second.token)
        with self.assertRaises(ValueError):
            self.queue.fail(first,1091)
        self.queue.succeed(second,fixture_snapshot(),1091)
        self.assertEqual(self.queue.list_jobs()[0]["status"],"succeeded")

    def test_retries_backoff_and_terminal_failure(self):
        self.queue.enqueue("demo",1000,1000)
        for due,attempt in [(1000,1),(1030,2),(1090,3)]:
            claim=self.queue.claim(due)
            self.assertEqual(claim.attempt,attempt)
            self.queue.fail(claim,due)
            self.assertIsNone(self.queue.claim(due))
        self.assertIsNone(self.queue.claim(9999))
        self.assertEqual(self.queue.list_jobs()[0]["status"],"failed")
        self.assertIsNone(self.queue.result("demo"))

    def test_schedule_coalesces_and_does_not_accumulate(self):
        self.queue.configure_schedule("daily",300,1000)
        self.assertEqual(self.queue.tick(1905),1)
        self.assertEqual(self.queue.list_jobs()[0]["id"],"schedule-daily_1900")
        self.assertEqual(self.queue.tick(1905),0)
        self.assertEqual(self.queue.tick(2200),0)
        self.assertEqual(run_once(self.queue,lambda:2200),"schedule-daily_1900")
        self.assertEqual(self.queue.tick(2500),1)
        self.queue.disable_schedule("daily")
        self.assertEqual(self.queue.tick(10000),0)

    def test_schedule_prefix_collision_does_not_block(self):
        self.queue.configure_schedule("a",300,1000)
        self.queue.configure_schedule("a_b",300,1000)
        self.assertEqual(self.queue.tick(1000),2)
        self.assertEqual(len(self.queue.list_jobs()),2)

    def test_invalid_limits_and_result(self):
        for invalid in ("../x","schedule-reserved",""):
            with self.assertRaises(ValueError):
                self.queue.enqueue(invalid,1000,1000)
        with self.assertRaises(ValueError):
            self.queue.configure_schedule("fast",299,1000)
        self.queue.enqueue("demo",1000,1000)
        claim=self.queue.claim(1000)
        with self.assertRaises(ValueError):
            self.queue.succeed(claim,{"mode":"live"},1000)
        with self.assertRaises(ValueError):
            self.queue.succeed(claim,dict(fixture_snapshot(),extra="x"*262145),1000)
        self.assertEqual(self.queue.list_jobs()[0]["status"],"running")
        self.assertIsNone(self.queue.result("demo"))
