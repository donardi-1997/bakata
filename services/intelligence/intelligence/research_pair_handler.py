"""Lambda entrypoint for the pair controller. Disabled unless explicitly enabled.

Invoke `launch` synchronously (RequestResponse) only; the function's
EventInvokeConfig disables Lambda's own async retries. Configuration comes only
from the deployment environment. The invocation
event selects an action and nothing else: it can never supply ARNs, subnets,
the ledger table or the authorization nonce. Launching needs a second,
independent opt-in. The handler never initializes or releases the ledger.
"""
import json
import os
import time

from .research_pair_controller import ROLES, PairConfig, PairController
from .research_pair_dynamo_ledger import DynamoLedger

ENV = {
    "table": "BAKATA_PAIR_TABLE",
    "nonce": "BAKATA_PAIR_NONCE",
    "cluster": "BAKATA_CLUSTER",
    "proxy_definition": "BAKATA_PROXY_DEFINITION",
    "worker_definition": "BAKATA_WORKER_DEFINITION",
    "proxy_subnet": "BAKATA_PROXY_SUBNET",
    "proxy_security_group": "BAKATA_PROXY_SECURITY_GROUP",
    "worker_subnet": "BAKATA_WORKER_SUBNET",
    "worker_security_group": "BAKATA_WORKER_SECURITY_GROUP",
}


def _action(event):
    if event == {"action": "supervise"}:
        return "supervise", None
    if (isinstance(event, dict) and set(event) == {"action", "role"} and event["action"] == "launch"
            and event["role"] in ROLES):
        return "launch", event["role"]
    raise ValueError("Unsupported invocation; only supervise or launch of a fixed role")


def _clients():
    import boto3
    from botocore.config import Config
    config = Config(region_name="us-east-1", retries={"total_max_attempts": 1},
                    connect_timeout=3, read_timeout=5, ignore_configured_endpoint_urls=True)
    return boto3.client("dynamodb", config=config), boto3.client("ecs", config=config)


def run(event, environ, *, clients, clock, remaining=None):
    """Testable core; `clients` returns (dynamodb, ecs); `remaining` returns seconds left."""
    if environ.get("BAKATA_PAIR_CONTROLLER_ENABLED") != "true":
        return {"state": "disabled"}
    if environ.get("AWS_REGION") != "us-east-1":
        raise ValueError("Reviewed region required")
    action, role = _action(event)
    if action == "launch" and environ.get("BAKATA_PAIR_LAUNCH_ENABLED") != "true":
        raise ValueError("Launch not enabled for this deployment")
    missing = [name for name in ENV.values() if not environ.get(name)]
    if missing:
        raise ValueError("Missing reviewed configuration: " + ",".join(sorted(missing)))
    config = PairConfig(**{field: environ[name] for field, name in ENV.items()
                           if field not in ("table", "nonce")})
    dynamodb, ecs = clients()
    ledger = DynamoLedger(dynamodb, environ[ENV["table"]], environ[ENV["nonce"]])
    controller = PairController(ledger, ecs, config, clock=clock, enabled=True, remaining=remaining)
    if action == "launch":
        return {"state": "launched", "role": role, "task": controller.launch(role)}
    return controller.supervise()


def handler(event, context):
    # Lambda's own clock: a claim is never persisted without time to perform its effect.
    remaining = lambda: context.get_remaining_time_in_millis() / 1000  # noqa: E731
    result = run(event, os.environ, clients=_clients, clock=lambda: int(time.time()), remaining=remaining)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return result
