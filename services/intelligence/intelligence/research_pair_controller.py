"""Offline worker/proxy pair controller over the experimental pair ledger.

Not deployed and disabled by default. It drives an injected ECS-like client and
is only tested with fakes; it proves ordering and fail-closed behaviour, not
AWS permissions, network isolation or durability of the ledger file.

Invariants:
- every side effect is preceded by a CAS-persisted claim; a claim is never
  repeated, so an uncertain RunTask/StopTask needs reconciliation or a human;
- the worker is launched only while the proxy is bound and observed with
  lastStatus RUNNING;
- after the deadline, when either task is observed stopping/stopped, or when a
  role is unverifiable, every verified running task is stopped; a failure in
  one role never prevents stopping the other, and is raised after the attempt;
- STOPPED is observed per role; the slot is never released.

Task "identity" checks bind to non-secret values (config, run, nonce, tags):
they detect mistakes, not a principal that may call ecs:RunTask in the cluster.
"""
from dataclasses import dataclass
import hashlib
import json
import re

from .research_pair_contract import replay
from .research_pair_ledger import Conflict, Ledger

ROLES = ("proxy", "worker")
_CONTAINERS = {"proxy": ("proxy-fixture",), "worker": ("worker", "coordinator")}
_FAMILY = {"proxy": "proxy-fixture", "worker": "persistent-fixture"}
_STARTING = {"PROVISIONING", "PENDING", "ACTIVATING"}
_DRAINING = _STARTING | {"RUNNING", "DEACTIVATING", "STOPPING", "DEPROVISIONING"}
PLATFORM = "1.4.0"
LAUNCH_MARGIN = 30
BIND_GRACE = 120  # a newer unbound claim may be an in-flight launch
BIND_ATTEMPTS = 3


class UnsafeTask(ValueError):
    """Our task (identity verified) running with a configuration we did not request."""

    def __init__(self, role, status, reason):
        super().__init__("Unsafe %s task: %s" % (role, reason))
        self.status = status


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _now(value):
    if type(value) is not int or value < 0:
        raise ValueError("Trusted integer clock required")
    return value


def _dict(value):
    if not isinstance(value, dict):
        raise ValueError("Malformed ECS response")
    return value


def _list(value, limit):
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError("Malformed ECS response")
    return value


@dataclass(frozen=True, slots=True)
class PairConfig:
    cluster: str
    proxy_definition: str
    worker_definition: str
    proxy_subnet: str
    proxy_security_group: str
    worker_subnet: str
    worker_security_group: str

    def __post_init__(self):
        match = (re.fullmatch(r"arn:aws:ecs:us-east-1:([0-9]{12}):cluster/(bakata-research-[A-Za-z0-9_-]{1,80})",
                              self.cluster) if isinstance(self.cluster, str) else None)
        if match is None:
            raise ValueError("Reviewed research cluster required")
        base = f"arn:aws:ecs:us-east-1:{match.group(1)}:task-definition/bakata-research-[A-Za-z0-9_-]{{1,80}}-"
        for role in ROLES:
            definition = getattr(self, role + "_definition")
            if not isinstance(definition, str) or not re.fullmatch(base + _FAMILY[role] + r":[1-9][0-9]*", definition):
                raise ValueError("Reviewed %s fixture definition required" % role)
            subnet, group = getattr(self, role + "_subnet"), getattr(self, role + "_security_group")
            if (not isinstance(subnet, str) or not re.fullmatch(r"subnet-[0-9a-f]{17}", subnet)
                or not isinstance(group, str) or not re.fullmatch(r"sg-[0-9a-f]{17}", group)):
                raise ValueError("Reviewed private fixture network required")
        if self.proxy_security_group == self.worker_security_group:
            # Ingress to the proxy must be expressible as "from the worker SG only".
            raise ValueError("Worker and proxy security groups must differ")

    @property
    def task_prefix(self):
        return self.cluster.replace(":cluster/", ":task/") + "/"

    def definition(self, role):
        return getattr(self, role + "_definition")

    def is_task(self, arn):
        return isinstance(arn, str) and re.fullmatch(re.escape(self.task_prefix) + r"[0-9a-f]{32}", arn) is not None


class PairController:
    def __init__(self, ledger, ecs, config, *, clock, enabled=False):
        if not isinstance(ledger, Ledger) or not isinstance(config, PairConfig) or not callable(clock):
            raise ValueError("Reviewed ledger, configuration and clock required")
        self.ledger, self.ecs, self.config, self.clock = ledger, ecs, config, clock
        self.enabled = enabled is True

    def _require_enabled(self):
        if not self.enabled:
            raise ValueError("Pair controller disabled")

    # -- ledger helpers -------------------------------------------------
    def _state(self):
        revision, events = self.ledger.snapshot()
        return revision, replay(events), events

    def _token(self, state, role):
        c = self.config
        return hashlib.sha256(_encode([c.cluster, c.definition(role), state.run, state.until,
                                       state.nonce, role]).encode()).hexdigest()

    def _group(self, state, role):
        return "bakata-research:%s:%s" % (role, self._token(state, role)[:16])

    def _bind(self, role, arn):
        """Persist a binding. Retrying is safe: the reducer refuses a second bind."""
        for _ in range(BIND_ATTEMPTS):
            revision, state, _events = self._state()
            member = getattr(state, role)
            if member.identity == arn:
                return arn
            if member.identity is not None:
                raise ValueError("Conflicting %s binding; manual reconciliation required" % role)
            try:
                self.ledger.append(revision, {"type": "bind", "role": role,
                                              "at": _now(self.clock()), "identity": arn})
                return arn
            except Conflict:
                continue
        raise ValueError("Binding for %s not persisted; reconcile without retry" % role)

    # -- ECS observation ------------------------------------------------
    def _describe(self, state, role, task_arn):
        """Return running, starting, stopping or stopped; raise if unverifiable."""
        c = self.config
        response = _dict(self.ecs.describe_tasks(cluster=c.cluster, tasks=[task_arn], include=["TAGS"]))
        tasks = _list(response.get("tasks", []), 1)
        if response.get("failures") or len(tasks) != 1:
            raise ValueError("Unverified %s task" % role)
        task = _dict(tasks[0])
        tags = _list(task.get("tags", []), 50)
        if not all(isinstance(t, dict) and isinstance(t.get("key"), str) and isinstance(t.get("value"), str)
                   for t in tags):
            raise ValueError("Malformed ECS response")
        tagmap = {t["key"]: t["value"] for t in tags}
        token = self._token(state, role)
        if (len(tagmap) != len(tags)
            or task.get("taskArn") != task_arn or task.get("clusterArn") != c.cluster
            or task.get("taskDefinitionArn") != c.definition(role)
            or task.get("launchType") != "FARGATE" or task.get("platformVersion") != PLATFORM
            or task.get("enableExecuteCommand") is not False
            or task.get("group") != self._group(state, role)
            or task.get("startedBy") != token[:32]
            or tagmap.get("bakata:purpose") != "research-fixture"
            or tagmap.get("bakata:role") != role
            or tagmap.get("bakata:run") != state.run
            or tagmap.get("bakata:until") != str(state.until)):
            raise ValueError("Unverified %s task" % role)
        last, desired = task.get("lastStatus"), task.get("desiredStatus")
        if last == "STOPPED" and desired == "STOPPED":
            status = "stopped"
        elif desired == "STOPPED" and last in _DRAINING:
            status = "stopping"
        elif desired == "RUNNING" and last == "RUNNING":
            status = "running"
        elif desired == "RUNNING" and last in _STARTING | {"DEACTIVATING"}:
            status = "starting"
        else:
            raise ValueError("Unexpected %s task status" % role)
        # Identity is verified above. IAM cannot constrain RunTask overrides or
        # networking, so verify them here; an unsafe task is still ours to stop.
        overrides = _dict(task.get("overrides", {}))
        if overrides.get("taskRoleArn") or overrides.get("executionRoleArn"):
            raise UnsafeTask(role, status, "role override")
        expected = [{"name": n, "environment": self._environment(state)} for n in _CONTAINERS[role]]
        if set(overrides) - {"containerOverrides"} or overrides.get("containerOverrides") != expected:
            raise UnsafeTask(role, status, "overrides differ from the reviewed request")
        subnets = set()
        for attachment in _list(task.get("attachments", []), 10):
            attachment = _dict(attachment)
            if attachment.get("type") == "ElasticNetworkInterface":
                for detail in _list(attachment.get("details", []), 50):
                    detail = _dict(detail)
                    if detail.get("name") == "subnetId":
                        subnets.add(detail.get("value"))
        # Before an ENI is attached the list may be empty; any present subnet must match.
        if subnets and subnets != {getattr(c, role + "_subnet")}:
            raise UnsafeTask(role, status, "subnet")
        if last == "RUNNING" and not subnets:
            raise UnsafeTask(role, status, "no network attachment")
        return status

    @staticmethod
    def _environment(state):
        return [{"name": "BAKATA_RESEARCH_RUN", "value": state.run},
                {"name": "BAKATA_RESEARCH_UNTIL", "value": str(state.until)}]

    # -- launch ---------------------------------------------------------
    def launch(self, role):
        self._require_enabled()
        if role not in ROLES:
            raise ValueError("Unknown role")
        revision, state, _events = self._state()
        now = _now(self.clock())
        if now + LAUNCH_MARGIN >= state.until:
            raise ValueError("Insufficient time before deadline")
        if role == "worker":
            proxy = state.proxy
            if proxy.identity is None or proxy.stop_claimed or proxy.stopped:
                raise ValueError("Bound live proxy required")
            if self._describe(state, "proxy", proxy.identity) != "running":
                raise ValueError("Proxy not RUNNING")
        # The reducer refuses a second claim for the same role; Conflict means no claim.
        self.ledger.append(revision, {"type": "claim-launch", "role": role, "at": now})
        # A claim is not authority for a late effect: recheck time and peer after persisting it.
        if _now(self.clock()) + LAUNCH_MARGIN >= state.until:
            raise ValueError("Deadline reached after claim; launch abandoned, slot retained")
        if role == "worker":
            _r, latest, _e = self._state()
            if latest.proxy.stop_claimed or latest.proxy.stopped:
                raise ValueError("Proxy stopping after claim; launch abandoned, slot retained")
        c = self.config
        token = self._token(state, role)
        env = self._environment(state)
        try:
            result = _dict(self.ecs.run_task(
                cluster=c.cluster, taskDefinition=c.definition(role), launchType="FARGATE",
                platformVersion=PLATFORM, count=1, clientToken=token, startedBy=token[:32],
                group=self._group(state, role), enableExecuteCommand=False,
                networkConfiguration={"awsvpcConfiguration": {
                    "subnets": [getattr(c, role + "_subnet")],
                    "securityGroups": [getattr(c, role + "_security_group")],
                    "assignPublicIp": "DISABLED"}},
                overrides={"containerOverrides": [{"name": n, "environment": env} for n in _CONTAINERS[role]]},
                tags=[{"key": "bakata:purpose", "value": "research-fixture"},
                      {"key": "bakata:role", "value": role},
                      {"key": "bakata:run", "value": state.run},
                      {"key": "bakata:until", "value": str(state.until)}]))
            tasks = _list(result.get("tasks", []), 1)
            if result.get("failures") or len(tasks) != 1:
                raise ValueError()
            arn = _dict(tasks[0]).get("taskArn")
            if not c.is_task(arn):
                raise ValueError()
        except Exception:
            raise ValueError("Launch not confirmed; reconcile %s without retry" % role) from None
        return self._bind(role, arn)

    def reconcile(self, role):
        """Bind a claimed-but-unbound launch. Never calls RunTask.

        Real ListTasks returns only desiredStatus RUNNING by default: an uncertain
        launch that already stopped cannot be found here and needs a human.
        """
        self._require_enabled()
        _revision, state, _events = self._state()
        member = getattr(state, role)
        if not member.launch_claimed or member.identity is not None:
            raise ValueError("Nothing to reconcile")
        # No match is NOT proof that no task was launched: keep failing closed.
        page = _dict(self.ecs.list_tasks(cluster=self.config.cluster,
                                         startedBy=self._token(state, role)[:32], maxResults=2))
        candidates = _list(page.get("taskArns", []), 2)
        if page.get("nextToken") or len(candidates) != 1 or not self.config.is_task(candidates[0]):
            raise ValueError("Ambiguous or missing %s launch; manual reconciliation required" % role)
        self._describe(state, role, candidates[0])
        return self._bind(role, candidates[0])

    # -- supervision ----------------------------------------------------
    def supervise(self):
        """Tick: never launches, never releases the slot; isolates failures per role."""
        self._require_enabled()
        _revision, state, events = self._state()
        if state.both_stopped:
            return {"state": "both-stopped"}
        now = _now(self.clock())
        expired = now >= state.until
        errors = {}

        def attempt(role, action):
            try:
                return action()
            except Exception as exc:  # recorded and raised after every role was attempted
                errors[role] = "%s: %s" % (type(exc).__name__, exc)
                return None

        claimed_at = {e["role"]: e["at"] for e in events if e.get("type") == "claim-launch"}
        for role in ROLES:
            member = getattr(state, role)
            if member.launch_claimed and member.identity is None:
                # abs(): a claim stamped in the future (clock skew) must not defer reconciliation.
                if not expired and abs(now - claimed_at[role]) < BIND_GRACE:
                    continue  # possibly an in-flight launch by another controller
                attempt(role, lambda role=role: self.reconcile(role))
        _revision, state, _events = self._state()

        observed = {}
        for role in ROLES:
            member = getattr(state, role)
            if member.stopped:
                observed[role] = "stopped"
            elif member.identity is not None:
                try:
                    observed[role] = self._describe(state, role, member.identity)
                except UnsafeTask as exc:
                    # Our task, unsafe configuration: report it AND stop it if still active.
                    errors[role] = "%s: %s" % (type(exc).__name__, exc)
                    observed[role] = exc.status
                except Exception as exc:  # identity unverified: never stop an unknown task
                    errors[role] = "%s: %s" % (type(exc).__name__, exc)

        def record_stopped(role):
            revision, latest, _e = self._state()
            member = getattr(latest, role)
            if not member.stopped:
                self.ledger.append(revision, {"type": "observe-stopped", "role": role,
                                              "at": _now(self.clock()), "identity": member.identity,
                                              "last": "STOPPED", "desired": "STOPPED"})
        for role, status in observed.items():
            if status == "stopped" and not getattr(state, role).stopped:
                attempt(role, lambda role=role: record_stopped(role))
        _revision, state, _events = self._state()
        if state.both_stopped and not errors:
            return {"state": "both-stopped"}

        peer_down = any(status in ("stopped", "stopping") for status in observed.values())
        # A persisted stop claim means someone already decided to end the pair,
        # even if its StopTask never reached ECS (crash between claim and effect).
        stop_decided = any(getattr(state, r).stop_claimed and not getattr(state, r).stopped for r in ROLES)
        # Fail-safe by design: any unverifiable role, including a transient API
        # error, terminates the pair rather than leaving a task unsupervised.
        unverifiable = bool(errors)
        if not (expired or peer_down or stop_decided or unverifiable):
            return {"state": "running", "tasks": observed}

        requested = []

        def stop(role):
            revision, latest, _e = self._state()
            member = getattr(latest, role)
            if member.stop_claimed:
                # A previous invocation may have crashed after claiming. Never repeat StopTask.
                raise ValueError("Uncertain %s stop; manual reconciliation required" % role)
            self.ledger.append(revision, {"type": "claim-stop", "role": role, "at": _now(self.clock())})
            reply = _dict(self.ecs.stop_task(cluster=self.config.cluster, task=member.identity,
                                             reason="Bakata research fixture pair terminated"))
            task = _dict(reply.get("task", {}))
            if task.get("taskArn") != member.identity or task.get("desiredStatus") != "STOPPED":
                raise ValueError("Stop not confirmed for %s" % role)
            requested.append(role)
        for role, status in observed.items():
            if status in ("running", "starting"):
                attempt(role, lambda role=role: stop(role))

        reason = ("deadline" if expired else "peer-down" if peer_down
                  else "stop-claimed" if stop_decided else "unverifiable")
        result = {"state": "stop-requested" if requested else "stopping", "reason": reason,
                  "requested": requested, "tasks": observed}
        if errors:
            raise ValueError("Pair supervision incomplete after stop attempts: %s; result %s"
                             % (_encode(errors), _encode(result)))
        return result
