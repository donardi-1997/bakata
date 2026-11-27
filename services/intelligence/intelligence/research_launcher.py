"""Offline-tested controller contract; no deployed entrypoint or live mode.

The controller's dedicated ledger must not be writable by any ECS task role.
An uncertain launch burns the singleton slot until independently reconciled.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import re

from .research_receipts import timestamp
from .research_watchdog import FixtureTaskBinding


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class FixtureLaunchConfig:
    cluster: str
    definition: str
    subnet: str
    security_group: str
    table: str

    def __post_init__(self):
        # Validate against the same account, region and fixture family as watchdog.
        if not isinstance(self.cluster, str):
            raise ValueError("Reviewed cluster required")
        task = self.cluster.replace(":cluster/", ":task/") + "/" + "0" * 32
        FixtureTaskBinding(self.cluster, task, self.definition, "fixture-validation", 1)
        if (not isinstance(self.subnet, str) or not re.fullmatch(r"subnet-[0-9a-f]{17}", self.subnet)
            or not isinstance(self.security_group, str) or not re.fullmatch(r"sg-[0-9a-f]{17}", self.security_group)
            or not isinstance(self.table, str) or not re.fullmatch(r"bakata-research-[A-Za-z0-9_-]{1,80}-launches", self.table)):
            raise ValueError("Reviewed private fixture resources required")


class FixtureLauncher:
    def __init__(self, ddb, ecs, config, *, enabled=False):
        if not isinstance(config, FixtureLaunchConfig):
            raise ValueError("Reviewed configuration required")
        self.ddb, self.ecs, self.config = ddb, ecs, config
        self.enabled = enabled is True

    def _key(self, sk):
        return {"pk": {"S": "FIXTURE#LAUNCH"}, "sk": {"S": sk}}

    def _put_new(self, sk, record):
        return {"Put": {"TableName": self.config.table,
            "Item": dict(self._key(sk), payload={"S": encode(record)}),
            "ConditionExpression": "attribute_not_exists(pk)"}}

    def launch(self, run, until, *, clock):
        """Only a trusted caller and a trusted UTC clock may invoke this method."""
        if not self.enabled:
            raise ValueError("Fixture launcher disabled")
        now = timestamp(clock())
        timestamp(until)
        c = self.config
        dummy = c.cluster.replace(":cluster/", ":task/") + "/" + "0" * 32
        FixtureTaskBinding(c.cluster, dummy, c.definition, run, until)
        if not now + 60 <= until <= now + 1800:
            raise ValueError("Explicit fixture authorization required")
        token = hashlib.sha256(encode([c.cluster, c.definition, run, until]).encode()).hexdigest()
        pending = {"state": "launch-pending", "run": run, "until": until,
                   "cluster": c.cluster, "definition": c.definition, "token": token}
        sk = "RUN#" + run
        # Both the per-run tombstone and global slot must be absent atomically.
        # Never automatically release the slot or retry on ambiguous results.
        try:
            self.ddb.transact_write_items(TransactItems=[
                self._put_new("ACTIVE", pending), self._put_new(sk, pending)])
            if timestamp(clock()) >= until - 30:
                raise ValueError("Insufficient time")
            env = [{"name": "BAKATA_RESEARCH_RUN", "value": run},
                   {"name": "BAKATA_RESEARCH_UNTIL", "value": str(until)}]
            tags = [{"key": "bakata:purpose", "value": "research-fixture"},
                    {"key": "bakata:run", "value": run},
                    {"key": "bakata:until", "value": str(until)}]
            result = self.ecs.run_task(cluster=c.cluster, taskDefinition=c.definition,
                launchType="FARGATE", count=1, clientToken=token, startedBy=token[:32],
                enableExecuteCommand=False,
                networkConfiguration={"awsvpcConfiguration": {
                    "subnets": [c.subnet], "securityGroups": [c.security_group],
                    "assignPublicIp": "DISABLED"}},
                overrides={"containerOverrides": [
                    {"name": name, "environment": env} for name in ("worker", "coordinator")]},
                tags=tags)
            if result.get("failures") or len(result.get("tasks", [])) != 1:
                raise ValueError("Uncertain launch")
            task = result["tasks"][0]
            binding = FixtureTaskBinding(c.cluster, task["taskArn"], c.definition, run, until)
            if (task.get("clusterArn") != c.cluster or task.get("taskDefinitionArn") != c.definition
                or task.get("launchType") != "FARGATE"):
                raise ValueError("Unexpected task identity")
            bound = dict(pending, state="bound", binding=asdict(binding))
            # Save even if expiry passed while RunTask was in flight.
            # The watchdog must independently confirm task identity and expiry.
            self.ddb.transact_write_items(TransactItems=[
                {"Put": {"TableName": c.table,
                         "Item": dict(self._key(key), payload={"S": encode(bound)}),
                         "ConditionExpression": "payload = :old",
                         "ExpressionAttributeValues": {":old": {"S": encode(pending)}}}}
                for key in ("ACTIVE", sk)])
            return binding
        except Exception:
            raise ValueError("Fixture launch not confirmed; reconcile durable slot without retry") from None

    def binding(self, run):
        """Only the trusted controller/watchdog reads this separate ledger."""
        if not isinstance(run, str) or not re.fullmatch(r"fixture-[A-Za-z0-9_-]{1,56}", run):
            raise ValueError("Invalid fixture run")
        def read(sk):
            item = self.ddb.get_item(TableName=self.config.table, Key=self._key(sk),
                                     ConsistentRead=True).get("Item")
            if not item:
                raise ValueError("No trusted task binding")
            raw = item["payload"]["S"]
            data = json.loads(raw)
            if encode(data) != raw:
                raise ValueError("Invalid binding encoding")
            return data
        active, record = read("ACTIVE"), read("RUN#" + run)
        if active != record or record.get("state") != "bound":
            raise ValueError("No trusted task binding")
        binding = FixtureTaskBinding(**record["binding"])
        if (binding.run != run or binding.cluster != self.config.cluster
            or binding.definition != self.config.definition
            or record.get("run") != run or record.get("until") != binding.until):
            raise ValueError("Binding scope mismatch")
        return binding
