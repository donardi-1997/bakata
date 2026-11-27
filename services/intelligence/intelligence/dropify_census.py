"""Audit a contiguous catalog traversal across individually authorized capture windows."""
import argparse
from contextlib import closing
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from .dropify_bridge import APP_ID, MAX_CATALOG_PAGE, decode
from .dropify_capture import approval, policy, read_record
from .dropify_catalog import MAX_BYTES, unique
from .storage import encode, instant

MAX_WINDOWS=MAX_CATALOG_PAGE


def audit(db,windows,*,now):
    """No provider calls. Validate raw pages against the durable bridge archive.

    A partial/empty terminal page is an observed endpoint, not proof of coverage.
    """
    now=instant(now)
    if not 1<=len(windows)<=MAX_WINDOWS or db.in_transaction:
        raise ValueError("Explicit ordered capture windows required")
    db.execute("PRAGMA query_only=ON")
    db.execute("BEGIN")
    try:
        if (db.execute("PRAGMA application_id").fetchone()[0],db.execute("PRAGMA user_version").fetchone()[0])!=(APP_ID,1):
            raise ValueError("Unexpected bridge archive")
        expected=1
        store=binding=None
        last_at=None
        last_id=0
        seen_runs=set()
        seen=set()
        pages=stock_positive=stock_zero=stock_unknown=0
        terminal=False
        for directory in windows:
            directory=Path(directory)
            if directory.is_symlink() or not directory.is_dir() or terminal:
                raise ValueError("Unexpected window after terminal page or invalid directory")
            raw_plan=read_record(directory/"run.json",8192)
            p=json.loads(raw_plan,object_pairs_hook=unique)
            if p!=policy(p["run"],p["store"],p["first"],p["last"],p["until"],p["operator"],p["source_ref"]):
                raise ValueError("Invalid window manifest")
            if store is None:
                store,binding=p["store"],p["source_ref"]
            if p["store"]!=store or p["source_ref"]!=binding or p["first"]!=expected or p["run"] in seen_runs:
                raise ValueError("Window scope or continuity mismatch")
            seen_runs.add(p["run"])
            for page in range(p["first"],p["last"]+1):
                path=directory/f"page-{page:03d}.json"
                marker=directory/f"attempt-{page:03d}.json"
                if not path.exists():
                    if marker.exists():
                        raise ValueError("Uncertain capture attempt")
                    if any((directory/f"page-{n:03d}.json").exists() or (directory/f"attempt-{n:03d}.json").exists() for n in range(page+1,p["last"]+1)):
                        raise ValueError("Gap in window")
                    break
                if terminal:
                    raise ValueError("Page after terminal response")
                raw=read_record(path,MAX_BYTES)
                attempt=json.loads(read_record(marker,8192),object_pairs_hook=unique)
                at,data=decode(raw,now)
                captured=datetime.fromisoformat(at)
                if (set(attempt)!={"run","page","at"} or attempt["run"]!=p["run"] or attempt["page"]!=page
                    or type(attempt["at"]) is not int or not attempt["at"]<=captured.timestamp()<p["until"]
                    or captured>now or (last_at is not None and captured<=last_at)):
                    raise ValueError("Invalid capture chronology")
                if (data["store_id"],data["page"],data["page_size"],data["approval_ref"],data["query_sha256"])!=(store,page,10,approval(p["run"],page),hashlib.sha256(b"").hexdigest()):
                    raise ValueError("Page scope mismatch")
                sha=hashlib.sha256(raw).hexdigest()
                archived=db.execute("SELECT store,at,page,size,operator,rows,approval_ref,query_sha256 FROM pages WHERE sha=?",(sha,)).fetchone()
                if archived!=(store,at,page,10,p["operator"],len(data["rows"]),data["approval_ref"],data["query_sha256"]):
                    raise ValueError("Page not archived; recover capture first")
                records=db.execute("""SELECT r.id,o.payload FROM page_rows r JOIN observations o
                    ON (r.store,r.id,r.at)=(o.store,o.id,o.at) WHERE r.sha=? AND r.store=? AND r.at=?""",(sha,store,at)).fetchall()
                if dict(records)!={r["external_id"]:encode(r) for r in data["rows"]}:
                    raise ValueError("Archived observations differ")
                for row in data["rows"]:
                    eid=int(row["external_id"])
                    if eid<=last_id or eid in seen:
                        raise ValueError("Cross-window duplicate or non-increasing ID")
                    seen.add(eid)
                    last_id=eid
                    stock=row["simple_stock"]
                    if stock is None: stock_unknown+=1
                    elif stock==0: stock_zero+=1
                    else: stock_positive+=1
                last_at=captured
                expected=page+1
                pages+=1
                terminal=not data["possible_next"]
            # Incomplete window may resume, but cannot be bypassed with another authorization.
            if not terminal and expected<=p["last"] and directory!=Path(windows[-1]):
                raise ValueError("Incomplete non-final window")
        state="terminal-page-observed" if terminal else "page-ceiling-reached" if expected>MAX_CATALOG_PAGE else "incomplete"
        return {"schema":"bakata-dropify-census-v1","store_id":store,"state":state,
                "pages_archived":pages,"unique_products_observed":len(seen),
                "stock_reported_positive":stock_positive,"stock_reported_zero":stock_zero,"stock_unknown":stock_unknown,
                "next_page":expected if state=="incomplete" else None,"last_captured_at":last_at.isoformat() if last_at else None,
                "coverage_verified":False,"provider_total_verified":False,"global_snapshot":False,"provider_queries":0}
    finally:
        db.rollback()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db",required=True,type=Path)
    p.add_argument("windows",nargs="+",type=Path)
    a=p.parse_args()
    if not a.db.is_file() or a.db.is_symlink():
        p.error("Existing private bridge archive required")
    try:
        with closing(sqlite3.connect(a.db.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as db:
            print(encode(audit(db,a.windows,now=datetime.now(timezone.utc))))
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,sqlite3.Error,OSError):
        p.exit(1,"Census blocked: inspect private windows and archive; do not skip uncertain pages.\n")


if __name__=="__main__":
    main()
