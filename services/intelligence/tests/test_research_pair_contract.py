import unittest

from intelligence.research_pair_contract import replay


class PairContractTests(unittest.TestCase):
    def setUp(self):
        self.events = [{"type": "authorize", "run": "fixture-test", "at": 100, "until": 400,
                        "nonce": "0" * 32}]

    def add(self, kind, role, at=101, **fields):
        self.events.append(dict(type=kind, role=role, at=at, **fields))

    def bind(self, role):
        self.add("claim-launch", role)
        self.add("bind", role, identity=role + "-task")

    def stopped(self, role, **changes):
        fields = dict(identity=role + "-task", last="STOPPED", desired="STOPPED")
        fields.update(changes)
        self.add("observe-stopped", role, **fields)

    def test_two_independent_confirmations_never_release_slot(self):
        self.bind("proxy")
        self.bind("worker")
        self.add("claim-stop", "worker")
        self.stopped("worker")
        self.assertFalse(replay(self.events).both_stopped)
        self.add("claim-stop", "proxy")
        self.stopped("proxy")
        self.assertTrue(replay(self.events).both_stopped)
        self.add("release", "proxy")
        with self.assertRaises(ValueError):
            replay(self.events)

    def test_ambiguous_launch_and_stop_cannot_be_retried(self):
        self.add("claim-launch", "proxy")
        self.add("claim-launch", "proxy")
        with self.assertRaises(ValueError):
            replay(self.events)
        self.events.pop()
        self.add("bind", "proxy", identity="proxy-task")
        self.add("claim-stop", "proxy")
        self.add("claim-stop", "proxy")
        with self.assertRaises(ValueError):
            replay(self.events)
        self.events.pop()
        self.stopped("proxy")
        self.assertTrue(replay(self.events).proxy.stopped)

    def test_worker_requires_bound_live_proxy_and_deadline(self):
        self.add("claim-launch", "worker")
        with self.assertRaises(ValueError):
            replay(self.events)
        self.events.pop()
        self.bind("proxy")
        self.add("claim-stop", "proxy")
        self.add("claim-launch", "worker")
        with self.assertRaises(ValueError):
            replay(self.events)
        self.events.pop()
        self.events.pop()
        self.add("claim-launch", "worker", at=400)
        with self.assertRaises(ValueError):
            replay(self.events)

    def test_wrong_identity_status_duplicate_or_extra_data_rejected(self):
        self.bind("proxy")
        for changes in ({"identity": "other"}, {"last": "RUNNING"}, {"desired": "RUNNING"},
                        {"extra": "x"}):
            self.stopped("proxy", **changes)
            with self.assertRaises(ValueError):
                replay(self.events)
            self.events.pop()
        self.stopped("proxy")
        self.stopped("proxy")
        with self.assertRaises(ValueError):
            replay(self.events)

    def test_same_identity_and_malformed_history_rejected(self):
        self.bind("proxy")
        self.add("claim-launch", "worker")
        self.add("bind", "worker", identity="proxy-task")
        with self.assertRaises(ValueError):
            replay(self.events)
        for events in ([], [dict(self.events[0], at=True)],
                       [self.events[0], {"type": "claim-launch", "role": "proxy", "at": 99}],
                       [self.events[0], {"type": "authorize", "run": "fixture-x", "at": 101, "until": 400}]):
            with self.assertRaises(ValueError):
                replay(events)

    def test_types_and_history_bound_rejected_uniformly(self):
        for event in (
            {"type": [], "role": "proxy", "at": 101},
            {"type": {}, "role": "proxy", "at": 101},
            {"type": "claim-launch", "role": [], "at": 101},
            {"type": "bind", "role": "proxy", "at": 101, "identity": []},
            {"type": "claim-launch", "role": "proxy", "at": []},
        ):
            with self.subTest(event=event), self.assertRaises(ValueError):
                replay(self.events + [event])
        with self.assertRaises(ValueError):
            replay(self.events * 33)

    def test_claim_does_not_prevent_proxy_stop_or_deadline_race(self):
        self.bind("proxy")
        self.add("claim-launch", "worker", at=399)
        prefix = list(self.events)
        self.stopped("proxy", at=400)
        self.add("bind", "worker", at=401, identity="worker-task")
        state = replay(self.events)
        self.assertTrue(state.proxy.stopped)
        self.assertEqual(state.worker.identity, "worker-task")
        # Replay of a common prefix gives no concurrency or execution authority.
        self.assertEqual(replay(prefix), replay(list(prefix)))


if __name__ == "__main__":
    unittest.main()
