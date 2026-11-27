import unittest
from unittest.mock import Mock
from test_research_launcher import Ledger, BASE, NOW
from intelligence.research_launcher import FixtureLaunchConfig, FixtureLauncher
from intelligence.research_supervisor import supervise

class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.config = FixtureLaunchConfig(BASE+"cluster/bakata-research-ci",
            BASE+"task-definition/bakata-research-ci-persistent-fixture:1",
            "subnet-"+"a"*17, "sg-"+"b"*17, "bakata-research-ci-launches")
        self.ddb, self.ecs = Ledger(), Mock()
        self.until = NOW+300
        self.task = {"taskArn": BASE+"task/bakata-research-ci/"+"a"*32,
            "clusterArn": self.config.cluster, "taskDefinitionArn": self.config.definition,
            "launchType": "FARGATE", "lastStatus": "RUNNING", "desiredStatus": "RUNNING",
            "tags": [{"key":"bakata:purpose","value":"research-fixture"},
                     {"key":"bakata:run","value":"fixture-ci"},
                     {"key":"bakata:until","value":str(self.until)}]}
        self.ecs.run_task.return_value = {"tasks":[self.task],"failures":[]}
        self.ecs.list_tasks.return_value = {"taskArns":[self.task["taskArn"]]}
        self.ecs.describe_tasks.return_value = {"tasks":[self.task],"failures":[]}
        self.ecs.stop_task.return_value = {"task":{"taskArn":self.task["taskArn"],"desiredStatus":"STOPPED"}}

    def launch(self, ambiguous=False):
        if ambiguous:
            self.ddb.fail_second = True
        launcher = FixtureLauncher(self.ddb, self.ecs, self.config, enabled=True)
        if ambiguous:
            with self.assertRaises(ValueError):
                launcher.launch("fixture-ci", self.until, clock=lambda:NOW)
        else:
            launcher.launch("fixture-ci", self.until, clock=lambda:NOW)
        self.ddb.fail_second = False
        self.task["startedBy"] = self.ecs.run_task.call_args.kwargs["startedBy"]

    def tick(self, now=None):
        return supervise(self.ddb,self.ecs,table=self.config.table,cluster=self.config.cluster,
            definition=self.config.definition,now=self.until if now is None else now)

    def test_idle_and_before_deadline(self):
        self.assertEqual(self.tick(),"idle")
        self.launch()
        self.assertEqual(self.tick(self.until-1),"before-deadline")
        self.ecs.list_tasks.assert_not_called()
        self.ecs.describe_tasks.assert_not_called()
        self.ecs.stop_task.assert_not_called()

    def test_pending_reconciles_exact_task(self):
        self.launch(ambiguous=True)
        self.assertEqual(self.tick(),"stop-requested")
        self.ecs.list_tasks.assert_called_once_with(cluster=self.config.cluster,startedBy=self.task["startedBy"],maxResults=2)
        self.ecs.stop_task.assert_called_once()
        self.assertEqual(self.ecs.run_task.call_count,1)
        self.assertIn("ACTIVE",self.ddb.items)

    def test_no_candidate_or_ambiguous_candidates(self):
        self.launch(ambiguous=True)
        for page in [{"taskArns":[]},{"taskArns":[self.task["taskArn"]],"nextToken":"more"},
                     {"taskArns":[self.task["taskArn"],self.task["taskArn"]]}]:
            self.ecs.list_tasks.return_value=page
            with self.assertRaises(ValueError):
                self.tick()
        self.ecs.stop_task.assert_not_called()

    def test_wrong_identity_or_tags_never_stopped(self):
        self.launch(ambiguous=True)
        for changes in [{"startedBy":"other"},{"taskDefinitionArn":"other"},{"tags":[]},
                        {"clusterArn":"other"},{"launchType":"EC2"}]:
            self.ecs.describe_tasks.return_value={"tasks":[dict(self.task,**changes)],"failures":[]}
            with self.assertRaises(ValueError):
                self.tick()
        self.ecs.stop_task.assert_not_called()

    def test_uncertain_stop_never_repeated(self):
        self.launch()
        self.ecs.stop_task.side_effect=RuntimeError("ambiguous")
        with self.assertRaises(ValueError):
            self.tick()
        with self.assertRaises(ValueError):
            self.tick(self.until+60)
        self.ecs.stop_task.assert_called_once()
        self.task.update(lastStatus="STOPPED",desiredStatus="STOPPED")
        self.assertEqual(self.tick(self.until+120),"stopped")
        self.ecs.stop_task.assert_called_once()
        self.assertIn("ACTIVE",self.ddb.items)

    def test_stop_requested_is_not_stopped(self):
        self.launch()
        self.assertEqual(self.tick(),"stop-requested")
        self.task["desiredStatus"]="STOPPED"
        self.assertEqual(self.tick(self.until+60),"stopping")
        self.task["lastStatus"]="STOPPED"
        self.assertEqual(self.tick(self.until+120),"stopped")
        self.ecs.stop_task.assert_called_once()

    def test_inconsistent_ledger(self):
        self.launch()
        self.ddb.items["RUN#fixture-ci"]={"payload":{"S":"{}"}}
        with self.assertRaises(ValueError):
            self.tick()
        self.ecs.describe_tasks.assert_not_called()
        self.ecs.stop_task.assert_not_called()

    def test_failed_claim_prevents_stop(self):
        self.launch()
        self.ddb.writes=1
        self.ddb.fail_second=True
        with self.assertRaises(ValueError):
            self.tick()
        self.ecs.stop_task.assert_not_called()

if __name__=="__main__":
    unittest.main()
