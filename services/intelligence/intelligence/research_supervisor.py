"""Independent expiry supervisor. No launch, secret access or slot release."""
from dataclasses import asdict
import hashlib
import json
import os
import re
import time

from .research_launcher import encode
from .research_receipts import timestamp
from .research_watchdog import FixtureTaskBinding


def supervise(ddb, ecs, *, table, cluster, definition, now):
    timestamp(now)
    if not isinstance(table, str) or not re.fullmatch(r"bakata-research-[A-Za-z0-9_-]{1,80}-launches", table):
        raise ValueError("Reviewed launch table required")
    if not isinstance(cluster, str):
        raise ValueError("Reviewed cluster required")
    dummy = cluster.replace(":cluster/", ":task/") + "/" + "0" * 32
    FixtureTaskBinding(cluster, dummy, definition, "fixture-validation", 1)

    def key(sk):
        return {"pk": {"S": "FIXTURE#LAUNCH"}, "sk": {"S": sk}}

    def read(sk):
        item = ddb.get_item(TableName=table, Key=key(sk), ConsistentRead=True).get("Item")
        if not item:
            return None
        raw = item["payload"]["S"]
        if len(raw) > 8192:
            raise ValueError()
        data = json.loads(raw)
        if not isinstance(data, dict) or encode(data) != raw:
            raise ValueError()
        return data

    def replace(old, new):
        ddb.transact_write_items(TransactItems=[
            {"Put": {"TableName": table,
                     "Item": dict(key(sk), payload={"S": encode(new)}),
                     "ConditionExpression": "payload = :old",
                     "ExpressionAttributeValues": {":old": {"S": encode(old)}}}}
            for sk in ("ACTIVE", "RUN#" + old["run"])])

    def inspect(binding, marker):
        response = ecs.describe_tasks(cluster=cluster, tasks=[binding.task], include=["TAGS"])
        if response.get("failures") or len(response.get("tasks", [])) != 1:
            raise ValueError()
        task = response["tasks"][0]
        tags = task.get("tags", [])
        if not isinstance(tags, list) or len(tags) > 50:
            raise ValueError()
        tagmap = {entry["key"]: entry["value"] for entry in tags}
        if (len(tagmap) != len(tags)
            or task.get("taskArn") != binding.task or task.get("clusterArn") != cluster
            or task.get("taskDefinitionArn") != definition or task.get("launchType") != "FARGATE"
            or task.get("startedBy") != marker
            or tagmap.get("bakata:purpose") != "research-fixture"
            or tagmap.get("bakata:run") != binding.run
            or tagmap.get("bakata:until") != str(binding.until)):
            raise ValueError()
        last, desired = task.get("lastStatus"), task.get("desiredStatus")
        if last == "STOPPED" and desired == "STOPPED":
            return "stopped"
        if desired == "STOPPED" and last in {"PROVISIONING","PENDING","ACTIVATING","RUNNING","DEACTIVATING","STOPPING","DEPROVISIONING"}:
            return "stopping"
        if desired == "RUNNING" and last in {"PROVISIONING","PENDING","ACTIVATING","RUNNING","DEACTIVATING"}:
            return "running"
        raise ValueError()

    try:
        record = read("ACTIVE")
        if record is None:
            return "idle"
        run, until = record["run"], record["until"]
        FixtureTaskBinding(cluster, dummy, definition, run, until)
        token = hashlib.sha256(encode([cluster, definition, run, until]).encode()).hexdigest()
        base = {"state": record["state"], "run": run, "until": until,
                "cluster": cluster, "definition": definition, "token": token}
        state = record["state"]
        if state == "bound":
            binding = FixtureTaskBinding(**record["binding"])
            if (binding.cluster, binding.definition, binding.run, binding.until) != (cluster, definition, run, until):
                raise ValueError()
            base["binding"] = asdict(binding)
            for field in ("stop_claimed_at", "observed_stopped_at"):
                if field in record:
                    value = timestamp(record[field])
                    if not until <= value <= now:
                        raise ValueError()
                    base[field] = value
        elif state != "launch-pending":
            raise ValueError()
        if record != base or read("RUN#" + run) != record:
            raise ValueError()
        if now < until:
            return "before-deadline"
        if "observed_stopped_at" in record:
            return "stopped"
        marker = token[:32]
        if state == "launch-pending":
            # ECS is eventually consistent. No match is NOT proof of no launch.
            # Refuse pagination or multiple candidates; keep the slot blocked.
            page = ecs.list_tasks(cluster=cluster, startedBy=marker, maxResults=2)
            candidates = page.get("taskArns", [])
            if page.get("nextToken") or not isinstance(candidates, list) or len(candidates) != 1:
                raise ValueError()
            binding = FixtureTaskBinding(cluster, candidates[0], definition, run, until)
            observed = inspect(binding, marker)
            bound = dict(record, state="bound", binding=asdict(binding))
            replace(record, bound)
            record = bound
        else:
            observed = inspect(binding, marker)
        if observed == "stopped":
            replace(record, dict(record, observed_stopped_at=now))
            return "stopped"
        if observed == "stopping":
            return "stopping"
        if "stop_claimed_at" in record:
            # An earlier invocation may have crashed after its claim. Never
            # repeat StopTask automatically; surface failure for manual review.
            raise ValueError()
        claimed = dict(record, stop_claimed_at=now)
        replace(record, claimed)
        reply = ecs.stop_task(cluster=cluster, task=binding.task,
                             reason="Bakata research fixture deadline exceeded")
        if reply.get("task", {}).get("taskArn") != binding.task or reply["task"].get("desiredStatus") != "STOPPED":
            raise ValueError()
        return "stop-requested"
    except Exception:
        raise ValueError("Fixture expiry state unverified; slot retained; reconcile manually") from None


def handler(event, context):
    """Deployment configuration only. The invocation cannot supply task IDs."""
    if os.environ.get("BAKATA_WATCHDOG_ENABLED") != "true":
        return {"state": "disabled"}
    if os.environ.get("AWS_REGION") != "us-east-1":
        raise ValueError("Reviewed region required")
    import boto3
    from botocore.config import Config
    config = Config(retries={"total_max_attempts": 1}, connect_timeout=3, read_timeout=5,
                    ignore_configured_endpoint_urls=True)
    state = supervise(boto3.client("dynamodb", config=config), boto3.client("ecs", config=config),
        table=os.environ["BAKATA_LAUNCH_TABLE"], cluster=os.environ["BAKATA_CLUSTER"],
        definition=os.environ["BAKATA_TASK_DEFINITION"], now=int(time.time()))
    print(json.dumps({"state": state}, separators=(",", ":")))
    return {"state": state}
