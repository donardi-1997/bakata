"""Offline invariants for the dormant pair-controller IAM boundary.

Security-relevant fields are compared *exactly* against reviewed values, so any
widening (extra condition, resource, action, role, policy resource) fails and
must be reviewed deliberately. Structural only: no evaluation against AWS.
"""
import copy
import json
from pathlib import Path
import unittest

INFRA = Path(__file__).resolve().parents[1] / "infra" / "research-aws"
TEMPLATE = json.loads((INFRA / "pair-controller.json").read_text())
FOUNDATION = json.loads((INFRA / "foundation.json").read_text())
PROXY = json.loads((INFRA / "proxy-task.json").read_text())

ON = "PairControllerEnabled"
ROLE_ARN = {"Fn::Sub": "arn:${AWS::Partition}:iam::${AWS::AccountId}:role/${AWS::StackName}-pair-controller"}
TABLE_ARN = {"Fn::Sub": "arn:${AWS::Partition}:dynamodb:${AWS::Region}:${AWS::AccountId}:table/${AWS::StackName}-pair-ledger"}
TASKS = {"Fn::Sub": ["arn:${AWS::Partition}:ecs:${AWS::Region}:${AWS::AccountId}:task/${Name}/*",
                     {"Name": {"Fn::Select": [1, {"Fn::Split": [":cluster/", {"Ref": "ClusterArn"}]}]}}]}
CLUSTER = {"ArnEquals": {"ecs:cluster": {"Ref": "ClusterArn"}}}
PURPOSE = {"bakata:purpose": "research-fixture"}

EXPECTED_STATEMENTS = {
    "RunOnlyReviewedDefinitions": {
        "Effect": "Allow", "Action": "ecs:RunTask",
        "Resource": [{"Ref": "WorkerTaskDefinitionArn"}, {"Ref": "ProxyTaskDefinitionArn"}],
        "Condition": {**CLUSTER, "StringEquals": {"aws:RequestTag/bakata:purpose": "research-fixture"},
                      "ForAllValues:StringEquals": {"aws:TagKeys": ["bakata:purpose", "bakata:role", "bakata:run", "bakata:until"]}}},
    "NeverExecuteCommand": {
        "Effect": "Deny", "Action": "ecs:RunTask", "Resource": "*",
        "Condition": {"StringEquals": {"ecs:enable-execute-command": "true"}}},
    "TagOnlyAtLaunch": {
        "Effect": "Allow", "Action": "ecs:TagResource", "Resource": TASKS,
        "Condition": {"StringEquals": {"ecs:CreateAction": "RunTask"}}},
    "ObserveAndStopResearchTasks": {
        "Effect": "Allow", "Action": ["ecs:DescribeTasks", "ecs:StopTask"], "Resource": TASKS,
        "Condition": {**CLUSTER, "StringEquals": {"ecs:ResourceTag/bakata:purpose": "research-fixture"}}},
    "ListOnlyResearchCluster": {
        "Effect": "Allow", "Action": "ecs:ListTasks", "Resource": "*", "Condition": CLUSTER},
    "PassOnlyReviewedTaskRoles": {
        "Effect": "Allow", "Action": "iam:PassRole",
        "Resource": [{"Ref": "WorkerTaskRoleArn"}, {"Ref": "WorkerExecutionRoleArn"}, {"Ref": "ProxyExecutionRoleArn"}],
        "Condition": {"StringEquals": {"iam:PassedToService": "ecs-tasks.amazonaws.com"}}},
    "AppendOnlyPairLedger": {
        "Effect": "Allow",
        "Action": ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:ConditionCheckItem"],
        "Resource": {"Fn::GetAtt": ["PairLedger", "Arn"]},
        "Condition": {"ForAllValues:StringLike": {"dynamodb:LeadingKeys": ["PAIR#*"]},
                      "Null": {"dynamodb:LeadingKeys": "false"}}},
    "OwnLogsOnly": {
        "Effect": "Allow", "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
        "Resource": {"Fn::Sub": "arn:${AWS::Partition}:logs:${AWS::Region}:${AWS::AccountId}:log-group:${ControllerLogs}:log-stream:*"}},
}
EXPECTED_LEDGER_POLICY = {"Version": "2012-10-17", "Statement": [{
    "Sid": "OnlyPairControllerWrites", "Effect": "Deny", "Principal": "*",
    "Action": ["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:BatchWriteItem",
               "dynamodb:PartiQLInsert", "dynamodb:PartiQLUpdate", "dynamodb:PartiQLDelete"],
    "Resource": TABLE_ARN,
    "Condition": {"ArnNotEquals": {"aws:PrincipalArn": ROLE_ARN}}}]}
EXPECTED_TRUST = {"Version": "2012-10-17", "Statement": [{
    "Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole",
    "Condition": {"StringEquals": {"aws:SourceAccount": {"Ref": "AWS::AccountId"}}}}]}
EXPECTED_PATTERNS = {
    "ClusterArn": "^$|^arn:aws:ecs:us-east-1:[0-9]{12}:cluster/bakata-research-[A-Za-z0-9_-]{1,80}$",
    "WorkerTaskDefinitionArn": "^$|^arn:aws:ecs:us-east-1:[0-9]{12}:task-definition/bakata-research-[A-Za-z0-9_-]{1,80}-persistent-fixture:[1-9][0-9]*$",
    "ProxyTaskDefinitionArn": "^$|^arn:aws:ecs:us-east-1:[0-9]{12}:task-definition/bakata-research-[A-Za-z0-9_-]{1,80}-proxy-fixture:[1-9][0-9]*$",
    "WorkerTaskRoleArn": "^$|^arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_-]{1,64}$",
    "WorkerExecutionRoleArn": "^$|^arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_-]{1,64}$",
    "ProxyExecutionRoleArn": "^$|^arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_-]{1,64}$",
}
ALLOWED_TYPES = {"PairLedger": "AWS::DynamoDB::Table", "ControllerLogs": "AWS::Logs::LogGroup",
                 "ControllerRole": "AWS::IAM::Role"}


def violations(t):
    found = []
    params = t["Parameters"]
    enable = params.get("EnablePairController", {})
    if enable != {"Type": "String", "Default": "false", "AllowedValues": ["false", "true"]}:
        found.append("enable flag changed")
    if t.get("Conditions") != {ON: {"Fn::Equals": [{"Ref": "EnablePairController"}, "true"]}}:
        found.append("condition changed")
    if set(params) != {"EnablePairController", *EXPECTED_PATTERNS}:
        found.append("parameters changed")
    for key, pattern in EXPECTED_PATTERNS.items():
        if params.get(key, {}).get("AllowedPattern") != pattern or params[key].get("Default") != "":
            found.append("parameter pattern widened: " + key)
    rule = t.get("Rules", {}).get("ReviewedInputsWhenEnabled", {})
    if rule.get("RuleCondition") != {"Fn::Equals": [{"Ref": "EnablePairController"}, "true"]}:
        found.append("rule condition changed")
    required = [a.get("Assert") for a in rule.get("Assertions", [])]
    if required != [{"Fn::Not": [{"Fn::Equals": [{"Ref": k}, ""]}]} for k in EXPECTED_PATTERNS]:
        found.append("inputs not all required when enabled")

    resources = t["Resources"]
    if {k: v.get("Type") for k, v in resources.items()} != ALLOWED_TYPES:
        found.append("resource set changed")
    for name, res in resources.items():
        if res.get("Condition") != ON:
            found.append("unconditioned resource " + name)
    for name, out in t.get("Outputs", {}).items():
        if out.get("Condition") != ON:
            found.append("unconditioned output " + name)

    ledger = resources.get("PairLedger", {})
    props = ledger.get("Properties", {})
    if ledger.get("DeletionPolicy") != "Retain" or ledger.get("UpdateReplacePolicy") != "Retain":
        found.append("ledger can be deleted or replaced")
    if (props.get("DeletionProtectionEnabled") is not True
        or props.get("PointInTimeRecoverySpecification") != {"PointInTimeRecoveryEnabled": True}
        or props.get("SSESpecification") != {"SSEEnabled": True}
        or props.get("TableName") != {"Fn::Sub": "${AWS::StackName}-pair-ledger"}):
        found.append("ledger protection changed")
    if props.get("ResourcePolicy") != {"PolicyDocument": EXPECTED_LEDGER_POLICY}:
        found.append("ledger writable by principals other than the controller")

    role = resources.get("ControllerRole", {}).get("Properties", {})
    if set(role) != {"RoleName", "AssumeRolePolicyDocument", "Policies"}:
        found.append("controller role has extra properties (path, managed policies, boundary changes)")
    if role.get("RoleName") != {"Fn::Sub": "${AWS::StackName}-pair-controller"}:
        found.append("controller role name changed")
    if role.get("AssumeRolePolicyDocument") != EXPECTED_TRUST:
        found.append("controller trust changed")
    policies = role.get("Policies", [])
    if len(policies) != 1 or policies[0].get("PolicyName") != "PairControllerLeastPrivilege":
        found.append("controller policy set changed")
    else:
        statements = policies[0]["PolicyDocument"].get("Statement", [])
        actual = {s.get("Sid"): {k: v for k, v in s.items() if k != "Sid"} for s in statements}
        if len(actual) != len(statements) or actual != EXPECTED_STATEMENTS:
            for sid in sorted(set(actual) | set(EXPECTED_STATEMENTS), key=str):
                if actual.get(sid) != EXPECTED_STATEMENTS.get(sid):
                    found.append("controller statement changed: " + str(sid))
    return found


def network_violations(foundation, proxy):
    found = []
    res = foundation["Resources"]
    proxy_sg = ({"Ref": "ProxyFixtureSecurityGroup"}, {"Fn::GetAtt": ["ProxyFixtureSecurityGroup", "GroupId"]})
    ingress = [r["Properties"] for r in res.values() if r["Type"] == "AWS::EC2::SecurityGroupIngress"
               and r["Properties"].get("GroupId") in proxy_sg]
    if ingress != [{"GroupId": {"Ref": "ProxyFixtureSecurityGroup"},
                    "SourceSecurityGroupId": {"Ref": "ProxyFixtureWorkerSecurityGroup"},
                    "IpProtocol": "tcp", "FromPort": 8443, "ToPort": 8443}]:
        found.append("proxy ingress is not exactly worker SG on tcp/8443")
    sg = res["ProxyFixtureSecurityGroup"]["Properties"]
    if sg.get("SecurityGroupIngress"):
        found.append("inline proxy ingress")
    if sg.get("SecurityGroupEgress") != [
            {"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "DestinationSecurityGroupId": {"Ref": "EndpointSecurityGroup"}},
            {"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "DestinationPrefixListId": {"Ref": "S3ManagedPrefixList"}}]:
        found.append("proxy egress widened")
    if any(r["Type"] == "AWS::EC2::SecurityGroupEgress" and r["Properties"].get("GroupId") in proxy_sg
           for r in res.values()):
        found.append("separate proxy egress rule")
    if "TaskRoleArn" in proxy["Resources"]["ProxyTask"]["Properties"]:
        found.append("proxy task has an application role")
    worker_statements = [s for p in res["FixtureTaskRole"]["Properties"]["Policies"]
                         for s in p["PolicyDocument"]["Statement"]]
    worker_actions = {a for s in worker_statements
                      for a in ([s.get("Action")] if isinstance(s.get("Action"), str) else s.get("Action") or ["*"])}
    if (any(a.startswith(("ecs:", "iam:", "lambda:", "sts:")) or "*" in a for a in worker_actions)
        or any("NotAction" in s or "NotResource" in s for s in worker_statements)):
        found.append("worker task role can control tasks or roles")
    if any(s.get("Effect") == "Allow" and s.get("Resource") in ("*", ["*"]) for s in worker_statements):
        found.append("worker task role has a wildcard resource")
    if res["FixtureTaskRole"]["Properties"].get("ManagedPolicyArns"):
        found.append("worker task role has managed policies")
    return found


def _stmt(t, sid):
    return next(s for s in t["Resources"]["ControllerRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
                if s.get("Sid") == sid)


# Includes the 24 mutations of the independent audit (21 previously undetected).
TEMPLATE_MUTATIONS = {
    "enabled by default": lambda t: t["Parameters"]["EnablePairController"].update(Default="true"),
    "unconditioned resource": lambda t: t["Resources"]["ControllerRole"].pop("Condition"),
    "runnable resource": lambda t: t["Resources"].update(F={"Type": "AWS::Lambda::Function", "Condition": ON}),
    "extra inline role policy resource": lambda t: t["Resources"].update(P={"Type": "AWS::IAM::RolePolicy", "Condition": ON, "Properties": {
        "RoleName": {"Ref": "ControllerRole"}, "PolicyName": "x",
        "PolicyDocument": {"Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]}}}),
    "input not required": lambda t: t["Rules"]["ReviewedInputsWhenEnabled"]["Assertions"].pop(),
    "rule never applies": lambda t: t["Rules"]["ReviewedInputsWhenEnabled"].update(RuleCondition={"Fn::Equals": ["a", "b"]}),
    "pattern widened": lambda t: t["Parameters"]["WorkerTaskRoleArn"].update(AllowedPattern=".*"),
    "ledger writable": lambda t: t["Resources"]["PairLedger"]["Properties"].pop("ResourcePolicy"),
    "ledger deny weakened by AND": lambda t: t["Resources"]["PairLedger"]["Properties"]["ResourcePolicy"]["PolicyDocument"]["Statement"][0]["Condition"].update(
        ArnNotLike={"aws:PrincipalArn": "arn:aws:iam::*:role/*"}),
    "ledger deny missing UpdateItem": lambda t: t["Resources"]["PairLedger"]["Properties"]["ResourcePolicy"]["PolicyDocument"]["Statement"][0]["Action"].remove("dynamodb:UpdateItem"),
    "ledger deletable": lambda t: t["Resources"]["PairLedger"].update(DeletionPolicy="Delete"),
    "ledger replaceable": lambda t: t["Resources"]["PairLedger"].update(UpdateReplacePolicy="Delete"),
    "exec deny removed": lambda t: t["Resources"]["ControllerRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"].remove(_stmt(t, "NeverExecuteCommand")),
    "RunTask wildcard": lambda t: _stmt(t, "RunOnlyReviewedDefinitions").update(Resource="*"),
    "RunTask wildcard list": lambda t: _stmt(t, "RunOnlyReviewedDefinitions").update(Resource=["*"]),
    "RunTask any ARN": lambda t: _stmt(t, "RunOnlyReviewedDefinitions").update(Resource="arn:aws:ecs:*:*:*"),
    "RunTask without cluster": lambda t: _stmt(t, "RunOnlyReviewedDefinitions")["Condition"].pop("ArnEquals"),
    "RunTask without request tag": lambda t: _stmt(t, "RunOnlyReviewedDefinitions")["Condition"].pop("StringEquals"),
    "RunTask any tag keys": lambda t: _stmt(t, "RunOnlyReviewedDefinitions")["Condition"].pop("ForAllValues:StringEquals"),
    "unexpected action": lambda t: _stmt(t, "ObserveAndStopResearchTasks")["Action"].append("ecs:RegisterTaskDefinition"),
    "wildcard action": lambda t: _stmt(t, "ListOnlyResearchCluster").update(Action="ecs:*"),
    "StopTask without tag": lambda t: _stmt(t, "ObserveAndStopResearchTasks")["Condition"].pop("StringEquals"),
    "split Describe without tag": lambda t: t["Resources"]["ControllerRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"].append(
        {"Sid": "Extra", "Effect": "Allow", "Action": "ecs:DescribeTasks", "Resource": "*"}),
    "PassRole without service": lambda t: _stmt(t, "PassOnlyReviewedTaskRoles").pop("Condition"),
    "PassRole wildcard": lambda t: _stmt(t, "PassOnlyReviewedTaskRoles").update(Resource="*"),
    "PassRole extra admin role": lambda t: _stmt(t, "PassOnlyReviewedTaskRoles")["Resource"].append("arn:aws:iam::123456789012:role/Admin"),
    "controller deletes items": lambda t: _stmt(t, "AppendOnlyPairLedger")["Action"].append("dynamodb:DeleteItem"),
    "ledger any partition": lambda t: _stmt(t, "AppendOnlyPairLedger")["Condition"]["ForAllValues:StringLike"].update({"dynamodb:LeadingKeys": ["*"]}),
    "ledger without Null guard": lambda t: _stmt(t, "AppendOnlyPairLedger")["Condition"].pop("Null"),
    "trust without account": lambda t: t["Resources"]["ControllerRole"]["Properties"]["AssumeRolePolicyDocument"]["Statement"][0].pop("Condition"),
    "trust other account": lambda t: t["Resources"]["ControllerRole"]["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]["Condition"]["StringEquals"].update(
        {"aws:SourceAccount": "999999999999"}),
    "managed policy": lambda t: t["Resources"]["ControllerRole"]["Properties"].update(ManagedPolicyArns=["arn:aws:iam::aws:policy/AdministratorAccess"]),
    "role path breaks ledger ARN": lambda t: t["Resources"]["ControllerRole"]["Properties"].update(Path="/x/"),
    "logs any group": lambda t: _stmt(t, "OwnLogsOnly").update(Resource="*"),
}


class PairControllerIamTests(unittest.TestCase):
    def test_template_invariants(self):
        self.assertEqual(violations(TEMPLATE), [])

    def test_cross_template_separation(self):
        self.assertEqual(network_violations(FOUNDATION, PROXY), [])

    def test_template_mutations_detected(self):
        for name, fn in TEMPLATE_MUTATIONS.items():
            t = copy.deepcopy(TEMPLATE)
            fn(t)
            with self.subTest(name):
                self.assertNotEqual(violations(t), [], name)

    def test_network_mutations_detected(self):
        def foundation(fn):
            f = copy.deepcopy(FOUNDATION)
            fn(f["Resources"])
            return f
        cases = {
            "ingress from endpoints": foundation(lambda r: r["ProxyFixtureIngress"]["Properties"].update(
                SourceSecurityGroupId={"Ref": "EndpointSecurityGroup"})),
            "ingress port widened": foundation(lambda r: r["ProxyFixtureIngress"]["Properties"].update(ToPort=9000)),
            "extra ingress via GetAtt": foundation(lambda r: r.update(X={"Type": "AWS::EC2::SecurityGroupIngress", "Properties": {
                "GroupId": {"Fn::GetAtt": ["ProxyFixtureSecurityGroup", "GroupId"]}, "CidrIp": "0.0.0.0/0",
                "IpProtocol": "-1"}})),
            "proxy egress opened": foundation(lambda r: r["ProxyFixtureSecurityGroup"]["Properties"]["SecurityGroupEgress"].append(
                {"IpProtocol": "-1", "CidrIp": "0.0.0.0/0"})),
            "worker role wildcard write": foundation(lambda r: r["FixtureTaskRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"].append(
                {"Effect": "Allow", "Action": "dynamodb:PutItem", "Resource": "*"})),
            "worker role NotAction": foundation(lambda r: r["FixtureTaskRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"].append(
                {"Effect": "Allow", "NotAction": "s3:GetObject", "Resource": "arn:aws:s3:::x/*"})),
            "worker role controls tasks": foundation(lambda r: r["FixtureTaskRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"].append(
                {"Effect": "Allow", "Action": "ecs:RunTask", "Resource": "*"})),
        }
        for name, f in cases.items():
            with self.subTest(name):
                self.assertTrue(network_violations(f, PROXY), name)
        p = copy.deepcopy(PROXY)
        p["Resources"]["ProxyTask"]["Properties"]["TaskRoleArn"] = "arn:aws:iam::123456789012:role/x"
        self.assertTrue(network_violations(FOUNDATION, p))


if __name__ == "__main__":
    unittest.main()
