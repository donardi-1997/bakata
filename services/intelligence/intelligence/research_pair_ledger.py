"""Offline, single-host SQLite experiment. Never authorizes external effects."""
import json
import os
from pathlib import Path
import sqlite3

from .research_pair_contract import replay


class Conflict(ValueError):
    """The caller's snapshot is stale; no event was appended by this call."""


def _encode(event):
    return json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False)


_SCHEMA = {
    "pair_events": "CREATE TABLE pair_events (revision INTEGER PRIMARY KEY, event TEXT NOT NULL)",
    "pair_no_update": "CREATE TRIGGER pair_no_update BEFORE UPDATE ON pair_events "
                      "BEGIN SELECT RAISE(ABORT, 'append only'); END",
    "pair_no_delete": "CREATE TRIGGER pair_no_delete BEFORE DELETE ON pair_events "
                      "BEGIN SELECT RAISE(ABORT, 'append only'); END",
    "pair_no_replace": "CREATE TRIGGER pair_no_replace BEFORE INSERT ON pair_events "
                       "WHEN EXISTS (SELECT 1 FROM pair_events WHERE revision = NEW.revision) "
                       "BEGIN SELECT RAISE(ABORT, 'append only'); END",
}
_MAX_EVENT_BYTES = 4096


def _path(path):
    path = os.fsdecode(os.fspath(path))
    if not path or path == ":memory:" or path.lower().startswith("file:"):
        raise ValueError("A local database path is required")
    return Path(path).absolute()


def _connect(path):
    # mode=rw never creates a missing database. Do not accept caller-supplied URIs.
    db = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, isolation_level=None, timeout=5)
    db.execute("PRAGMA synchronous=FULL")
    db.execute("PRAGMA recursive_triggers=ON")
    return db


class Ledger:
    """One permanently occupied slot, using a trusted local SQLite database.

    A failed append other than Conflict has an unknown outcome to its caller.
    Reading the ledger afterwards does not confer authority to execute an effect.
    """

    @classmethod
    def initialize(cls, path, authorization):
        """Create a new occupied slot once; never recreate an existing file."""
        path = _path(path)
        raw = _encode(authorization)
        if len(raw.encode("utf-8")) > _MAX_EVENT_BYTES:
            raise ValueError("Event too large")
        replay([json.loads(raw)])
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        # Leave even a failed initialization in place: a human must investigate.
        db = _connect(path)
        try:
            db.execute("BEGIN IMMEDIATE")
            for sql in _SCHEMA.values():
                db.execute(sql)
            db.execute("INSERT INTO pair_events VALUES (1, ?)", (raw,))
            db.execute("COMMIT")
        finally:
            db.close()
        return cls(path)

    def __init__(self, path):
        self.db = _connect(_path(path))
        try:
            self.snapshot()
        except BaseException:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def _read(self):
        schema = self.db.execute(
            "SELECT name, sql FROM sqlite_master WHERE name IN "
            "('pair_events','pair_no_update','pair_no_delete','pair_no_replace') LIMIT 5"
        ).fetchall()
        if dict(schema) != _SCHEMA:
            raise ValueError("Invalid ledger schema")
        metadata = self.db.execute(
            "SELECT revision, typeof(event), length(CAST(event AS BLOB)) "
            "FROM pair_events ORDER BY revision LIMIT 33"
        ).fetchall()
        if (not 1 <= len(metadata) <= 32
            or any(revision != i or kind != "text" or size > _MAX_EVENT_BYTES
                   for i, (revision, kind, size) in enumerate(metadata, 1))):
            raise ValueError("Invalid ledger revisions")
        rows = self.db.execute(
            "SELECT revision, event FROM pair_events ORDER BY revision LIMIT 33"
        ).fetchall()
        events = [json.loads(row[1]) for row in rows]
        if any(_encode(event) != row[1] for event, row in zip(events, rows)):
            raise ValueError("Noncanonical ledger")
        if events:
            replay(events)
        return events

    def snapshot(self):
        self.db.execute("BEGIN")
        try:
            events = self._read()
            self.db.execute("COMMIT")
            return len(events), events
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def append(self, expected_revision, event):
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("Invalid revision")
        # Serialize before locking and validate the exact data that will be stored.
        raw = _encode(event)
        if len(raw.encode("utf-8")) > _MAX_EVENT_BYTES:
            raise ValueError("Event too large")
        event = json.loads(raw)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            events = self._read()
            if len(events) != expected_revision:
                raise Conflict("Stale ledger revision")
            replay(events + [event])
            revision = expected_revision + 1
            self.db.execute("INSERT INTO pair_events VALUES (?, ?)", (revision, raw))
            self.db.execute("COMMIT")
            return revision
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise
