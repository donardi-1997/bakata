"""Synthetic end-to-end export from the actual radar and alert ledger."""
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime,timezone,timedelta
from intelligence.dropify_bridge import BridgeArchive
from intelligence.alert_ledger import AlertLedger,ZERO
from intelligence.alert_dashboard import export

if os.environ.get("BAKATA_CI_FIXTURES")!="1":
    raise SystemExit("CI fixture required")
now=datetime.now(timezone.utc).replace(microsecond=0)
with closing(sqlite3.connect(":memory:")) as db, closing(sqlite3.connect(":memory:")) as ldb:
    bridge=BridgeArchive(db)
    ledger=AlertLedger(ldb,"fixture-dashboard",500)
    row={"external_id":"96","sku":"025216","title":"Fixture <script>unsafe</script>","type":"simple",
         "base_price":"7000.25","suggested_price":"17000","simple_stock":412,"categories":["Cocina"],"warehouse":"Fixture"}
    for hours,item in ((2,row),(1,dict(row,base_price="6300.22",simple_stock=0))):
        raw=json.dumps({"schema":"bakata-dropify-bridge-v1","captured_at":(now-timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "store_id":"7","page":1,"page_size":10,"offset":0,"possible_next":False,"rows":[item],
            "approval_ref":"fixture-"+str(hours),"query_sha256":hashlib.sha256(b"").hexdigest()}).encode()
        bridge.ingest(raw,"fixture",now)
    assert ledger.collect(db,store="7",now=now)["inserted"]==2
    item=next(i for i in ledger.list(store="7")["items"] if i["alert"]["signal"]["code"]=="price-decreased")
    ledger.transition(item["alert"]["signal"]["signal_id"],event_id="fixture-resolve",to="resolved",actor_ref="fixture",
        reason_ref="fixture-ticket",expected_previous_sha256=ZERO,now=now)
    result=export(ldb,archive_ref="fixture-dashboard",threshold=500,store="7",now=now)
    assert json.loads(result)["counts"]=={"open":1,"acknowledged":0,"resolved":1}
    assert ldb.execute("PRAGMA query_only").fetchone()[0]==1
    print(result)
