import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from intelligence.dropify_capture import policy
from intelligence.research_credentials import SecretBinding,SCHEMA
from intelligence.research_fixture_gate import FixtureCredentialGate
from intelligence.research_worker import coordinate
from intelligence.research_watchdog import FixtureTaskBinding,enforce_deadline


class GateTests(unittest.TestCase):
    def test_gate_failure_leaves_reservation_and_no_request(self):
        now=1795748400
        plan=policy("fixture-gate","7",1,3,now+300,"ci","fixture-task")
        binding=SecretBinding("arn:aws:secretsmanager:us-east-1:123456789012:secret:bakata/research/dropify/fixture-Ab1234","a"*32,"123456789012","7")
        for token in ("invalid-fixture-token","ci-only-token-canary"):
            sm=Mock()
            sm.get_secret_value.return_value={"ARN":binding.arn,"VersionId":binding.version,
                "VersionStages":["AWSPREVIOUS"] if token=="ci-only-token-canary" else ["AWSCURRENT"],
                "SecretString":json.dumps({"schema":SCHEMA,"store_id":"7","token":token})}
            receipts=Mock()
            receipts.reserve.return_value={"plan":plan,"state":"reserved","attempt":"b"*32,"reserved_at":now}
            with tempfile.TemporaryDirectory() as directory:
                exchange=Path(directory)
                (exchange/"ready.json").write_text(json.dumps({"run":plan["run"],"store":"7"}))
                with self.assertRaises(ValueError):
                    coordinate(exchange,receipts,plan,clock=lambda:now,credential_gate=FixtureCredentialGate(sm,binding))
                receipts.reserve.assert_called_once_with(plan,1,now=now)
                receipts.persist.assert_not_called()
                sm.get_secret_value.assert_called_once()
                self.assertFalse(list(exchange.glob("request-*")))
                self.assertTrue((exchange/"coordinator.json").exists())


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.now=1795748400
        base="arn:aws:ecs:us-east-1:123456789012:"
        self.binding=FixtureTaskBinding(base+"cluster/bakata-research-ci",base+"task/bakata-research-ci/"+"a"*32,
            base+"task-definition/bakata-research-ci-persistent-fixture:1","fixture-ci",self.now)
        b=self.binding
        self.task={"taskArn":b.task,"clusterArn":b.cluster,"taskDefinitionArn":b.definition,"launchType":"FARGATE",
                   "lastStatus":"RUNNING","desiredStatus":"RUNNING","tags":[{"key":"bakata:purpose","value":"research-fixture"},
                    {"key":"bakata:run","value":b.run},{"key":"bakata:until","value":str(b.until)}]}
        self.ecs=Mock()
        self.ecs.describe_tasks.return_value={"tasks":[self.task],"failures":[]}
        self.ecs.stop_task.return_value={"task":{"taskArn":b.task,"desiredStatus":"STOPPED"}}

    def test_before_deadline_no_aws(self):
        self.assertEqual(enforce_deadline(self.ecs,self.binding,now=self.now-1)["state"],"before-deadline")
        self.ecs.describe_tasks.assert_not_called()
        self.ecs.stop_task.assert_not_called()

    def test_exact_expired_task_only(self):
        result=enforce_deadline(self.ecs,self.binding,now=self.now)
        self.assertEqual(result,{"state":"stop-requested","stop_requested":True})
        self.ecs.describe_tasks.assert_called_once_with(cluster=self.binding.cluster,tasks=[self.binding.task],include=["TAGS"])
        self.ecs.stop_task.assert_called_once_with(cluster=self.binding.cluster,task=self.binding.task,reason="Bakata research fixture deadline exceeded")

    def test_wrong_task_or_tags_denied(self):
        for changes in [{"taskArn":"wrong"},{"clusterArn":"wrong"},{"taskDefinitionArn":"wrong"},{"launchType":"EC2"},
                        {"tags":[]},{"tags":self.task["tags"]+[self.task["tags"][0]]},{"desiredStatus":"OTHER"}]:
            self.ecs.describe_tasks.return_value={"tasks":[dict(self.task,**changes)]}
            with self.assertRaisesRegex(ValueError,"unverified"):
                enforce_deadline(self.ecs,self.binding,now=self.now)
        self.ecs.stop_task.assert_not_called()

    def test_stopped_or_stopping_not_repeated(self):
        for changes,state in [({"lastStatus":"STOPPED","desiredStatus":"STOPPED"},"stopped"),
                              ({"desiredStatus":"STOPPED"},"stopping")]:
            self.ecs.describe_tasks.return_value={"tasks":[dict(self.task,**changes)]}
            self.assertEqual(enforce_deadline(self.ecs,self.binding,now=self.now)["state"],state)
        self.ecs.stop_task.assert_not_called()

    def test_uncertain_stop_not_repeated(self):
        self.ecs.stop_task.side_effect=RuntimeError("synthetic transport failure")
        with self.assertRaisesRegex(ValueError,"unverified"):
            enforce_deadline(self.ecs,self.binding,now=self.now)
        self.ecs.stop_task.assert_called_once()

    def test_nonresearch_task_binding_denied(self):
        b=self.binding
        with self.assertRaises(ValueError):
            FixtureTaskBinding(b.cluster.replace("bakata-research-ci","production"),b.task,b.definition,b.run,b.until)
        with self.assertRaises(ValueError):
            FixtureTaskBinding(b.cluster,b.task,b.definition.replace("persistent-fixture","live"),b.run,b.until)


if __name__=="__main__":
    unittest.main()
