import json
import unittest
from unittest.mock import Mock
from intelligence.research_launcher import FixtureLaunchConfig, FixtureLauncher

BASE = "arn:aws:ecs:us-east-1:123456789012:"
NOW = 1795748400

class Ledger:
    """Atomic conditional-write fake. No AWS or network."""
    def __init__(self):
        self.items = {}
        self.fail_second = False
        self.writes = 0
    def transact_write_items(self, *, TransactItems):
        self.writes += 1
        if self.fail_second and self.writes == 2:
            raise RuntimeError("synthetic failure")
        new = dict(self.items)
        for entry in TransactItems:
            p = entry["Put"]
            item = p["Item"]
            key = item["sk"]["S"]
            old = new.get(key)
            if p["ConditionExpression"] == "attribute_not_exists(pk)":
                if old is not None:
                    raise RuntimeError("duplicate")
            elif old is None or old["payload"] != p["ExpressionAttributeValues"][":old"]:
                raise RuntimeError("changed")
            new[key] = item
        self.items = new
    def get_item(self, *, TableName, Key, ConsistentRead):
        assert ConsistentRead
        return {"Item": self.items.get(Key["sk"]["S"])}

class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.config = FixtureLaunchConfig(BASE+"cluster/bakata-research-ci",
            BASE+"task-definition/bakata-research-ci-persistent-fixture:1",
            "subnet-"+"a"*17, "sg-"+"b"*17, "bakata-research-ci-launches")
        self.ddb, self.ecs = Ledger(), Mock()
        self.task = BASE+"task/bakata-research-ci/"+"a"*32
        self.ecs.run_task.return_value = {"failures": [], "tasks": [{
            "taskArn": self.task, "clusterArn": self.config.cluster,
            "taskDefinitionArn": self.config.definition, "launchType": "FARGATE"}]}
        self.launcher = FixtureLauncher(self.ddb, self.ecs, self.config, enabled=True)

    def launch(self, run="fixture-ci", until=NOW+300):
        return self.launcher.launch(run, until, clock=lambda:NOW)

    def test_disabled_or_invalid_no_writes(self):
        with self.assertRaises(ValueError):
            FixtureLauncher(self.ddb, self.ecs, self.config).launch("fixture-ci", NOW+300, clock=lambda:NOW)
        for run, until in [("live-ci", NOW+300), ("fixture-ci", NOW+10), ("fixture-ci", NOW+1801)]:
            with self.assertRaises(ValueError):
                self.launch(run, until)
        self.assertEqual(self.ddb.writes, 0)
        self.ecs.run_task.assert_not_called()

    def test_exact_launch_and_binding(self):
        b = self.launch()
        self.assertEqual(b.task, self.task)
        self.assertEqual(self.launcher.binding("fixture-ci"), b)
        self.ecs.run_task.assert_called_once()
        args = self.ecs.run_task.call_args.kwargs
        self.assertEqual(args["count"], 1)
        self.assertEqual(args["taskDefinition"], self.config.definition)
        self.assertFalse(args["enableExecuteCommand"])
        self.assertEqual(args["networkConfiguration"]["awsvpcConfiguration"], {
            "subnets":[self.config.subnet], "securityGroups":[self.config.security_group],
            "assignPublicIp":"DISABLED"})
        self.assertEqual([x["name"] for x in args["overrides"]["containerOverrides"]], ["worker","coordinator"])
        for item in args["overrides"]["containerOverrides"]:
            self.assertEqual(item["environment"], [{"name":"BAKATA_RESEARCH_RUN","value":"fixture-ci"},
                {"name":"BAKATA_RESEARCH_UNTIL","value":str(NOW+300)}])
        self.assertEqual(len(args["clientToken"]), 64)

    def test_duplicate_and_other_run_blocked(self):
        self.launch()
        for run in ("fixture-ci", "fixture-other"):
            with self.assertRaises(ValueError):
                self.launch(run)
        self.ecs.run_task.assert_called_once()

    def test_ambiguous_launch_burns_slot(self):
        self.ecs.run_task.side_effect = RuntimeError("private error")
        with self.assertRaisesRegex(ValueError, "reconcile"):
            self.launch()
        with self.assertRaises(ValueError):
            self.launch("fixture-other")
        with self.assertRaises(ValueError):
            self.launcher.binding("fixture-ci")
        self.ecs.run_task.assert_called_once()

    def test_wrong_identity_or_binding_write_failure(self):
        self.ecs.run_task.return_value["tasks"][0]["launchType"] = "EC2"
        with self.assertRaises(ValueError):
            self.launch()
        with self.assertRaises(ValueError):
            self.launcher.binding("fixture-ci")
        self.setUp()
        self.ddb.fail_second = True
        with self.assertRaises(ValueError):
            self.launch()
        with self.assertRaises(ValueError):
            self.launcher.binding("fixture-ci")
        with self.assertRaises(ValueError):
            self.launch("fixture-other")
        self.ecs.run_task.assert_called_once()

    def test_expiry_before_request_and_after_response(self):
        ticks = iter([NOW, NOW+280])
        with self.assertRaises(ValueError):
            self.launcher.launch("fixture-ci", NOW+300, clock=lambda:next(ticks))
        self.ecs.run_task.assert_not_called()
        self.setUp()
        ticks = iter([NOW, NOW+1])
        self.assertEqual(self.launcher.launch("fixture-ci", NOW+300, clock=lambda:next(ticks)).until, NOW+300)

    def test_inconsistent_ledger_denied(self):
        self.launch()
        raw = self.ddb.items["ACTIVE"]["payload"]["S"]
        self.ddb.items["ACTIVE"]["payload"]["S"] = raw.replace("bound", "other")
        with self.assertRaises(ValueError):
            self.launcher.binding("fixture-ci")

if __name__ == "__main__":
    unittest.main()
