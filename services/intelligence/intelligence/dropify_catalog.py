"""Unverified visible Dropify catalog observations, not supplier quotes or Woo imports."""
import argparse
from contextlib import closing
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

from .storage import instant, ref

MAX_BYTES=262144
MAX_PAGES=2000
MAX_ROWS=100000
APP_ID=0x424B4431
FIELDS=("external_id","sku","title","display_price","suggested_price","display_stock","category","warehouse","store")


def unique(pairs):
    result={}
    for k,v in pairs:
        if k in result:
            raise ValueError("Duplicate JSON field")
        result[k]=v
    return result


def amount(value, maximum):
    if value in ("","—","-"):
        return None
    if not re.fullmatch(r"(?:0|[1-9][0-9]{0,11}|[1-9][0-9]{0,2}(?:\.[0-9]{3}){1,3})",value):
        raise ValueError("Unknown display number format")
    result=int(value.replace(".",""))
    if result>maximum:
        raise ValueError("Display number exceeds bound")
    return result


def decode(raw,now):
    if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_BYTES:
        raise ValueError("Invalid export size")
    data=json.loads(raw,object_pairs_hook=unique)
    if not isinstance(data,dict) or set(data)!={"schema","captured_at","rows"} or data["schema"]!="bakata-dropify-visible-v1":
        raise ValueError("Invalid export contract")
    if not isinstance(data["captured_at"],str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z",data["captured_at"]):
        raise ValueError("Expected browser UTC time")
    at=instant(datetime.fromisoformat(data["captured_at"].replace("Z","+00:00")))
    if at>instant(now)+timedelta(minutes=5):
        raise ValueError("Future capture")
    if not isinstance(data["rows"],list) or not 1<=len(data["rows"])<=100:
        raise ValueError("Invalid page size")
    rows=[]
    seen=set()
    for item in data["rows"]:
        if not isinstance(item,dict) or set(item)!=set(FIELDS):
            raise ValueError("Unexpected catalog fields")
        for value in item.values():
            if not isinstance(value,str) or len(value)>512 or any(ord(c)<32 or ord(c)==127 for c in value):
                raise ValueError("Invalid catalog text")
        if not re.fullmatch(r"[1-9][0-9]{0,29}",item["external_id"]) or not item["title"].strip() or not item["store"].strip():
            raise ValueError("Missing identity")
        key=(item["store"],item["external_id"])
        if key in seen:
            raise ValueError("Duplicate catalog identity")
        seen.add(key)
        rows.append((item["store"],item["external_id"],item["sku"],item["title"],
                     amount(item["display_price"],10**10),amount(item["suggested_price"],10**10),
                     amount(item["display_stock"],10**7),item["category"],item["warehouse"]))
    return at.isoformat(timespec="microseconds"),rows


class DropifyCatalog:
    def __init__(self,db):
        self.db=db
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("BEGIN IMMEDIATE")
        try:
            app=db.execute("PRAGMA application_id").fetchone()[0]
            version=db.execute("PRAGMA user_version").fetchone()[0]
            if app==version==0:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1").fetchone():
                    raise ValueError("Unrecognized database")
                db.execute("CREATE TABLE pages (sha256 TEXT PRIMARY KEY, captured_at TEXT NOT NULL, operator_ref TEXT NOT NULL, row_count INTEGER NOT NULL)")
                db.execute("""CREATE TABLE catalog (
                    store TEXT NOT NULL, external_id TEXT NOT NULL, captured_at TEXT NOT NULL,
                    sku TEXT NOT NULL, title TEXT NOT NULL, display_price INTEGER, suggested_price INTEGER,
                    display_stock INTEGER, category TEXT NOT NULL, warehouse TEXT NOT NULL,
                    PRIMARY KEY(store,external_id,captured_at))""")
                db.execute("""CREATE TABLE page_rows (
                    sha256 TEXT NOT NULL REFERENCES pages(sha256), store TEXT NOT NULL, external_id TEXT NOT NULL,
                    captured_at TEXT NOT NULL, PRIMARY KEY(sha256,store,external_id),
                    FOREIGN KEY(store,external_id,captured_at) REFERENCES catalog(store,external_id,captured_at))""")
                db.execute(f"PRAGMA application_id={APP_ID}")
                db.execute("PRAGMA user_version=1")
            elif app!=APP_ID or version!=1:
                raise ValueError("Unsupported catalog database")
            page_size=db.execute("PRAGMA page_size").fetchone()[0]
            cap=320*1024*1024//page_size
            if db.execute(f"PRAGMA max_page_count={cap}").fetchone()[0]>cap:
                raise ValueError("Catalog storage budget exceeded")
            db.commit()
        except BaseException:
            db.rollback()
            raise

    def ingest(self,raw,operator_ref,now):
        operator_ref=ref(operator_ref)
        at,rows=decode(raw,now)
        sha=hashlib.sha256(raw).hexdigest()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            old=self.db.execute("SELECT 1 FROM pages WHERE sha256=?",(sha,)).fetchone()
            if old:
                self.db.commit()
                return {"page_sha256":sha,"inserted":0,"replay":True}
            if self.db.execute("SELECT COUNT(*) FROM pages").fetchone()[0]>=MAX_PAGES:
                raise ValueError("Page capacity reached")
            self.db.execute("INSERT INTO pages VALUES (?,?,?,?)",(sha,at,operator_ref,len(rows)))
            available=MAX_ROWS-self.db.execute("SELECT COUNT(*) FROM catalog").fetchone()[0]
            inserted=0
            for store,eid,*values in rows:
                key=(store,eid,at)
                existing=self.db.execute("SELECT sku,title,display_price,suggested_price,display_stock,category,warehouse FROM catalog WHERE store=? AND external_id=? AND captured_at=?",key).fetchone()
                if existing is not None and existing!=tuple(values):
                    raise ValueError("Conflicting observation")
                if existing is None:
                    if inserted>=available:
                        raise ValueError("Observation capacity reached")
                    self.db.execute("INSERT INTO catalog VALUES (?,?,?,?,?,?,?,?,?,?)",key+tuple(values))
                    inserted+=1
                self.db.execute("INSERT INTO page_rows VALUES (?,?,?,?)",(sha,store,eid,at))
            self.db.commit()
            return {"page_sha256":sha,"inserted":inserted,"replay":False}
        except BaseException:
            self.db.rollback()
            raise

    def candidates(self,*,store="",category="",query="",in_stock=False,limit=100,offset=0):
        if type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or not 0<=offset<=MAX_ROWS:
            raise ValueError("Invalid pagination")
        if any(not isinstance(v,str) or len(v)>120 for v in (store,category,query)):
            raise ValueError("Invalid filter")
        cursor=self.db.execute("""WITH latest AS (
            SELECT *, ROW_NUMBER() OVER(PARTITION BY store,external_id ORDER BY captured_at DESC) AS rn
            FROM catalog)
            SELECT store,external_id,captured_at,sku,title,display_price,suggested_price,display_stock,category,warehouse,
                CASE WHEN display_price IS NOT NULL AND suggested_price IS NOT NULL THEN suggested_price-display_price END AS displayed_spread
            FROM latest WHERE rn=1 AND (?='' OR store=?) AND (?='' OR category=?)
              AND (?='' OR instr(lower(title||' '||sku||' '||external_id),lower(?))>0)
              AND (?=0 OR display_stock>0)
            ORDER BY store,external_id LIMIT ? OFFSET ?""",
            (store,store,category,category,query,query,int(in_stock),limit,offset))
        return [dict(zip((c[0] for c in cursor.description),row)) for row in cursor.fetchall()]


def main():
    parser=argparse.ArgumentParser(description="Offline archive of visible Dropify pages")
    parser.add_argument("--db",required=True,type=Path)
    sub=parser.add_subparsers(dest="command",required=True)
    ingest=sub.add_parser("ingest")
    ingest.add_argument("file",type=Path)
    ingest.add_argument("--operator-ref",required=True)
    query=sub.add_parser("candidates")
    query.add_argument("--store",default="")
    query.add_argument("--category",default="")
    query.add_argument("--query",default="")
    query.add_argument("--in-stock",action="store_true")
    query.add_argument("--limit",type=int,default=100)
    query.add_argument("--offset",type=int,default=0)
    args=parser.parse_args()
    os.umask(0o077)
    with closing(sqlite3.connect(args.db,timeout=5)) as db:
        catalog=DropifyCatalog(db)
        if args.command=="ingest":
            with args.file.open("rb") as handle:
                result=catalog.ingest(handle.read(MAX_BYTES+1),args.operator_ref,datetime.now(timezone.utc))
        else:
            result=catalog.candidates(store=args.store,category=args.category,query=args.query,
                                      in_stock=args.in_stock,limit=args.limit,offset=args.offset)
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":
    main()
