"""Offline archive of bounded read-only connector snapshots. No supplier API."""
from contextlib import closing
from datetime import datetime, timezone, timedelta
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

from .dropify_catalog import unique, MAX_BYTES, MAX_PAGES, MAX_ROWS
from .storage import CommercialStore, instant, ref

APP_ID = 0x424B4432
FIELDS = {"external_id","sku","title","type","base_price","suggested_price","simple_stock","categories","warehouse"}


def text(value, limit, required=False):
    if not isinstance(value,str) or len(value.encode("utf-8"))>limit or any(ord(c)<32 or ord(c)==127 for c in value):
        raise ValueError("Invalid text")
    if required and not value.strip():
        raise ValueError("Missing title")
    return value


def decimal(value):
    if value is None:
        return None
    if not isinstance(value,str) or not re.fullmatch(r"(?:0|[1-9][0-9]{0,9})(?:\.[0-9]{1,2})?",value):
        raise ValueError("Invalid raw price")
    return value


def decode(raw, now):
    if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_BYTES:
        raise ValueError("Invalid snapshot size")
    data=json.loads(raw,object_pairs_hook=unique)
    if not isinstance(data,dict) or set(data)!={"schema","captured_at","store_id","page","page_size","offset","possible_next","rows","approval_ref","query_sha256"} or data["schema"]!="bakata-dropify-bridge-v1":
        raise ValueError("Unknown bridge schema")
    if not isinstance(data["captured_at"],str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",data["captured_at"]):
        raise ValueError("Invalid UTC capture time")
    at=instant(datetime.fromisoformat(data["captured_at"].replace("Z","+00:00")))
    if at>instant(now)+timedelta(minutes=5):
        raise ValueError("Future capture")
    ref(data["approval_ref"])
    if not isinstance(data["query_sha256"],str) or not re.fullmatch(r"[0-9a-f]{64}",data["query_sha256"]):
        raise ValueError("Invalid query digest")
    store=data["store_id"]
    page,size=data["page"],data["page_size"]
    if not isinstance(store,str) or not re.fullmatch(r"[1-9][0-9]{0,9}",store) or type(page) is not int or not 1<=page<=100 or type(size) is not int or not 1<=size<=20 or type(data["offset"]) is not int or data["offset"]!=(page-1)*size:
        raise ValueError("Invalid page metadata")
    rows=data["rows"]
    if not isinstance(rows,list) or len(rows)>size or type(data["possible_next"]) is not bool or data["possible_next"]!=(len(rows)==size):
        raise ValueError("Invalid response cardinality")
    seen=set()
    for row in rows:
        if not isinstance(row,dict) or set(row)!=FIELDS:
            raise ValueError("Unexpected raw row fields")
        eid=row["external_id"]
        if not isinstance(eid,str) or not re.fullmatch(r"[1-9][0-9]{0,29}",eid) or eid in seen:
            raise ValueError("Invalid or duplicate ID")
        seen.add(eid)
        text(row["sku"],128)
        text(row["title"],300,True)
        text(row["warehouse"],150)
        if row["type"] not in ("simple","unresolved"):
            raise ValueError("Invalid type")
        stock=row["simple_stock"]
        if stock is not None and (row["type"]!="simple" or type(stock) is not int or not 0<=stock<=1000000):
            raise ValueError("Invalid reported stock")
        decimal(row["base_price"])
        decimal(row["suggested_price"])
        if not isinstance(row["categories"],list) or len(row["categories"])>20:
            raise ValueError("Invalid categories")
        for label in row["categories"]:
            text(label,100,True)
    return at.isoformat(),data


class BridgeArchive:
    def __init__(self,db):
        self.db=db
        if db.in_transaction:
            raise ValueError("Independent connection required")
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("PRAGMA foreign_keys=ON")
        if db.execute("PRAGMA foreign_keys").fetchone()[0]!=1:
            raise ValueError("Foreign key enforcement unavailable")
        with db:
            db.execute("BEGIN IMMEDIATE")
            app,version=(db.execute("PRAGMA "+p).fetchone()[0] for p in ("application_id","user_version"))
            if app==version==0:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1").fetchone():
                    raise ValueError("Unrecognized database")
                db.execute("""CREATE TABLE pages (sha TEXT PRIMARY KEY,store TEXT NOT NULL,at TEXT NOT NULL,
                    page INTEGER NOT NULL,size INTEGER NOT NULL,operator TEXT NOT NULL,rows INTEGER NOT NULL,
                    approval_ref TEXT NOT NULL,query_sha256 TEXT NOT NULL)""")
                db.execute("""CREATE TABLE observations (store TEXT NOT NULL,id TEXT NOT NULL,at TEXT NOT NULL,
                    payload TEXT NOT NULL,PRIMARY KEY(store,id,at))""")
                db.execute("""CREATE TABLE page_rows (sha TEXT NOT NULL REFERENCES pages(sha),store TEXT NOT NULL,
                    id TEXT NOT NULL,at TEXT NOT NULL,PRIMARY KEY(sha,store,id),
                    FOREIGN KEY(store,id,at) REFERENCES observations(store,id,at))""")
                db.execute("""CREATE TABLE score_links (id TEXT PRIMARY KEY,store TEXT NOT NULL,product_id TEXT NOT NULL,
                    at TEXT NOT NULL,evaluation_id TEXT NOT NULL,evaluation_sha TEXT NOT NULL,
                    payload TEXT NOT NULL,FOREIGN KEY(store,product_id,at) REFERENCES observations(store,id,at))""")
                db.execute(f"PRAGMA application_id={APP_ID}")
                db.execute("PRAGMA user_version=1")
            elif app!=APP_ID or version!=1:
                raise ValueError("Unknown bridge archive schema")
            cap=320*1024*1024//db.execute("PRAGMA page_size").fetchone()[0]
            if db.execute(f"PRAGMA max_page_count={cap}").fetchone()[0]>cap:
                raise ValueError("Archive file limit exceeded")

    @staticmethod
    def encode(row):
        return json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(",",":"))

    def ingest(self,raw,operator,now):
        operator=ref(operator)
        at,data=decode(raw,now)
        store=data["store_id"]
        sha=hashlib.sha256(raw).hexdigest()
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if self.db.execute("SELECT 1 FROM pages WHERE sha=?",(sha,)).fetchone():
                return {"sha256":sha,"inserted":0}
            if self.db.execute("SELECT COUNT(*) FROM pages").fetchone()[0]>=MAX_PAGES:
                raise ValueError("Page capacity reached")
            self.db.execute("INSERT INTO pages VALUES (?,?,?,?,?,?,?,?,?)",(sha,store,at,data["page"],data["page_size"],operator,len(data["rows"]),data["approval_ref"],data["query_sha256"]))
            remaining=MAX_ROWS-self.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
            inserted=0
            for row in data["rows"]:
                key=(store,row["external_id"],at)
                payload=self.encode(row)
                old=self.db.execute("SELECT payload FROM observations WHERE store=? AND id=? AND at=?",key).fetchone()
                if old is not None and old!=(payload,):
                    raise ValueError("Conflicting observation")
                if old is None:
                    if inserted>=remaining:
                        raise ValueError("Observation capacity reached")
                    self.db.execute("INSERT INTO observations VALUES (?,?,?,?)",key+(payload,))
                    inserted+=1
                self.db.execute("INSERT INTO page_rows VALUES (?,?,?,?)",(sha,)+key)
        return {"sha256":sha,"inserted":inserted}

    def candidates(self,*,store,query="",category="",in_stock=False,limit=100,offset=0):
        if not isinstance(store,str) or not re.fullmatch(r"[1-9][0-9]{0,9}",store) or type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or not 0<=offset<=MAX_ROWS:
            raise ValueError("Invalid filters or pagination")
        text(query,120)
        text(category,100)
        rows=self.db.execute("""WITH latest AS (SELECT *,ROW_NUMBER() OVER(PARTITION BY store,id ORDER BY at DESC) rn
            FROM observations WHERE store=?) SELECT at,payload FROM latest WHERE rn=1
            AND (?='' OR instr(lower(json_extract(payload,'$.title')||' '||json_extract(payload,'$.sku')||' '||id),lower(?))>0)
            AND (?='' OR EXISTS(SELECT 1 FROM json_each(payload,'$.categories') WHERE value=?))
            AND (?=0 OR json_extract(payload,'$.simple_stock')>0)
            ORDER BY id LIMIT ? OFFSET ?""",(store,query,query,category,category,int(in_stock),limit,offset)).fetchall()
        return [dict(json.loads(payload),store_id=store,captured_at=at) for at,payload in rows]

    def link_score(self,link_id,key,commercial,evaluation_id,*,mapping_ref,cost_ref,actor_ref,
                   reviewed_cost_minor,now):
        """Link an existing review, never treat raw base price as acquisition cost."""
        link_id,evaluation_id,mapping_ref,cost_ref,actor_ref=map(ref,(link_id,evaluation_id,mapping_ref,cost_ref,actor_ref))
        now=instant(now)
        if not isinstance(key,tuple) or len(key)!=3 or type(reviewed_cost_minor) is not int or reviewed_cost_minor<0:
            raise ValueError("Explicit reviewed cost and observation key required")
        stored=self.db.execute("SELECT payload FROM observations WHERE store=? AND id=? AND at=?",key).fetchone()
        if stored is None or not timedelta(0)<=now-datetime.fromisoformat(key[2])<=timedelta(days=1):
            raise ValueError("Missing or stale connector observation")
        row=json.loads(stored[0])
        if row["type"]!="simple" or not row["simple_stock"]:
            raise ValueError("Reported positive simple stock required")
        review=commercial.review("evaluation",evaluation_id)
        if review is None:
            raise ValueError("Reviewed commercial evaluation required")
        result=review["payload"]["result"]
        economics=review["payload"]["economics"]
        if result["status"]!="review-ready" or result["blockers"] or result["coverage_pct"]!=100 or result["total"] is None or economics is None or economics["currency"]!="COP" or economics["supplier_cost_minor"]!=reviewed_cost_minor or economics["evidence_ref"]!=cost_ref:
            raise ValueError("Evaluation does not match independently reviewed supplier cost")
        age=timedelta(microseconds=result["max_age"])
        times=[datetime.fromisoformat(review["observed_at"]),datetime.fromisoformat(review["as_of"]),
               datetime.fromisoformat(economics["reviewed_at"])]
        times.extend(datetime.fromisoformat(r["reviewed_at"]) for r in review["payload"]["reviews"])
        if any(not timedelta(0)<=now-at<=age for at in times):
            raise ValueError("Stale or future evaluation evidence")
        payload={"mapping_ref":mapping_ref,"cost_ref":cost_ref,"actor_ref":actor_ref,
                 "reviewed_cost_minor":reviewed_cost_minor,"linked_at":now.isoformat(),
                 "score":result["total"],"rubric":result["rubric_version"],"mode":"review-reference-only"}
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if self.db.execute("SELECT COUNT(*) FROM score_links").fetchone()[0]>=20000:
                raise ValueError("Link capacity reached")
            self.db.execute("INSERT INTO score_links VALUES (?,?,?,?,?,?,?)",
                            (link_id,)+key+(evaluation_id,review["sha256"],self.encode(payload)))
        return payload

    def links(self,key):
        rows=self.db.execute("""SELECT id,evaluation_id,evaluation_sha,payload FROM score_links
            WHERE store=? AND product_id=? AND at=? ORDER BY id LIMIT 101""",key).fetchall()
        if len(rows)>100:
            raise ValueError("Too many historical links")
        return [dict(json.loads(payload),link_id=lid,evaluation_id=eid,evaluation_sha256=sha)
                for lid,eid,sha,payload in rows]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db",required=True,type=Path)
    sub=parser.add_subparsers(dest="command",required=True)
    ingest=sub.add_parser("ingest")
    ingest.add_argument("file",type=Path)
    ingest.add_argument("--operator",required=True)
    candidates=sub.add_parser("candidates")
    candidates.add_argument("--store",required=True)
    candidates.add_argument("--query",default="")
    candidates.add_argument("--category",default="")
    candidates.add_argument("--in-stock",action="store_true")
    candidates.add_argument("--limit",type=int,default=100)
    candidates.add_argument("--offset",type=int,default=0)
    link=sub.add_parser("link-score")
    link.add_argument("--commercial",type=Path,required=True)
    link.add_argument("--link-id",required=True)
    link.add_argument("--evaluation-id",required=True)
    for command in (link,sub.add_parser("links")):
        command.add_argument("--store",required=True)
        command.add_argument("--product-id",required=True)
        command.add_argument("--captured-at",required=True)
    link.add_argument("--mapping-ref",required=True)
    link.add_argument("--cost-ref",required=True)
    link.add_argument("--actor-ref",required=True)
    link.add_argument("--reviewed-cost-minor",required=True,type=int)
    args=parser.parse_args()
    if args.command=="link-score" and (not args.commercial.is_file() or args.db.resolve()==args.commercial.resolve() or (args.db.exists() and args.db.samefile(args.commercial))):
        parser.error("An existing distinct commercial archive is required")
    os.umask(0o077)
    with closing(sqlite3.connect(args.db,timeout=5)) as db:
        archive=BridgeArchive(db)
        if args.command=="ingest":
            with args.file.open("rb") as handle:
                result=archive.ingest(handle.read(MAX_BYTES+1),args.operator,datetime.now(timezone.utc))
        elif args.command=="candidates":
            result=archive.candidates(store=args.store,query=args.query,category=args.category,
                                      in_stock=args.in_stock,limit=args.limit,offset=args.offset)
        else:
            key=(args.store,args.product_id,instant(datetime.fromisoformat(args.captured_at)).isoformat())
            if args.command=="links":
                result=archive.links(key)
            else:
                with closing(sqlite3.connect(args.commercial,timeout=5)) as commercial_db:
                    commercial=CommercialStore(commercial_db)
                    result=archive.link_score(args.link_id,key,commercial,args.evaluation_id,
                        mapping_ref=args.mapping_ref,cost_ref=args.cost_ref,actor_ref=args.actor_ref,
                        reviewed_cost_minor=args.reviewed_cost_minor,now=datetime.now(timezone.utc))
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":
    main()
