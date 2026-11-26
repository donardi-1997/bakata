import sqlite3
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from intelligence.adapters import FixtureAdapter
from intelligence.repository import ObservationStore


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.store = ObservationStore(self.db)
        self.batch = FixtureAdapter().collect()

    def test_replay_and_unknown_price(self):
        self.assertEqual(self.store.ingest(self.batch), 2)
        self.assertEqual(self.store.ingest(self.batch), 0)
        self.assertEqual(self.store.count(), 2)
        self.assertIsNone(self.db.execute("SELECT price_minor FROM observations WHERE external_id='demo-002'").fetchone()[0])

    def test_price_history_and_utc(self):
        first = self.batch[0]
        self.store.ingest((first,))
        same = replace(first, observed_at=first.observed_at.astimezone(timezone(timedelta(hours=-5))))
        self.assertEqual(self.store.ingest((same,)), 0)
        later = replace(first, observed_at=first.observed_at + timedelta(days=1), price_minor=0)
        self.assertEqual(self.store.ingest((later,)), 1)

    def test_conflict_rolls_back_batch(self):
        self.store.ingest((self.batch[0],))
        with self.assertRaises(ValueError):
            self.store.ingest((self.batch[1], replace(self.batch[0], price_minor=1)))
        self.assertEqual(self.store.count(), 1)

    def test_invalid_values(self):
        for fields in ({"price_minor": -1}, {"price_minor": True}, {"price_minor": 1.5},
                       {"currency": "cop"}, {"observed_at": datetime(2026, 1, 1)},
                       {"url": "http://catalog.invalid/x"}, {"url": "https://user:pass@catalog.invalid/x"},
                       {"title": ""}, {"source": "../x"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                replace(self.batch[0], **fields)

    def test_bounded_batch(self):
        with self.assertRaises(ValueError):
            self.store.ingest(self.batch * 501)
        self.assertEqual(self.store.count(), 0)
