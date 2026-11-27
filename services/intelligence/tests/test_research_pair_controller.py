"""Offline pair controller tests: fake ECS, real SQLite ledger, no network or AWS."""
from pathlib import Path
import tempfile
import unittest

from intelligence.research_pair_controller import BIND_GRACE, PairConfig, PairController
from intelligence.research_pair_ledger import Conflict, Ledger

ACCOUNT = "123456789012"
BASE = f"arn:aws:ecs:us-east-1:{ACCOUNT}:"
NOW = 1_800_000_000
UNTIL = NOW + 600


def auth(nonce="0" * 32):
    return {"type": "authorize", "run": "fixture-ci", "at": NOW, "until": UNTIL, "nonce": nonce}


def config(**changes):
    values = dict(
        cluster=BASE + "cluster/bakata-research-ci",
        proxy_definition=BASE + "task-definition/bakata-research-ci-proxy-fixture:1",
        worker_definition=BASE + "task-definition/bakata-research-ci-persistent-fixture:1",
        proxy_subnet="subnet-" + "a" * 17, proxy_security_group="sg-" + "a" * 17,
        worker_subnet="subnet-" + "b" * 17, worker_security_group="sg-" + "b" * 17)
    values.update(changes)
    return PairConfig(**values)


class FakeECS:
    """Stateful fake modelling clientToken idempotency, the default RUNNING
    filter of ListTasks and tasks that disappear from DescribeTasks."""

    def __init__(self):
        self.tasks, self.calls, self.tokens = {}, [], {}
        self.run_error = self.stop_error = self.stop_only = None
        self.describe_override = {}

    def run_task(self, **kw):
        self.calls.append(("run", kw["taskDefinition"]))
        arn = self.tokens.get(kw["clientToken"])
        if arn is None:
            arn = BASE + "task/bakata-research-ci/" + format(len(self.tokens) + 1, "032x")
            self.tokens[kw["clientToken"]] = arn
            self.tasks[arn] = {
                "taskArn": arn, "clusterArn": kw["cluster"], "taskDefinitionArn": kw["taskDefinition"],
                "launchType": kw["launchType"], "platformVersion": kw["platformVersion"],
                "enableExecuteCommand": kw["enableExecuteCommand"], "group": kw["group"],
                "startedBy": kw["startedBy"], "tags": kw["tags"],
                "overrides": {"containerOverrides": kw["overrides"]["containerOverrides"]},
                "attachments": [{"type": "ElasticNetworkInterface", "details": [
                    {"name": "subnetId", "value": kw["networkConfiguration"]["awsvpcConfiguration"]["subnets"][0]},
                    {"name": "networkInterfaceId", "value": "eni-0123456789abcdef0"}]}],
                "lastStatus": "RUNNING", "desiredStatus": "RUNNING", "_kw": kw}
        if self.run_error:
            raise self.run_error
        return {"tasks": [{"taskArn": arn}], "failures": []}

    def describe_tasks(self, cluster, tasks, include):
        self.calls.append(("describe", tasks[0]))
        if tasks[0] in self.describe_override:
            return self.describe_override[tasks[0]]
        task = self.tasks.get(tasks[0])
        if task is None:
            return {"tasks": [], "failures": [{"arn": tasks[0], "reason": "MISSING"}]}
        return {"tasks": [{k: v for k, v in task.items() if k != "_kw"}], "failures": []}

    def list_tasks(self, cluster, startedBy, maxResults):
        self.calls.append(("list", startedBy))
        return {"taskArns": [a for a, t in self.tasks.items()
                             if t["startedBy"] == startedBy and t["desiredStatus"] == "RUNNING"]}

    def stop_task(self, cluster, task, reason):
        self.calls.append(("stop", task))
        if self.stop_error and (self.stop_only is None or task == self.stop_only):
            raise self.stop_error
        self.tasks[task]["desiredStatus"] = "STOPPED"
        return {"task": {"taskArn": task, "desiredStatus": "STOPPED"}}

    def count(self, kind):
        return sum(1 for c in self.calls if c[0] == kind)

    def stopped(self):
        return [c[1] for c in self.calls if c[0] == "stop"]


class PairControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "pair.sqlite"
        self.ledger = Ledger.initialize(self.path, auth())
        self.ecs = FakeECS()
        self.now = NOW
        self.ctl = self.controller()

    def controller(self, ledger=None, ecs=None, enabled=True):
        return PairController(ledger or self.ledger, ecs or self.ecs, config(),
                              clock=lambda: self.now, enabled=enabled)

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()

    def events(self):
        return [e["type"] + ":" + e.get("role", "") for e in self.ledger.snapshot()[1]]

    def set_status(self, arn, last, desired=None):
        self.ecs.tasks[arn]["lastStatus"] = last
        self.ecs.tasks[arn]["desiredStatus"] = desired or last

    def launch_pair(self):
        return self.ctl.launch("proxy"), self.ctl.launch("worker")

    def test_full_pair_lifecycle_and_slot_never_released(self):
        proxy, worker = self.launch_pair()
        self.assertNotEqual(proxy, worker)
        kw = self.ecs.tasks[worker]["_kw"]
        self.assertEqual(kw["networkConfiguration"]["awsvpcConfiguration"]["securityGroups"], ["sg-" + "b" * 17])
        self.assertEqual(kw["networkConfiguration"]["awsvpcConfiguration"]["assignPublicIp"], "DISABLED")
        self.assertEqual([o["name"] for o in kw["overrides"]["containerOverrides"]], ["worker", "coordinator"])
        self.assertEqual(self.ctl.supervise()["state"], "running")
        self.assertEqual(self.ecs.count("stop"), 0)
        self.now = UNTIL
        result = self.ctl.supervise()
        self.assertEqual((result["state"], result["reason"], sorted(result["requested"])),
                         ("stop-requested", "deadline", ["proxy", "worker"]))
        self.assertEqual(self.ctl.supervise()["state"], "stopping")  # draining, no repeat
        self.assertEqual(self.ecs.count("stop"), 2)
        for arn in (proxy, worker):
            self.set_status(arn, "STOPPED")
        self.assertEqual(self.ctl.supervise(), {"state": "both-stopped"})
        self.assertEqual(self.ctl.supervise(), {"state": "both-stopped"})
        self.assertEqual(self.events().count("observe-stopped:proxy"), 1)
        with self.assertRaises(ValueError):
            self.ctl.launch("proxy")
        with self.assertRaises(FileExistsError):
            Ledger.initialize(self.path, auth())
        self.assertEqual(self.ecs.count("run"), 2)

    def test_worker_requires_bound_proxy_with_lastStatus_running(self):
        with self.assertRaises(ValueError):
            self.ctl.launch("worker")
        proxy = self.ctl.launch("proxy")
        for last, desired in (("PENDING", "RUNNING"), ("RUNNING", "STOPPED")):
            self.set_status(proxy, last, desired)
            with self.subTest(last=last, desired=desired), self.assertRaises(ValueError):
                self.ctl.launch("worker")
        self.assertEqual(self.ecs.count("run"), 1)
        self.assertNotIn("claim-launch:worker", self.events())

    def test_no_launch_near_deadline_even_after_claim(self):
        self.now = UNTIL - 30
        with self.assertRaises(ValueError):
            self.ctl.launch("proxy")
        self.assertEqual(self.events(), ["authorize:"])
        ticks = iter([NOW, UNTIL - 10])  # clock passes the margin after the claim
        ctl = PairController(self.ledger, self.ecs, config(), clock=lambda: next(ticks), enabled=True)
        with self.assertRaises(ValueError):
            ctl.launch("proxy")
        self.assertEqual(self.ecs.count("run"), 0)
        self.assertIn("claim-launch:proxy", self.events())
        self.now = NOW
        with self.assertRaises(ValueError):  # claim is burned; never retried
            self.ctl.launch("proxy")

    def test_ambiguous_launch_is_reconciled_not_retried(self):
        self.ecs.run_error = TimeoutError("lost response")
        with self.assertRaises(ValueError):
            self.ctl.launch("proxy")
        with self.assertRaises(ValueError):
            self.ctl.launch("proxy")
        self.assertEqual(self.ecs.count("run"), 1)
        self.now = UNTIL
        self.assertEqual(self.ctl.supervise()["requested"], ["proxy"])
        self.assertEqual(self.ecs.count("list"), 1)
        self.assertEqual(self.ecs.count("run"), 1)

    def test_unbound_claim_within_grace_is_left_alone(self):
        self.ecs.run_error = TimeoutError()
        with self.assertRaises(ValueError):
            self.ctl.launch("proxy")
        self.assertEqual(self.ctl.supervise()["state"], "running")
        self.assertEqual(self.ecs.count("list"), 0)

    def test_missing_launch_still_stops_verified_peer(self):
        # Audit R1: an unreconcilable worker must not keep the proxy alive.
        proxy = self.ctl.launch("proxy")
        self.ecs.run_error = TimeoutError()
        with self.assertRaises(ValueError):
            self.ctl.launch("worker")
        self.ecs.run_error = None
        worker = [a for a in self.ecs.tasks if a != proxy][0]
        del self.ecs.tasks[worker]  # launch truly unknown: absence is not proof
        self.now = NOW + BIND_GRACE
        with self.assertRaisesRegex(ValueError, "worker"):
            self.ctl.supervise()
        self.assertEqual(self.ecs.stopped(), [proxy])
        self.assertNotIn("bind:worker", self.events())

    def test_stopped_ambiguous_launch_is_not_found_and_needs_human(self):
        self.ecs.run_error = TimeoutError()
        with self.assertRaises(ValueError):
            self.ctl.launch("proxy")
        only = list(self.ecs.tasks)[0]
        self.set_status(only, "STOPPED")  # default ListTasks filter hides it
        self.now = UNTIL
        with self.assertRaisesRegex(ValueError, "manual reconciliation"):
            self.ctl.supervise()
        self.assertEqual(self.ecs.count("stop"), 0)

    def test_uncertain_stop_never_repeated_and_peer_still_stopped(self):
        # Audit R2: a proxy StopTask timeout must not block stopping the worker.
        proxy, worker = self.launch_pair()
        self.now = UNTIL
        self.ecs.stop_error, self.ecs.stop_only = TimeoutError("lost response"), proxy
        with self.assertRaisesRegex(ValueError, "proxy"):
            self.ctl.supervise()
        self.ecs.stop_error = None
        with self.assertRaisesRegex(ValueError, "Uncertain proxy stop; manual reconciliation"):
            self.ctl.supervise()
        self.assertEqual(self.ecs.stopped(), [proxy, worker])  # proxy never repeated
        self.assertEqual(self.ecs.tasks[worker]["desiredStatus"], "STOPPED")
        self.assertIn("claim-stop:worker", self.events())

    def test_persisted_stop_claim_without_effect_ends_pair(self):
        # Audit N4: crash between claim-stop and StopTask, before the deadline.
        proxy, worker = self.launch_pair()
        revision, _ = self.ledger.snapshot()
        self.ledger.append(revision, {"type": "claim-stop", "role": "proxy", "at": NOW})
        self.now = NOW + 10
        with self.assertRaisesRegex(ValueError, "Uncertain proxy stop"):
            self.ctl.supervise()
        self.assertEqual(self.ecs.stopped(), [worker])
        self.assertEqual(self.ecs.tasks[proxy]["desiredStatus"], "RUNNING")  # needs a human

    def test_stop_uses_fresh_clock_after_concurrent_event(self):
        # Audit N3: another controller wrote a later timestamp during this tick.
        proxy, worker = self.launch_pair()
        self.set_status(proxy, "STOPPED")
        revision, _ = self.ledger.snapshot()
        self.ledger.append(revision, {"type": "observe-stopped", "role": "proxy", "at": NOW + 50,
                                      "identity": proxy, "last": "STOPPED", "desired": "STOPPED"})
        ticks = iter([NOW + 40] + [NOW + 60] * 10)
        ctl = PairController(self.ledger, self.ecs, config(), clock=lambda: next(ticks), enabled=True)
        self.assertEqual(ctl.supervise()["requested"], ["worker"])
        self.assertEqual(self.ecs.stopped(), [worker])

    def test_future_stamped_claim_does_not_defer_reconciliation(self):
        # Audit N5: clock skew between hosts.
        revision, _ = self.ledger.snapshot()
        self.ledger.append(revision, {"type": "claim-launch", "role": "proxy", "at": NOW + 500})
        self.now = NOW + 10
        with self.assertRaisesRegex(ValueError, "proxy"):
            self.ctl.supervise()
        self.assertEqual(self.ecs.count("list"), 1)

    def test_transient_api_error_terminates_pair_by_design(self):
        # Audit N1: documented fail-safe choice, not tolerance of flaky APIs.
        proxy, worker = self.launch_pair()

        def flaky(cluster, tasks, include, original=self.ecs.describe_tasks):
            if tasks[0] == worker:
                raise ConnectionError("throttled")
            return original(cluster=cluster, tasks=tasks, include=include)
        self.ecs.describe_tasks = flaky
        with self.assertRaisesRegex(ValueError, "worker.*ConnectionError|ConnectionError"):
            self.ctl.supervise()
        self.assertEqual(self.ecs.stopped(), [proxy])

    def test_missing_task_still_stops_peer(self):
        # Audit R3: DescribeTasks MISSING for one role.
        proxy, worker = self.launch_pair()
        del self.ecs.tasks[proxy]
        with self.assertRaisesRegex(ValueError, "proxy"):
            self.ctl.supervise()
        self.assertEqual(self.ecs.stopped(), [worker])

    def test_peer_down_either_role_stops_survivor(self):
        for down, last, desired in (("proxy", "STOPPED", "STOPPED"), ("worker", "STOPPED", "STOPPED"),
                                    ("worker", "STOPPING", "STOPPED")):
            with self.subTest(down=down, last=last):
                self.tearDown()  # release the previous ledger before a fresh fixture
                self.setUp()
                try:
                    arns = dict(zip(("proxy", "worker"), self.launch_pair()))
                    self.set_status(arns[down], last, desired)
                    result = self.ctl.supervise()
                    survivor = "worker" if down == "proxy" else "proxy"
                    self.assertEqual((result["reason"], result["requested"]), ("peer-down", [survivor]))
                    self.assertEqual(self.ecs.stopped(), [arns[survivor]])
                finally:
                    self.tearDown()

    def test_bind_retries_after_conflict(self):
        # Audit M1: another writer appends between RunTask and the bind.
        path = self.path

        class RacingLedger(Ledger):
            raced = False

            def append(self, expected_revision, event):
                if event["type"] == "bind" and not RacingLedger.raced:
                    RacingLedger.raced = True
                    other = Ledger(path)
                    try:  # a concurrent reconciler binds the same task first
                        revision, _ = other.snapshot()
                        other.append(revision, dict(event))
                    finally:
                        other.close()
                    with self_test.assertRaises(Conflict):
                        super().append(expected_revision, event)
                return super().append(expected_revision, event)
        self_test = self
        racing = RacingLedger(self.path)
        try:
            proxy = self.controller(ledger=racing).launch("proxy")
        finally:
            racing.close()
        self.assertTrue(RacingLedger.raced)
        self.assertEqual(self.events(), ["authorize:", "claim-launch:proxy", "bind:proxy"])
        self.assertEqual(self.ledger.snapshot()[1][-1]["identity"], proxy)
        self.assertEqual(self.ecs.count("run"), 1)

    def test_worker_abandoned_if_proxy_stop_claimed_after_worker_claim(self):
        proxy = self.ctl.launch("proxy")
        path = self.path

        class RacingLedger(Ledger):
            def append(self, expected_revision, event):
                revision = super().append(expected_revision, event)
                if event == {"type": "claim-launch", "role": "worker", "at": NOW}:
                    other = Ledger(path)
                    try:
                        other.append(revision, {"type": "claim-stop", "role": "proxy", "at": NOW})
                    finally:
                        other.close()
                return revision
        racing = RacingLedger(self.path)
        try:
            with self.assertRaisesRegex(ValueError, "Proxy stopping after claim"):
                self.controller(ledger=racing).launch("worker")
        finally:
            racing.close()
        self.assertEqual(self.ecs.count("run"), 1)
        self.assertTrue(proxy)

    def test_conflict_before_claim_prevents_effect(self):
        class RacingLedger(Ledger):
            def append(self, expected_revision, event):
                raise Conflict("Stale ledger revision")
        racing = RacingLedger(self.path)
        try:
            with self.assertRaises(Conflict):
                self.controller(ledger=racing).launch("proxy")
        finally:
            racing.close()
        self.assertEqual(self.ecs.count("run"), 0)

    def test_nonce_separates_ledgers_with_same_run(self):
        proxy = self.ctl.launch("proxy")
        other_path = Path(self.tmp.name) / "other.sqlite"
        other = Ledger.initialize(other_path, auth("1" * 32))
        try:
            ctl = self.controller(ledger=other)
            second = ctl.launch("proxy")
            self.assertNotEqual(proxy, second)  # distinct clientToken: no idempotent reuse
            with self.assertRaises(ValueError):
                ctl._describe(ctl._state()[1], "proxy", proxy)
        finally:
            other.close()

    def test_identity_mismatch_never_stops(self):
        proxy = self.ctl.launch("proxy")
        self.now = UNTIL
        for change in ({"taskDefinitionArn": config().worker_definition},
                       {"tags": [{"key": "bakata:purpose", "value": "research-fixture"}]},
                       {"startedBy": "0" * 32}, {"lastStatus": "BOGUS"},
                       {"enableExecuteCommand": True}, {"platformVersion": "LATEST"},
                       {"group": "service:other"}):
            original = dict(self.ecs.tasks[proxy])
            self.ecs.tasks[proxy].update(change)
            with self.subTest(change), self.assertRaises(ValueError):
                self.ctl.supervise()
            self.ecs.tasks[proxy] = original
        self.assertEqual(self.ecs.count("stop"), 0)

    def test_unsafe_configuration_of_our_task_is_stopped(self):
        # IAM cannot limit RunTask overrides or networking (audit): the controller
        # detects them, stops the offending task itself and its peer, then raises.
        env = [{"name": "BAKATA_RESEARCH_RUN", "value": "fixture-ci"},
               {"name": "BAKATA_RESEARCH_UNTIL", "value": str(UNTIL)}]
        foreign = [{"type": "ElasticNetworkInterface",
                    "details": [{"name": "subnetId", "value": "subnet-" + "c" * 17}]}]
        cases = [
            ({"overrides": {"containerOverrides": [{"name": "worker", "environment": env},
                                                   {"name": "coordinator", "environment": env}],
                            "taskRoleArn": BASE.replace(":ecs:us-east-1:", ":iam::") + "role/x"}}, "role override"),
            ({"overrides": {"containerOverrides": [{"name": "worker", "environment": env,
                                                    "command": ["sh", "-c", "curl evil"]},
                                                   {"name": "coordinator", "environment": env}]}}, "overrides differ"),
            ({"overrides": {"containerOverrides": [{"name": "worker", "environment": env + [{"name": "X", "value": "1"}]},
                                                   {"name": "coordinator", "environment": env}]}}, "overrides differ"),
            ({"attachments": foreign}, "subnet"),
            ({"attachments": []}, "no network attachment"),
        ]
        for change, reason in cases:
            with self.subTest(change):
                self.tearDown()  # release the previous ledger before a fresh fixture
                self.setUp()
                try:
                    proxy, worker = self.launch_pair()
                    self.ecs.tasks[worker].update(change)
                    with self.assertRaisesRegex(ValueError, "Unsafe worker task: " + reason):
                        self.ctl.supervise()
                    self.assertEqual(sorted(self.ecs.stopped()), sorted([proxy, worker]))
                finally:
                    self.tearDown()

    def test_unsafe_but_already_stopped_task_is_recorded_not_stopped(self):
        proxy, worker = self.launch_pair()
        self.ecs.tasks[worker]["attachments"] = [{"type": "ElasticNetworkInterface",
                                                  "details": [{"name": "subnetId", "value": "subnet-" + "c" * 17}]}]
        self.set_status(worker, "STOPPED")
        with self.assertRaisesRegex(ValueError, "Unsafe worker task"):
            self.ctl.supervise()
        self.assertIn("observe-stopped:worker", self.events())
        self.assertEqual(self.ecs.stopped(), [proxy])

    def test_starting_task_without_eni_is_accepted(self):
        proxy = self.ctl.launch("proxy")
        self.ecs.tasks[proxy]["attachments"] = []
        self.set_status(proxy, "PENDING", "RUNNING")
        self.assertEqual(self.ctl.supervise()["state"], "running")
        self.assertEqual(self.ecs.count("stop"), 0)

    def test_hostile_ecs_responses_fail_closed_as_value_error(self):
        proxy = self.ctl.launch("proxy")
        self.now = UNTIL
        for reply in (None, [], {"tasks": "x"}, {"tasks": [None]},
                      {"tasks": [{"tags": [1]}]}, {"tasks": [{"tags": [{"key": 1, "value": "v"}]}]}):
            self.ecs.describe_override[proxy] = reply
            with self.subTest(reply), self.assertRaisesRegex(ValueError, "proxy"):
                self.ctl.supervise()
        self.assertEqual(self.ecs.count("stop"), 0)
        self.ecs.describe_override.clear()
        self.ecs.stop_task = lambda **kw: "not a dict"
        with self.assertRaisesRegex(ValueError, "Malformed"):
            self.ctl.supervise()

    def test_configuration_and_enablement(self):
        for changes in ({"worker_security_group": "sg-" + "a" * 17},
                        {"proxy_definition": BASE + "task-definition/bakata-research-ci-persistent-fixture:1"},
                        {"worker_definition": BASE + "task-definition/other:1"},
                        {"cluster": "arn:aws:ecs:us-west-2:" + ACCOUNT + ":cluster/bakata-research-ci"},
                        {"proxy_subnet": "subnet-public"}):
            with self.subTest(changes), self.assertRaises(ValueError):
                config(**changes)
        disabled = self.controller(enabled=False)
        for action in (lambda: disabled.launch("proxy"), disabled.supervise,
                       lambda: disabled.reconcile("proxy")):
            with self.assertRaisesRegex(ValueError, "disabled"):
                action()
        with self.assertRaises(ValueError):
            PairController(object(), self.ecs, config(), clock=lambda: NOW, enabled=True)
        self.assertEqual(self.ecs.calls, [])


if __name__ == "__main__":
    unittest.main()
