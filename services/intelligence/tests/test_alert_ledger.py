import hashlib
import json
import sqlite3
import unittest
from datetime import datetime,timedelta,timezone
from intelligence.dropify_bridge import BridgeArchive
from intelligence.alert_ledger import AlertLedger,ZERO


class AlertLedgerTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.ledger_db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.addCleanup(self.ledger_db.close)
        self.archive=BridgeArchive(self.db)
        self.ledger=AlertLedger(self.ledger_db,"fixture-radar",500)
        self.now=datetime(2026,11,26,20,tzinfo=timezone.utc)
        self.row={"external_id":"96","sku":"025216","title":"Fixture","type":"simple",
            "base_price":"7000.25","suggested_price":"17000","simple_stock":412,
            "categories":["Cocina"],"warehouse":"Fixture"}
        self.ingest(2,self.row)
        self.ingest(1,dict(self.row,base_price="6300.22",simple_stock=0))

    def ingest(self,hours,row,store="7",approval="fixture"):
        at=self.now-timedelta(hours=hours)
        raw=json.dumps({"schema":"bakata-dropify-bridge-v1","captured_at":at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "store_id":store,"page":1,"page_size":10,"offset":0,"possible_next":False,
            "approval_ref":approval,"query_sha256":hashlib.sha256(b"").hexdigest(),"rows":[row]}).encode()
        self.archive.ingest(raw,"fixture-operator",self.now)

    def collect(self,**kw):
        args=dict(store="7",now=self.now)
        args.update(kw)
        return self.ledger.collect(self.db,**args)

    def items(self,**kw):
        return self.ledger.list(store="7",**kw)["items"]

    def alert_id(self):
        return self.items()[0]["alert"]["signal"]["signal_id"]

    def change(self,sid,to,prev=ZERO,event="e1"):
        return self.ledger.transition(sid,event_id=event,to=to,actor_ref="reviewer",
            reason_ref="ticket",expected_previous_sha256=prev,now=self.now)

    def test_dedup_and_resolution_preserved(self):
        self.assertEqual(self.collect()["inserted"],2)
        sid=self.alert_id()
        self.change(sid,"resolved")
        self.assertEqual(self.collect()["replayed"],2)
        self.assertEqual(self.ledger.history(sid)["state"],"resolved")
        self.assertEqual(len(self.items(state="resolved")),1)
        self.assertEqual(len(self.items(state="open")),1)
        self.assertEqual(self.db.execute("PRAGMA query_only").fetchone()[0],1)

    def test_transitions_and_conflict(self):
        self.collect()
        sid=self.alert_id()
        a=self.change(sid,"acknowledged")
        with self.assertRaisesRegex(ValueError,"state changed"):
            self.change(sid,"resolved",event="e2")
        b=self.change(sid,"resolved",a["sha256"],"e2")
        c=self.change(sid,"open",b["sha256"],"e3")
        self.assertEqual(c["previous_sha256"],b["sha256"])
        self.assertEqual(self.ledger.history(sid)["state"],"open")
        with self.assertRaises(ValueError):
            self.change(sid,"open",c["sha256"],"e4")
        with self.assertRaisesRegex(ValueError,"already used"):
            self.change(sid,"resolved",c["sha256"],"e1")

    def test_scope_and_immutability(self):
        self.collect()
        for scope,threshold in (("other",500),("fixture-radar",600)):
            with self.assertRaises(ValueError):
                AlertLedger(self.ledger_db,scope,threshold)
        with self.assertRaises(sqlite3.IntegrityError):
            self.ledger_db.execute("DELETE FROM alerts")
        self.ledger_db.rollback()
        self.change(self.alert_id(),"resolved")
        with self.assertRaises(sqlite3.IntegrityError):
            self.ledger_db.execute("UPDATE events SET payload='{}'")
        self.ledger_db.rollback()

    def test_listing_and_store(self):
        self.ingest(1,self.row,store="8")
        self.collect()
        self.collect(store="8")
        a=self.ledger.list(store="7",limit=1)
        b=self.ledger.list(store="7",limit=1,after=a["next_after"])
        self.assertIsNone(b["next_after"])
        self.assertEqual(len(a["items"]+b["items"]),2)
        self.assertEqual(len(self.ledger.list(store="8")["items"]),1)
        self.assertEqual(self.ledger.list(store="7",state="resolved",limit=1)["items"],[])

    def test_additional_provenance_does_not_overwrite(self):
        self.collect()
        original=self.ledger.history(self.alert_id())
        # Allow fixture setup only; actual collect never writes source archive.
        self.db.execute("PRAGMA query_only=OFF")
        self.ingest(1,dict(self.row,base_price="6300.22",simple_stock=0),approval="another-fixture")
        self.assertEqual(self.collect()["replayed"],2)
        self.assertEqual(self.ledger.history(self.alert_id()),original)

    def test_conflicting_core_aborts_batch(self):
        self.collect()
        self.db.execute("PRAGMA query_only=OFF")
        at=(self.now-timedelta(hours=1)).isoformat()
        payload=json.loads(self.db.execute("SELECT payload FROM observations WHERE at=?",(at,)).fetchone()[0])
        payload["base_price"]="5000"
        self.db.execute("UPDATE observations SET payload=? WHERE at=?",(json.dumps(payload),at))
        self.db.commit()
        with self.assertRaisesRegex(ValueError,"Conflicting signal"):
            self.collect()
        self.assertEqual(len(self.items()),2)
