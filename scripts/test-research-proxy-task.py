import json
import copy
import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def evaluate(expr, params, conditions):
    if not isinstance(expr, dict):
        return expr
    if "Ref" in expr:
        return params[expr["Ref"]]
    if "Condition" in expr:
        return evaluate(conditions[expr["Condition"]], params, conditions)
    if "Fn::Equals" in expr:
        a, b = expr["Fn::Equals"]
        return evaluate(a, params, conditions) == evaluate(b, params, conditions)
    if "Fn::Not" in expr:
        return not evaluate(expr["Fn::Not"][0], params, conditions)
    if "Fn::Or" in expr:
        return any(evaluate(x, params, conditions) for x in expr["Fn::Or"])
    raise AssertionError("Unsupported expression")


def validate_invariants(template):
    parameters = template["Parameters"]
    conditions = template["Conditions"]
    for flag in ("EnableProxyTask", "EnableProxyRepository"):
        assert parameters[flag]["Default"] == "false"
        assert parameters[flag]["AllowedValues"] == ["true", "false"]
    assert parameters["ProxyImageDigest"]["Default"] == ""
    assert parameters["ProxyImageDigest"]["AllowedPattern"] == "^$|^sha256:[a-f0-9]{64}$"
    rule = template["Rules"]["DigestRequired"]
    def accepted(repo, task, digest):
        params = {"EnableProxyRepository": repo, "EnableProxyTask": task, "ProxyImageDigest": digest}
        if not re.fullmatch(parameters["ProxyImageDigest"]["AllowedPattern"], digest):
            return False
        return not evaluate(rule["RuleCondition"], params, conditions) or all(
            evaluate(a["Assert"], params, conditions) for a in rule["Assertions"])
    digest = "sha256:" + "a" * 64
    for repo, task, value, expected in (
        ("false", "false", "", True), ("true", "false", "", True),
        ("true", "true", "", False), ("false", "true", digest, False),
        ("true", "true", digest, True), ("true", "true", "latest", False),
    ):
        assert accepted(repo, task, value) == expected
    resources = template["Resources"]
    outputs = template["Outputs"]
    assert set(resources) == {"ProxyRepository", "ProxyLogs", "ProxyExecutionRole", "ProxyTask"}
    assert set(outputs) == {"ProxyRepositoryUri", "ProxyTaskDefinition", "ProxyExecutionRoleArn"}
    for name, resource in resources.items():
        expected = "ProxyRepositoryEnabled" if name == "ProxyRepository" else "ProxyTaskEnabled"
        assert resource.get("Condition") == expected
    for name, output in outputs.items():
        expected = "ProxyRepositoryEnabled" if name == "ProxyRepositoryUri" else "ProxyTaskEnabled"
        assert output.get("Condition") == expected
    for repo, task in (("false", "false"), ("true", "false"), ("false", "true"), ("true", "true")):
        params = {"EnableProxyRepository": repo, "EnableProxyTask": task}
        assert evaluate(conditions["ProxyTaskEnabled"], params, conditions) == (task == "true")
        assert evaluate(conditions["ProxyRepositoryEnabled"], params, conditions) == (repo == "true" or task == "true")
    statements = resources["ProxyExecutionRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    assert statements[1]["Resource"] == {"Fn::GetAtt": ["ProxyRepository", "Arn"]}
    assert statements[2]["Resource"] == {"Fn::Sub": "arn:${AWS::Partition}:logs:${AWS::Region}:${AWS::AccountId}:log-group:${ProxyLogs}:log-stream:*"}
    assert "TaskRoleArn" not in resources["ProxyTask"]["Properties"]


class ProxyTaskTemplateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = json.loads((ROOT / "infra/research-aws/proxy-task.json").read_text(encoding="utf-8-sig"))
        cls.resources = cls.template["Resources"]

    def test_opt_in_and_digest(self):
        validate_invariants(self.template)
        image = self.resources["ProxyTask"]["Properties"]["ContainerDefinitions"][0]["Image"]
        self.assertIn("@${ProxyImageDigest}", image["Fn::Sub"])

    def test_separate_execution_role_and_no_application_permissions(self):
        task = self.resources["ProxyTask"]["Properties"]
        self.assertNotIn("TaskRoleArn", task)
        self.assertEqual(task["ExecutionRoleArn"], {"Fn::GetAtt": ["ProxyExecutionRole", "Arn"]})
        statements = self.resources["ProxyExecutionRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
        actions = {action for statement in statements for action in ([statement["Action"]] if isinstance(statement["Action"], str) else statement["Action"])}
        self.assertEqual(actions, {"ecr:GetAuthorizationToken", "ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage", "logs:CreateLogStream", "logs:PutLogEvents"})
        self.assertEqual(statements[1]["Resource"], {"Fn::GetAtt": ["ProxyRepository", "Arn"]})
        self.assertIn("${ProxyLogs}", statements[2]["Resource"]["Fn::Sub"])
        self.assertTrue(all(statement["Effect"] == "Allow" for statement in statements))
        self.assertEqual(statements[0]["Resource"], "*")
        self.assertNotEqual(statements[1]["Resource"], "*")
        self.assertNotEqual(statements[2]["Resource"], "*")
        trust = self.resources["ProxyExecutionRole"]["Properties"]["AssumeRolePolicyDocument"]["Statement"]
        self.assertEqual(trust, [{"Effect": "Allow", "Principal": {"Service": "ecs-tasks.amazonaws.com"}, "Action": "sts:AssumeRole"}])

    def test_inert_and_isolated_definition(self):
        self.assertEqual({r["Type"] for r in self.resources.values()}, {"AWS::ECR::Repository", "AWS::Logs::LogGroup", "AWS::IAM::Role", "AWS::ECS::TaskDefinition"})
        task = self.resources["ProxyTask"]["Properties"]
        self.assertEqual(task["NetworkMode"], "awsvpc")
        self.assertEqual(task["RequiresCompatibilities"], ["FARGATE"])
        self.assertEqual(len(task["ContainerDefinitions"]), 1)
        container = task["ContainerDefinitions"][0]
        self.assertTrue(container["ReadonlyRootFilesystem"])
        self.assertEqual(container["User"], "65534:65534")
        self.assertEqual(container["LinuxParameters"]["Capabilities"]["Drop"], ["ALL"])
        self.assertEqual(container["Environment"], [{"Name": "BAKATA_RESEARCH_PROXY_FIXTURE", "Value": "1"}])
        self.assertNotIn("Secrets", container)
        self.assertNotIn("Volumes", task)
        self.assertNotIn("Command", container)
        self.assertNotIn("EntryPoint", container)
        self.assertNotIn("MountPoints", container)

    def test_foundation_proxy_network_is_separate(self):
        foundation = json.loads((ROOT / "infra/research-aws/foundation.json").read_text(encoding="utf-8-sig"))
        resources = foundation["Resources"]
        for name in ("ProxyFixtureSubnet", "ProxyFixtureWorkerSubnet", "ProxyFixtureSecurityGroup", "ProxyFixtureWorkerSecurityGroup"):
            self.assertEqual(resources[name]["Condition"], "ProxyFixtureEnabled")
        ingress = resources["ProxyFixtureIngress"]["Properties"]
        self.assertEqual(ingress["SourceSecurityGroupId"], {"Ref": "ProxyFixtureWorkerSecurityGroup"})
        self.assertEqual((ingress["FromPort"], ingress["ToPort"]), (8443, 8443))
        self.assertEqual(ingress["GroupId"], {"Ref": "ProxyFixtureSecurityGroup"})
        self.assertEqual(ingress["IpProtocol"], "tcp")
        for subnet, association in (("ProxyFixtureSubnet", "ProxyFixtureSubnetAssociation"), ("ProxyFixtureWorkerSubnet", "ProxyFixtureWorkerSubnetAssociation")):
            self.assertFalse(resources[subnet]["Properties"]["MapPublicIpOnLaunch"])
            self.assertEqual(resources[association]["Condition"], "ProxyFixtureEnabled")
            self.assertEqual(resources[association]["Properties"]["SubnetId"], {"Ref": subnet})
            self.assertEqual(resources[association]["Properties"]["RouteTableId"], {"Ref": "ProxyFixtureRoutes"})
        route_table = {"Ref": "ProxyFixtureRoutes"}
        for resource in resources.values():
            if resource["Type"] == "AWS::EC2::Route":
                self.assertNotEqual(resource["Properties"].get("RouteTableId"), route_table)
        proxy_egress = resources["ProxyFixtureSecurityGroup"]["Properties"]["SecurityGroupEgress"]
        worker_egress = resources["ProxyFixtureWorkerSecurityGroup"]["Properties"]["SecurityGroupEgress"]
        def egress(destination, name, port):
            return {"IpProtocol": "tcp", "FromPort": port, "ToPort": port, destination: {"Ref": name}}
        self.assertEqual(proxy_egress, [egress("DestinationSecurityGroupId", "EndpointSecurityGroup", 443), egress("DestinationPrefixListId", "S3ManagedPrefixList", 443)])
        self.assertEqual(worker_egress, [egress("DestinationSecurityGroupId", "EndpointSecurityGroup", 443), egress("DestinationPrefixListId", "S3ManagedPrefixList", 443), egress("DestinationPrefixListId", "DynamoManagedPrefixList", 443), egress("DestinationSecurityGroupId", "ProxyFixtureSecurityGroup", 8443)])
        for name, source in (("ProxyFixtureEndpointIngress", "ProxyFixtureSecurityGroup"), ("ProxyFixtureWorkerEndpointIngress", "ProxyFixtureWorkerSecurityGroup")):
            self.assertEqual(resources[name]["Condition"], "ProxyFixtureEnabled")
            self.assertEqual(resources[name]["Properties"], {"GroupId": {"Ref": "EndpointSecurityGroup"}, "SourceSecurityGroupId": {"Ref": source}, "IpProtocol": "tcp", "FromPort": 443, "ToPort": 443})

    def test_guards_detect_unsafe_mutations(self):
        def missing_repo_condition(t):
            del t["Resources"]["ProxyRepository"]["Condition"]
        def missing_output_condition(t):
            del t["Outputs"]["ProxyRepositoryUri"]["Condition"]
        def empty_digest_allowed(t):
            del t["Rules"]["DigestRequired"]["Assertions"][0]
        def repo_not_required(t):
            del t["Rules"]["DigestRequired"]["Assertions"][1]
        def wildcard_repo(t):
            t["Resources"]["ProxyExecutionRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"][1]["Resource"] = "*"
        def task_role(t):
            t["Resources"]["ProxyTask"]["Properties"]["TaskRoleArn"] = "unsafe"
        def enabled_default(t):
            t["Parameters"]["EnableProxyRepository"]["Default"] = "true"
        for mutation in (missing_repo_condition, missing_output_condition, empty_digest_allowed, repo_not_required, wildcard_repo, task_role, enabled_default):
            with self.subTest(mutation=mutation.__name__):
                modified = copy.deepcopy(self.template)
                mutation(modified)
                with self.assertRaises(AssertionError):
                    validate_invariants(modified)


if __name__ == "__main__":
    unittest.main()
