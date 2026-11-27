"""Pure offline fixture model, not an ECS controller or authorization mechanism."""
from dataclasses import dataclass, replace
import re


@dataclass(frozen=True)
class Member:
    launch_claimed: bool = False
    identity: str | None = None
    stop_claimed: bool = False
    stopped: bool = False


@dataclass(frozen=True)
class Pair:
    run: str
    until: int
    at: int
    proxy: Member = Member()
    worker: Member = Member()

    @property
    def both_stopped(self):
        return self.proxy.stopped and self.worker.stopped


def _time(value):
    if type(value) is not int or value < 0:
        raise ValueError("Invalid time")
    return value


def replay(events):
    """Validate a complete, ordered ledger; no actions or external verification.

    A caller must atomically persist each event before any corresponding side
    effect. This function does not implement persistence or grant permission.
    """
    if not isinstance(events, (list, tuple)) or not 1 <= len(events) <= 32:
        raise ValueError("Bounded authorization ledger required")
    state = None
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("Invalid event")
        kind = event.get("type")
        if state is None:
            if (set(event) != {"type", "run", "at", "until"} or kind != "authorize"
                or not isinstance(event["run"], str)
                or not re.fullmatch(r"fixture-[A-Za-z0-9_-]{1,56}", event["run"])):
                raise ValueError("Invalid authorization")
            at, until = _time(event["at"]), _time(event["until"])
            if not at + 60 <= until <= at + 1800:
                raise ValueError("Invalid deadline")
            state = Pair(event["run"], until, at)
            continue
        schemas = {
            "claim-launch": {"type", "role", "at"},
            "bind": {"type", "role", "at", "identity"},
            "claim-stop": {"type", "role", "at"},
            "observe-stopped": {"type", "role", "at", "identity", "last", "desired"},
        }
        if (not isinstance(kind, str) or kind not in schemas
            or set(event) != schemas[kind]
            or not isinstance(event["role"], str)
            or event["role"] not in ("proxy", "worker")):
            raise ValueError("Invalid event schema")
        at = _time(event["at"])
        if at < state.at:
            raise ValueError("Nonmonotonic ledger")
        role = event["role"]
        member = getattr(state, role)
        if kind == "claim-launch":
            if (member.launch_claimed or at >= state.until
                or (role == "worker" and (state.proxy.identity is None
                                          or state.proxy.stop_claimed or state.proxy.stopped))):
                raise ValueError("Launch not claimable")
            member = replace(member, launch_claimed=True)
        elif kind == "bind":
            identity = event["identity"]
            other = state.worker if role == "proxy" else state.proxy
            if (not member.launch_claimed or member.identity is not None
                or not isinstance(identity, str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:/_-]{0,255}", identity)
                or identity == other.identity):
                raise ValueError("Invalid binding")
            member = replace(member, identity=identity)
        elif kind == "claim-stop":
            if member.identity is None or member.stop_claimed or member.stopped:
                raise ValueError("Stop not claimable")
            member = replace(member, stop_claimed=True)
        else:
            if (member.identity is None or member.stopped
                or event["identity"] != member.identity
                or event["last"] != "STOPPED" or event["desired"] != "STOPPED"):
                raise ValueError("Stopped not confirmed")
            member = replace(member, stopped=True)
        state = replace(state, at=at, **{role: member})
    return state
