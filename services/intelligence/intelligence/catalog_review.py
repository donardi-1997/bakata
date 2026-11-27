"""Read-only export of one archived catalog page for the administrator review desk."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3

from .dropify_bridge import APP_ID, decode
from .dropify_catalog import MAX_BYTES, unique
from .storage import instant, ref


def export_page(db, sha, *, now):
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("Select an exact archived page SHA-256")
    if db.in_transaction:
        raise ValueError("Independent read connection required")
    db.execute("PRAGMA query_only=ON")
    db.execute("BEGIN")
    try:
        if db.execute("PRAGMA application_id").fetchone()[0] != APP_ID or db.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise ValueError("Unexpected archive schema")
        page = db.execute("SELECT store,at,page,size,operator,rows,approval_ref,query_sha256 FROM pages WHERE sha=?", (sha,)).fetchone()
        if page is None:
            raise ValueError("Unknown archived page")
        store, at, number, size, operator, count, approval, query = page
        if type(count) is not int or not 0 <= count <= 20:
            raise ValueError("Invalid archived count")
        records = db.execute("""SELECT p.store,p.id,p.at,o.payload FROM page_rows p
            JOIN observations o ON (p.store,p.id,p.at)=(o.store,o.id,o.at)
            WHERE p.sha=? ORDER BY p.id LIMIT 21""", (sha,)).fetchall()
        if len(records) != count:
            raise ValueError("Incomplete archived page")
        rows = []
        for row_store, row_id, row_at, payload in records:
            item = json.loads(payload, object_pairs_hook=unique)
            if (row_store,row_at) != (store,at) or item.get("external_id") != row_id:
                raise ValueError("Conflicting page provenance")
            rows.append(item)
        captured = instant(datetime.fromisoformat(at))
        if captured.microsecond != 0:
            raise ValueError("Unexpected capture precision")
        snapshot = {"schema":"bakata-dropify-bridge-v1",
            "captured_at":captured.strftime("%Y-%m-%dT%H:%M:%SZ"), "store_id":store,
            "page":number, "page_size":size, "offset":(number-1)*size,
            "possible_next":count==size, "rows":rows, "approval_ref":approval, "query_sha256":query}
        decode(json.dumps(snapshot,ensure_ascii=False).encode(), now)
        output = {"schema":"bakata-catalog-review-v1", "source":"dropify-bridge-archive",
            "source_page_sha256":sha, "operator_ref":ref(operator), "snapshot":snapshot}
        # PHP checks the same compact JSON representation, including no duplicate keys.
        raw = json.dumps(output,ensure_ascii=False,separators=(",",":"),sort_keys=True).encode("utf-8")
        if len(raw)>MAX_BYTES:
            raise ValueError("Export too large")
        return raw
    finally:
        db.rollback()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db",required=True,type=Path)
    parser.add_argument("--page-sha256",required=True)
    args=parser.parse_args()
    if not args.db.is_file():
        parser.error("An existing archive is required")
    with closing(sqlite3.connect(args.db.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as db:
        print(export_page(db,args.page_sha256,now=datetime.now(timezone.utc)).decode("utf-8"))


if __name__=="__main__":
    main()
