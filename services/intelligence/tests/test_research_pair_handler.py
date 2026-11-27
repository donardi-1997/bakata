"""Pair controller Lambda handler: Moto DynamoDB + fake ECS, no network or AWS."""
import json
import os
import unittest

try:
    import boto3
    from moto import mock_aws
except ImportError:  # the intelligence image has no AWS SDK
    boto3 = None

from test_research_pair_dynamo_ledger import TEMPLATE

TABLE = "bakata-research-ci-pair-ledger"


def environment(**changes):
    from test_research_pair_controller import config
    c = config()
    env = {"AWS_REGION": "us-east-1", "BAKATA_PAIR_CONTROLLER_ENABLED": "true",
           "BAKATA_PAIR_TABLE": TABLE, "BAKATA_PAIR_NONCE": "0" * 32,
           "BAKATA_CLUSTER": c.cluster, "BAKATA_PROXY_DEFINITION": c.proxy_definition,
           "BAKATA_WORKER_DEFINITION": c.worker_definition,
           "BAKATA_PROXY_SUBNET": c.proxy_subnet, "BAKATA_PROXY_SECURITY_GROUP": c.proxy_security_group,
           "BAKATA_WORKER_SUBNET": c.worker_subnet, "BAKATA_WORKER_SECURITY_GROUP": c.worker_security_group}
    env.update(changes)
    return {k: v for k, v in env.items() if v is not None}


@unittest.skipIf(boto3 is None, "boto3/moto not installed")
@unittest.skipIf(TEMPLATE is None, "repository infra/ not available (intelligence image)")
class PairHandlerTests(unittest.TestCase):
    def setUp(self):
        from intelligence import research_pair_handler
        from intelligence.research_pair_dynamo_ledger import DynamoLedger
        from test_research_pair_controller import FakeECS, NOW, UNTIL
        self.module, self.NOW, self.UNTIL = research_pair_handler, NOW, UNTIL
        os.environ.update(AWS_ACCESS_KEY_ID="fixture", AWS_SECRET_ACCESS_KEY="fixture",
                          AWS_SESSION_TOKEN="fixture", AWS_DEFAULT_REGION="us-east-1",
                          AWS_EC2_METADATA_DISABLED="true")
        self.mock = mock_aws()
        self.mock.start()
        self.dynamodb = boto3.client("dynamodb", region_name="us-east-1")
        props = json.loads(TEMPLATE.read_text())["Resources"]["PairLedger"]["Properties"]
        self.dynamodb.create_table(TableName=TABLE, BillingMode="PAY_PER_REQUEST",
                                   AttributeDefinitions=props["AttributeDefinitions"], KeySchema=props["KeySchema"])
        self.authorize = lambda: DynamoLedger.initialize(self.dynamodb, TABLE, {
            "type": "authorize", "run": "fixture-ci", "at": NOW, "until": UNTIL, "nonce": "0" * 32})
        self.ecs, self.now, self.created = FakeECS(), NOW, 0

    def tearDown(self):
        self.mock.stop()

    def clients(self):
        self.created += 1
        return self.dynamodb, self.ecs

    def run_handler(self, event, env):
        return self.module.run(event, env, clients=self.clients, clock=lambda: self.now)

    def test_disabled_by_default_creates_no_clients(self):
        for env in ({}, environment(BAKATA_PAIR_CONTROLLER_ENABLED=None),
                    environment(BAKATA_PAIR_CONTROLLER_ENABLED="True"),
                    environment(BAKATA_PAIR_CONTROLLER_ENABLED="1")):
            with self.subTest(env.get("BAKATA_PAIR_CONTROLLER_ENABLED")):
                self.assertEqual(self.run_handler({"action": "supervise"}, env), {"state": "disabled"})
        self.assertEqual(self.created, 0)

    def test_event_cannot_supply_configuration(self):
        self.authorize()
        bad_events = [None, [], {}, {"action": "stop"}, {"action": "supervise", "cluster": "x"},
                      {"action": "launch"}, {"action": "launch", "role": "admin"},
                      {"action": "launch", "role": "proxy", "subnet": "subnet-" + "f" * 17},
                      {"action": "supervise", "BAKATA_PAIR_NONCE": "1" * 32}]
        for event in bad_events:
            with self.subTest(event), self.assertRaisesRegex(ValueError, "Unsupported invocation"):
                self.run_handler(event, environment(BAKATA_PAIR_LAUNCH_ENABLED="true"))
        self.assertEqual((self.created, self.ecs.calls), (0, []))

    def test_launch_requires_second_opt_in_and_region(self):
        self.authorize()
        with self.assertRaisesRegex(ValueError, "Launch not enabled"):
            self.run_handler({"action": "launch", "role": "proxy"}, environment())
        with self.assertRaisesRegex(ValueError, "region"):
            self.run_handler({"action": "supervise"}, environment(AWS_REGION="us-west-2"))
        with self.assertRaisesRegex(ValueError, "BAKATA_PROXY_SUBNET"):
            self.run_handler({"action": "supervise"}, environment(BAKATA_PROXY_SUBNET=""))
        self.assertEqual((self.created, self.ecs.calls), (0, []))

    def test_never_initializes_ledger(self):
        with self.assertRaisesRegex(ValueError, "Slot does not belong"):
            self.run_handler({"action": "supervise"}, environment())
        self.assertNotIn("Item", self.dynamodb.get_item(TableName=TABLE,
            Key={"pk": {"S": "PAIR#SLOT"}, "sk": {"S": "ACTIVE"}}))
        self.assertEqual(self.ecs.calls, [])

    def test_full_lifecycle_through_handler(self):
        self.authorize()
        env = environment(BAKATA_PAIR_LAUNCH_ENABLED="true")
        proxy = self.run_handler({"action": "launch", "role": "proxy"}, env)
        worker = self.run_handler({"action": "launch", "role": "worker"}, env)
        self.assertEqual((proxy["state"], worker["state"]), ("launched", "launched"))
        self.assertEqual(self.run_handler({"action": "supervise"}, environment())["state"], "running")
        self.now = self.UNTIL
        result = self.run_handler({"action": "supervise"}, environment())  # no launch opt-in needed
        self.assertEqual(sorted(result["requested"]), ["proxy", "worker"])
        for arn in (proxy["task"], worker["task"]):
            self.ecs.tasks[arn]["lastStatus"] = self.ecs.tasks[arn]["desiredStatus"] = "STOPPED"
        self.assertEqual(self.run_handler({"action": "supervise"}, environment()), {"state": "both-stopped"})
        self.assertEqual(self.ecs.count("run"), 2)

    def test_every_ecs_request_is_valid_for_the_real_api_model(self):
        # The fake ECS accepts anything: validate each request against botocore's ECS model.
        from botocore.validate import ParamValidator
        model = boto3.client("ecs", region_name="us-east-1").meta.service_model
        validator, checked, fake = ParamValidator(), [], self.ecs

        class ValidatingECS:
            def __getattr__(self, name):
                method = getattr(fake, name)
                if name not in ("run_task", "describe_tasks", "list_tasks", "stop_task"):
                    return method
                operation = model.operation_model("".join(p.title() for p in name.split("_")))

                def call(**kw):
                    report = validator.validate(kw, operation.input_shape)
                    if report.has_errors():
                        raise AssertionError(report.generate_report())
                    checked.append(operation.name)
                    return method(**kw)
                return call
        self.ecs = ValidatingECS()
        self.authorize()
        env = environment(BAKATA_PAIR_LAUNCH_ENABLED="true")
        fake.run_error = TimeoutError()  # proxy launch uncertain: exercises ListTasks reconciliation
        with self.assertRaises(ValueError):
            self.run_handler({"action": "launch", "role": "proxy"}, env)
        fake.run_error = None
        self.now = self.UNTIL
        self.run_handler({"action": "supervise"}, environment())
        self.assertEqual(sorted(set(checked)), ["DescribeTasks", "ListTasks", "RunTask", "StopTask"])

    def test_lambda_entrypoint_uses_invocation_time(self):
        from unittest import mock
        self.authorize()

        class Context:
            def __init__(self, ms):
                self.ms = ms

            def get_remaining_time_in_millis(self):
                return self.ms
        env = environment(BAKATA_PAIR_LAUNCH_ENABLED="true")
        with mock.patch.dict(os.environ, env, clear=False), \
                mock.patch.object(self.module, "_clients", self.clients), \
                mock.patch.object(self.module.time, "time", return_value=float(self.NOW)):
            with self.assertRaisesRegex(ValueError, "Insufficient invocation time"):
                self.module.handler({"action": "launch", "role": "proxy"}, Context(5_000))
            self.assertEqual(self.ecs.count("run"), 0)
            result = self.module.handler({"action": "launch", "role": "proxy"}, Context(115_000))
        self.assertEqual(result["state"], "launched")
        with mock.patch.dict(os.environ, {"BAKATA_PAIR_CONTROLLER_ENABLED": "false"}):
            self.assertEqual(self.module.handler({"action": "supervise"}, Context(1)), {"state": "disabled"})

    def test_template_environment_matches_handler(self):
        function = json.loads(TEMPLATE.read_text())["Resources"]["ControllerFunction"]["Properties"]
        self.assertEqual(function["Handler"], "intelligence.research_pair_handler.handler")
        self.assertEqual(set(function["Environment"]["Variables"]),
                         set(self.module.ENV.values()) | {"BAKATA_PAIR_CONTROLLER_ENABLED", "BAKATA_PAIR_LAUNCH_ENABLED"})

    def test_production_clients_have_no_retries_or_custom_endpoints(self):
        hostile = {"AWS_ENDPOINT_URL": "http://127.0.0.1:9", "AWS_ENDPOINT_URL_DYNAMODB": "http://127.0.0.1:9",
                   "AWS_ENDPOINT_URL_ECS": "http://127.0.0.1:9"}
        saved = {k: os.environ.get(k) for k in hostile}
        os.environ.update(hostile)
        try:
            # Control: an ordinary client honours the environment override...
            self.assertEqual(boto3.client("dynamodb", region_name="us-east-1").meta.endpoint_url, "http://127.0.0.1:9")
            dynamodb, ecs = self.module._clients()
        finally:
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        # ...the handler's clients ignore it and only talk to the real regional endpoints.
        self.assertEqual(dynamodb.meta.endpoint_url, "https://dynamodb.us-east-1.amazonaws.com")
        self.assertEqual(ecs.meta.endpoint_url, "https://ecs.us-east-1.amazonaws.com")
        for client in (dynamodb, ecs):
            self.assertEqual(client.meta.region_name, "us-east-1")
            self.assertEqual(client.meta.config.retries["total_max_attempts"], 1)  # botocore adds mode
            self.assertEqual((client.meta.config.connect_timeout, client.meta.config.read_timeout), (3, 5))


if __name__ == "__main__":
    unittest.main()
