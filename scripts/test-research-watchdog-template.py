import json
from pathlib import Path
import unittest

TEMPLATE = Path(__file__).resolve().parents[1] / "infra/research-aws/watchdog.json"

class WatchdogTemplateTests(unittest.TestCase):
    def setUp(self):
        self.t = json.loads(TEMPLATE.read_text())
        self.r = self.t["Resources"]
        self.statements = {s["Sid"]:s for s in self.r["WatchdogRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]}

    def test_disabled_and_pinned(self):
        self.assertEqual(self.t["Parameters"]["EnableWatchdog"]["Default"],"false")
        fn = self.r["Watchdog"]["Properties"]
        self.assertEqual(fn["ReservedConcurrentExecutions"],1)
        self.assertEqual(fn["Code"]["S3ObjectVersion"],{"Ref":"CodeVersion"})
        self.assertEqual(fn["Environment"]["Variables"]["BAKATA_WATCHDOG_ENABLED"],{"Ref":"EnableWatchdog"})
        self.assertEqual(self.r["WatchdogSchedule"]["Properties"]["State"],{"Fn::If":["WatchdogEnabled","ENABLED","DISABLED"]})

    def test_only_scoped_actions(self):
        actions = {a for s in self.statements.values() for a in ([s["Action"]] if isinstance(s["Action"],str) else s["Action"])}
        self.assertEqual(actions,{"dynamodb:GetItem","dynamodb:PutItem","ecs:ListTasks","ecs:DescribeTasks","ecs:StopTask","logs:CreateLogStream","logs:PutLogEvents"})
        stop = self.statements["StopTaggedFixtureOnly"]
        self.assertIn("task/${ClusterName}/*",stop["Resource"]["Fn::Sub"])
        self.assertEqual(stop["Condition"]["StringEquals"]["aws:ResourceTag/bakata:purpose"],"research-fixture")
        self.assertIn("ecs:cluster",stop["Condition"]["StringEquals"])
        self.assertIn("ecs:cluster",self.statements["DiscoverInReviewedCluster"]["Condition"]["StringEquals"])
        self.assertEqual(self.statements["LaunchLedgerOnly"]["Resource"],{"Fn::GetAtt":["LaunchTable","Arn"]})

    def test_ledger_retained_without_ttl(self):
        table = self.r["LaunchTable"]
        self.assertEqual(table["DeletionPolicy"],"Retain")
        self.assertEqual(table["UpdateReplacePolicy"],"Retain")
        self.assertNotIn("TimeToLiveSpecification",table["Properties"])

if __name__=="__main__":
    unittest.main()
