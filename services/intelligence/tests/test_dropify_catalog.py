import json
import sqlite3
import unittest
from datetime import datetime, timezone
from intelligence.dropify_catalog import DropifyCatalog, decode


class DropifyCatalogTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.archive=DropifyCatalog(self.db)
        self.now=datetime(2026,11,26,22,tzinfo=timezone.utc)
        self.row={"external_id":"96","sku":"025216","title":"Fixture",
                  "display_price":"7.000","suggested_price":"17.000","display_stock":"412",
                  "category":"Otro","warehouse":"Fixture warehouse","store":"fixture-store"}

    def raw(self,rows=None,at="2026-11-26T20:00:00.000Z"):
        return json.dumps({"schema":"bakata-dropify-visible-v1","captured_at":at,
                           "rows":rows if rows is not None else [self.row]}).encode()

    def ingest(self,raw):
        return self.archive.ingest(raw,"fixture-operator",self.now)

    def test_replay_and_latest_history(self):
        raw=self.raw()
        self.assertEqual(self.ingest(raw)["inserted"],1)
        self.assertTrue(self.ingest(raw)["replay"])
        self.ingest(self.raw([dict(self.row,display_price="8.000",display_stock="0")],at="2026-11-26T21:00:00.000Z"))
        rows=self.archive.candidates()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["sku"],"025216")
        self.assertEqual(rows[0]["displayed_spread"],9000)
        self.assertEqual(self.archive.candidates(in_stock=True),[])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM catalog").fetchone()[0],2)
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(),[])

    def test_unknown_and_filters(self):
        other=dict(self.row,external_id="99",title="Other",display_price="",display_stock="—",category="Cocina")
        self.ingest(self.raw([self.row,other]))
        self.assertEqual(len(self.archive.candidates(query="025216",limit=1)),1)
        self.assertEqual(self.archive.candidates(category="Cocina")[0]["display_price"],None)
        self.assertEqual(len(self.archive.candidates(in_stock=True)),1)
        self.assertEqual(self.archive.candidates(limit=1,offset=1)[0]["external_id"],"99")

    def test_conflicting_page_rolls_back(self):
        self.ingest(self.raw())
        with self.assertRaisesRegex(ValueError,"Conflicting"):
            self.ingest(self.raw([dict(self.row,external_id="99"),dict(self.row,display_price="1")]))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM pages").fetchone()[0],1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM catalog").fetchone()[0],1)

    def test_schema_rejects_opaque_and_ambiguous_numbers(self):
        for row in (dict(self.row,token="secret"),dict(self.row,display_price="7,000"),
                    dict(self.row,external_id=""),dict(self.row,display_stock="-1")):
            with self.assertRaises(ValueError):
                self.ingest(self.raw([row]))
        with self.assertRaises(ValueError):
            self.ingest(self.raw([self.row,self.row]))
        with self.assertRaises(ValueError):
            self.ingest(self.raw(at="2026-11-27T20:00:00.000Z"))

    def test_reopen_and_reject_unrelated_database(self):
        DropifyCatalog(self.db)
        with sqlite3.connect(":memory:") as other:
            other.execute("CREATE TABLE unrelated(id INTEGER)")
            with self.assertRaises(ValueError):
                DropifyCatalog(other)
