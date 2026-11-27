"""Offline contract examples, not an AWS implementation or security proof."""
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FixtureRun:
    """Small fail-closed specification model; identifiers are synthetic."""

    def __init__(self, run):
        self.run = run
        self.state = "new"
        self.secrets = {f"{run}/proxy": "proxy", f"{run}/worker": "worker"}

    def may_read(self, principal, secret):
        return self.state in ("new", "running") and self.secrets.get(secret) == principal

    def start(self, *, proxy_ready, worker_ready, matching_pin, unexpired):
        if self.state != "new":
            raise ValueError("run cannot restart")
        if all((proxy_ready, worker_ready, matching_pin, unexpired)):
            self.state = "running"
        else:
            self.state = "cleanup_required"

    def finish(self, *, stopped, inaccessible, deleted):
        if self.state not in ("running", "cleanup_required"):
            raise ValueError("invalid cleanup")
        self.state = "closed" if all((stopped, inaccessible, deleted)) else "cleanup_required"


class ContractTests(unittest.TestCase):
    def test_template_has_no_delivery_or_launch(self):
        template = json.loads((ROOT / "infra/research-aws/proxy-task.json").read_text(encoding="utf-8-sig"))
        resources = template["Resources"]
        self.assertEqual({r["Type"] for r in resources.values()}, {
            "AWS::ECR::Repository", "AWS::Logs::LogGroup",
            "AWS::IAM::Role", "AWS::ECS::TaskDefinition",
        })
        task = resources["ProxyTask"]["Properties"]
        container, = task["ContainerDefinitions"]
        self.assertNotIn("TaskRoleArn", task)
        self.assertNotIn("Volumes", task)
        self.assertNotIn("Secrets", container)
        self.assertNotIn("MountPoints", container)
        self.assertEqual(container["Environment"], [{"Name": "BAKATA_RESEARCH_PROXY_FIXTURE", "Value": "1"}])
        self.assertEqual(template["Parameters"]["EnableProxyTask"]["Default"], "false")

    def test_separation_and_run_isolation(self):
        a, b = FixtureRun("a"), FixtureRun("b")
        self.assertTrue(a.may_read("proxy", "a/proxy"))
        for principal, secret in (("worker", "a/proxy"), ("proxy", "a/worker"),
                                  ("proxy", "b/proxy"), ("controller", "a/proxy")):
            self.assertFalse(a.may_read(principal, secret))
        self.assertTrue(b.may_read("proxy", "b/proxy"))

    def test_partial_mismatch_and_expired_fail_closed(self):
        for index in range(4):
            checks = [True] * 4
            checks[index] = False
            run = FixtureRun("a")
            run.start(proxy_ready=checks[0], worker_ready=checks[1],
                      matching_pin=checks[2], unexpired=checks[3])
            self.assertEqual(run.state, "cleanup_required")
            self.assertFalse(run.may_read("proxy", "a/proxy"))
            with self.assertRaises(ValueError):
                run.start(proxy_ready=True, worker_ready=True, matching_pin=True, unexpired=True)

    def test_cleanup_needs_all_confirmations(self):
        for index in range(3):
            run = FixtureRun("a")
            run.start(proxy_ready=True, worker_ready=True, matching_pin=True, unexpired=True)
            checks = [True] * 3
            checks[index] = False
            run.finish(stopped=checks[0], inaccessible=checks[1], deleted=checks[2])
            self.assertEqual(run.state, "cleanup_required")
            self.assertFalse(run.may_read("worker", "a/worker"))
            run.finish(stopped=True, inaccessible=True, deleted=True)
            self.assertEqual(run.state, "closed")
            self.assertFalse(run.may_read("proxy", "a/proxy"))


if __name__ == "__main__":
    unittest.main()
