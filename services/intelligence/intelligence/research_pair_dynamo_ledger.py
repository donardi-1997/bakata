"""DynamoDB pair ledger: same contract as the SQLite Ledger, for the AWS controller.

Layout (single table from infra/research-aws/pair-controller.json):
- pk "PAIR#SLOT", sk "ACTIVE": occupies the table's single slot forever;
- pk "PAIR#<nonce>", sk "REV#0001".."REV#0032": one canonical JSON event each,
  plus a random per-call writer token (revisions after the first).

Every write is conditional (attribute_not_exists), so two controllers cannot
append the same revision. Only the controller role may write (resource policy).
Tested with Moto only: not proof of IAM, consistency or durability in AWS.
"""
import json
import re
import secrets

from .research_pair_contract import replay
from .research_pair_ledger import Conflict

SLOT = {"pk": {"S": "PAIR#SLOT"}, "sk": {"S": "ACTIVE"}}
MAX_EVENTS = 32
MAX_EVENT_BYTES = 4096


class SlotOccupied(ValueError):
    """The table already holds a pair; it is never reused or recreated."""


def _encode(event):
    return json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sk(revision):
    return "REV#%04d" % revision


def _error_code(exc):
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return None
    return response.get("Error", {}).get("Code")


def _table(name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{3,255}", name):
        raise ValueError("Reviewed table name required")
    return name


class DynamoLedger:
    """Use a client built with retries disabled (total_max_attempts=1) and no
    custom endpoint; any failure other than Conflict has an unknown outcome."""

    @classmethod
    def initialize(cls, client, table, authorization):
        raw = _encode(authorization)
        if len(raw.encode("utf-8")) > MAX_EVENT_BYTES:
            raise ValueError("Event too large")
        state = replay([json.loads(raw)])
        pair = "PAIR#" + state.nonce
        first = {"pk": {"S": pair}, "sk": {"S": _sk(1)}}
        try:
            client.transact_write_items(TransactItems=[
                {"Put": {"TableName": _table(table),
                         "Item": dict(SLOT, pair={"S": pair}),
                         "ConditionExpression": "attribute_not_exists(pk)"}},
                {"Put": {"TableName": table,
                         "Item": dict(first, event={"S": raw}),
                         "ConditionExpression": "attribute_not_exists(pk)"}}])
        except Exception as exc:
            if _error_code(exc) != "TransactionCanceledException":
                raise  # unknown outcome
            reasons = [r.get("Code") for r in exc.response.get("CancellationReasons", []) if isinstance(r, dict)]
            if "ConditionalCheckFailed" not in reasons:
                raise  # throttling or transaction conflict: nothing written, outcome to re-check
            # Distinguish a lost response for this same authorization from a real occupant.
            slot = client.get_item(TableName=table, Key=SLOT, ConsistentRead=True).get("Item")
            stored = client.get_item(TableName=table, Key=first, ConsistentRead=True).get("Item")
            # Same ownership criterion as __init__; the stored authorization must match exactly.
            if slot and slot.get("pair") == {"S": pair} and stored == dict(first, event={"S": raw}):
                return cls(client, table, state.nonce)
            raise SlotOccupied("Pair slot already occupied; never recreated") from None
        return cls(client, table, state.nonce)

    def __init__(self, client, table, nonce):
        if not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{32}", nonce):
            raise ValueError("Authorization nonce required")
        self.client, self.table, self.pair = client, _table(table), "PAIR#" + nonce
        slot = client.get_item(TableName=self.table, Key=SLOT, ConsistentRead=True).get("Item")
        if not slot or slot.get("pair") != {"S": self.pair}:
            raise ValueError("Slot does not belong to this pair")
        self.snapshot()

    def close(self):
        """Nothing to release; present for interface parity with Ledger."""

    def _read(self):
        page = self.client.query(
            TableName=self.table, ConsistentRead=True, Limit=MAX_EVENTS + 1,
            KeyConditionExpression="pk = :pk", ExpressionAttributeValues={":pk": {"S": self.pair}})
        items = page.get("Items", [])
        if page.get("LastEvaluatedKey") or not 1 <= len(items) <= MAX_EVENTS:
            raise ValueError("Invalid ledger revisions")
        events = []
        for revision, item in enumerate(items, 1):
            # The first event is written by initialize() without a writer token.
            expected = {"pk", "sk", "event"} if revision == 1 else {"pk", "sk", "event", "writer"}
            if (set(item) != expected or item["sk"] != {"S": _sk(revision)}
                or (revision > 1 and not re.fullmatch(r"[0-9a-f]{32}", item["writer"].get("S", "")))):
                raise ValueError("Invalid ledger revisions")
            raw = item["event"].get("S")
            if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_EVENT_BYTES:
                raise ValueError("Invalid ledger event")
            event = json.loads(raw)
            if _encode(event) != raw:
                raise ValueError("Noncanonical ledger")
            events.append(event)
        replay(events)
        return events

    def snapshot(self):
        events = self._read()
        return len(events), events

    def append(self, expected_revision, event):
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("Invalid revision")
        raw = _encode(event)
        if len(raw.encode("utf-8")) > MAX_EVENT_BYTES:
            raise ValueError("Event too large")
        event = json.loads(raw)
        events = self._read()
        if len(events) != expected_revision:
            raise Conflict("Stale ledger revision")
        replay(events + [event])
        revision = expected_revision + 1
        key = {"pk": {"S": self.pair}, "sk": {"S": _sk(revision)}}
        # Unique per call: identical events from two controllers must still conflict.
        writer = secrets.token_hex(16)
        try:
            self.client.put_item(TableName=self.table,
                                 Item=dict(key, event={"S": raw}, writer={"S": writer}),
                                 ConditionExpression="attribute_not_exists(pk)")
        except Exception as exc:
            if _error_code(exc) != "ConditionalCheckFailedException":
                # Unknown outcome: the caller must reconcile, never assume. The token is
                # attached so a reconciler can tell its own write from an identical one.
                exc.bakata_writer = writer
                raise
            # A transport-level retry of this very request also fails the
            # condition; only this call's writer token proves the write is ours.
            try:
                stored = self.client.get_item(TableName=self.table, Key=key, ConsistentRead=True).get("Item")
            except Exception as read_error:
                read_error.bakata_writer = writer
                raise
            if stored and stored.get("writer") == {"S": writer} and stored.get("event") == {"S": raw}:
                return revision
            raise Conflict("Stale ledger revision") from None
        return revision
