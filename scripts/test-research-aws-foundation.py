"""Offline safety regression tests for the dormant research stack."""
import json
from pathlib import Path
import unittest

TEMPLATE=Path(__file__).resolve().parents[1]/"infra/research-aws/foundation.json"


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.t=json.loads(TEMPLATE.read_text())
        self.r=self.t["Resources"]

    def props(self,name):
        return self.r[name]["Properties"]

    def test_dormant_defaults(self):
        self.assertEqual(self.t["Parameters"]["EnableFixtureNetwork"]["Default"],"false")
        self.assertEqual(self.props("Coordinator")["ReservedConcurrentExecutions"],0)
        forbidden={"AWS::ECS::Service","AWS::Events::Rule","AWS::Scheduler::Schedule",
                   "AWS::Lambda::EventSourceMapping","AWS::Lambda::Permission",
                   "AWS::EC2::InternetGateway","AWS::EC2::NatGateway","AWS::EC2::Route",
                   "AWS::EC2::VPCPeeringConnection","AWS::SecretsManager::Secret"}
        self.assertFalse(forbidden & {r["Type"] for r in self.r.values()})
        for name,r in self.r.items():
            if r["Type"].startswith("AWS::EC2::") or name in ("FixtureTask","ExecutionRole","WorkerLogs"):
                self.assertEqual(r["Condition"],"FixtureNetworkEnabled")
        self.assertFalse(self.props("ResearchSubnet")["MapPublicIpOnLaunch"])
        self.assertFalse(self.props("WorkerSecurityGroup").get("SecurityGroupIngress"))
        self.assertIn("ImagesRequired",self.t["Rules"])

    def test_persistent_evidence(self):
        bucket=self.props("EvidenceBucket")
        self.assertTrue(all(bucket["PublicAccessBlockConfiguration"].values()))
        self.assertEqual(bucket["VersioningConfiguration"]["Status"],"Enabled")
        self.assertEqual(bucket["OwnershipControls"]["Rules"][0]["ObjectOwnership"],"BucketOwnerEnforced")
        self.assertTrue(self.props("CaptureLedger")["DeletionProtectionEnabled"])
        self.assertTrue(self.props("CaptureLedger")["PointInTimeRecoverySpecification"]["PointInTimeRecoveryEnabled"])
        for name in ("EvidenceBucket","CaptureLedger","WorkerRepository","DatabaseRepository"):
            self.assertEqual(self.r[name]["DeletionPolicy"],"Retain")
            self.assertEqual(self.r[name]["UpdateReplacePolicy"],"Retain")
        for name in ("WorkerRepository","DatabaseRepository"):
            self.assertEqual(self.props(name)["ImageTagMutability"],"IMMUTABLE")
            self.assertTrue(self.props(name)["ImageScanningConfiguration"]["ScanOnPush"])

    def test_no_task_permissions_or_credential_injection(self):
        task=self.props("FixtureTask")
        self.assertNotIn("TaskRoleArn",task)
        self.assertEqual(task["NetworkMode"],"awsvpc")
        self.assertEqual(task["RequiresCompatibilities"],["FARGATE"])
        for c in task["ContainerDefinitions"]:
            self.assertNotIn("Secrets",c)
            self.assertFalse(c.get("PortMappings"))
            self.assertIn("@",c["Image"]["Fn::Sub"])
        worker=next(c for c in task["ContainerDefinitions"] if c["Name"]=="worker")
        self.assertEqual(worker["User"],"33:33")
        self.assertTrue(worker["ReadonlyRootFilesystem"])
        self.assertEqual(worker["LinuxParameters"]["Capabilities"]["Drop"],["ALL"])
        self.assertEqual(worker["DependsOn"],[{"ContainerName":"database","Condition":"HEALTHY"}])
        self.assertEqual(worker["Environment"],[{"Name":"BAKATA_RESEARCH_FIXTURE","Value":"1"}])
        for name in ("CoordinatorRole","ExecutionRole"):
            for inline in self.props(name)["Policies"]:
                for statement in inline["PolicyDocument"]["Statement"]:
                    actions=statement["Action"]
                    if isinstance(actions,str): actions=[actions]
                    self.assertTrue(all(x.startswith(("logs:","ecr:")) and "*" not in x for x in actions))
                    if statement["Resource"]=="*":
                        self.assertEqual(actions,["ecr:GetAuthorizationToken"])

    def test_endpoint_scope(self):
        self.assertEqual(self.props("S3Endpoint")["VpcEndpointType"],"Gateway")
        stmt=self.props("S3Endpoint")["PolicyDocument"]["Statement"][0]
        self.assertEqual(stmt["Action"],"s3:GetObject")
        self.assertIn("starport-layer-bucket",stmt["Resource"]["Fn::Sub"])
        for name in ("EcrApiEndpoint","EcrDockerEndpoint","LogsEndpoint"):
            self.assertTrue(self.props(name)["PrivateDnsEnabled"])
            self.assertEqual(self.props(name)["VpcEndpointType"],"Interface")


if __name__=="__main__":
    unittest.main()
