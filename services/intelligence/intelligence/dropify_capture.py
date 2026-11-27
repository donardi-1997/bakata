"""Bounded capture through the hardened connector's explicitly authorized WP-CLI reader."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import tempfile
import time

from .dropify_bridge import BridgeArchive, decode
from .dropify_catalog import MAX_BYTES, unique
from .storage import encode, ref

MAX_PAGES_PER_RUN=10
PAUSE_SECONDS=10


def durable(path,raw):
    """Publish a private record atomically, without overwriting evidence."""
    if path.exists() or path.is_symlink():
        raise ValueError("Existing capture record")
    with tempfile.NamedTemporaryFile(dir=path.parent,prefix=".capture-",delete=False) as handle:
        temp=Path(handle.name)
        try:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
            os.link(temp,path)
            fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            temp.unlink(missing_ok=True)


def read_record(path,limit):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Invalid private capture record")
    with path.open("rb") as handle:
        raw=handle.read(limit+1)
    if len(raw)>limit:
        raise ValueError("Capture record too large")
    return raw


def approval(run,page):
    return "batch-"+hashlib.sha256(f"{run}:{page}".encode()).hexdigest()


def policy(run,store,first,last,until,operator,source_ref):
    if not isinstance(run,str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",run) or not isinstance(store,str) or not re.fullmatch(r"[1-9][0-9]{0,9}",store):
        raise ValueError("Explicit run and store required")
    if type(first) is not int or type(last) is not int or not 1<=first<=last<=100 or last-first>=MAX_PAGES_PER_RUN or type(until) is not int:
        raise ValueError("Invalid authorized page range")
    return {"schema":"bakata-dropify-capture-run-v1","run":run,"store":store,"first":first,
        "last":last,"until":until,"operator":ref(operator),"source_ref":ref(source_ref)}


def capture(workspace,archive,plan,fetch,*,clock=time.time,pause=time.sleep):
    workspace=Path(workspace)
    if workspace.is_symlink():
        raise ValueError("Private workspace required")
    workspace.mkdir(mode=0o700,parents=False,exist_ok=True)
    mode=workspace.stat()
    if not workspace.is_dir() or mode.st_uid!=os.getuid() or stat.S_IMODE(mode.st_mode)&0o077:
        raise ValueError("Capture workspace must be private and owned by operator")
    lockfd=os.open(workspace/".lock",os.O_CREAT|os.O_NOFOLLOW|os.O_RDWR,0o600)
    with os.fdopen(lockfd,"wb") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        manifest=workspace/"run.json"
        raw_plan=encode(plan).encode()
        if manifest.exists():
            if read_record(manifest,8192)!=raw_plan:
                raise ValueError("Run scope changed")
        else:
            if not clock()<plan["until"]<=clock()+1800:
                raise ValueError("New run requires a current authorization")
            durable(manifest,raw_plan)
        seen=set()
        previous=None
        completed=requests=inserted=0
        reason="authorized-limit"
        for page in range(plan["first"],plan["last"]+1):
            output=workspace/f"page-{page:03d}.json"
            attempt=workspace/f"attempt-{page:03d}.json"
            if output.exists():
                raw=read_record(output,MAX_BYTES)
                if not attempt.exists():
                    raise ValueError("Page has no durable attempt record")
            else:
                if attempt.exists():
                    raise ValueError("Uncertain page attempt; reconcile manually, never retry")
                if clock()>=plan["until"]:
                    reason="authorization-expired"
                    break
                if completed:
                    pause(PAUSE_SECONDS)
                if clock()>=plan["until"]:
                    reason="authorization-expired"
                    break
                durable(attempt,encode({"run":plan["run"],"page":page,"at":int(clock())}).encode())
                raw=fetch(plan["run"],plan["store"],page)
                requests+=1
                if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_BYTES:
                    raise ValueError("Missing or oversized projected page")
                decode(raw,datetime.fromtimestamp(clock(),timezone.utc))
                durable(output,raw)
            marker=json.loads(read_record(attempt,8192),object_pairs_hook=unique)
            if not isinstance(marker,dict) or set(marker)!={"run","page","at"} or marker["run"]!=plan["run"] or marker["page"]!=page or type(marker["at"]) is not int:
                raise ValueError("Invalid attempt marker")
            now=datetime.fromtimestamp(clock(),timezone.utc)
            at,data=decode(raw,now)
            captured=datetime.fromisoformat(at).timestamp()
            if (data["store_id"],data["page"],data["page_size"],data["approval_ref"],data["query_sha256"])!=(
                plan["store"],page,10,approval(plan["run"],page),hashlib.sha256(b"").hexdigest()):
                raise ValueError("Page scope mismatch")
            if not marker["at"]<=captured<=clock() or captured>=plan["until"] or (previous is not None and captured<=previous):
                raise ValueError("Page capture chronology mismatch")
            ids=[int(r["external_id"]) for r in data["rows"]]
            if ids!=sorted(ids) or seen.intersection(ids) or (seen and ids and min(ids)<=max(seen)):
                raise ValueError("Pagination anomaly; review captured page, do not continue")
            # A crash after saving but before ingest resumes locally, no new call.
            receipt=archive.ingest(raw,plan["operator"],now)
            inserted+=receipt["inserted"]
            seen.update(ids)
            previous=captured
            completed+=1
            if not data["possible_next"]:
                reason="partial-or-empty-page"
                break
        following=plan["first"]+completed
        return {"schema":"bakata-dropify-capture-result-v1","run":plan["run"],
                "pages_archived":completed,"unique_ids_in_window":len(seen),
                "new_observations":inserted,"connector_calls_this_execution":requests,
                "stop_reason":reason,"next_page":following if reason!="partial-or-empty-page" and following<=100 else None,
                "coverage_verified":False,"provider_total_verified":False,"woo_mutation":False}


def connector(wrapper,run,store,page):
    # Operator-reviewed executable with a fixed site/user/script; no tokens in args.
    with tempfile.TemporaryFile() as out:
        result=subprocess.run([str(wrapper),run,store,str(page)],stdout=out,stderr=subprocess.DEVNULL,timeout=35,check=False)
        if result.returncode!=0:
            raise ValueError("Connector page blocked or uncertain")
        out.seek(0)
        return out.read(MAX_BYTES+1)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("workspace","db","wrapper"):
        p.add_argument("--"+name,required=True,type=Path)
    for name in ("run","store","operator"):
        p.add_argument("--"+name,required=True)
    for name in ("first","last","until"):
        p.add_argument("--"+name,required=True,type=int)
    a=p.parse_args()
    if any(x.is_symlink() for x in (a.workspace,a.db,a.wrapper)) or not a.wrapper.is_file() or not os.access(a.wrapper,os.X_OK) or not a.db.is_file() or a.db.samefile(a.wrapper):
        p.error("Existing bridge archive and trusted executable wrapper required")
    os.umask(0o077)
    try:
        binding=hashlib.sha256(encode([[str(x.resolve()),x.stat().st_dev,x.stat().st_ino] for x in (a.db,a.wrapper)]+[hashlib.sha256(read_record(a.wrapper,65536)).hexdigest()]).encode()).hexdigest()
        plan=policy(a.run,a.store,a.first,a.last,a.until,a.operator,binding)
        with closing(sqlite3.connect(a.db,timeout=5)) as db:
            archive=BridgeArchive(db)
            print(encode(capture(a.workspace,archive,plan,lambda r,s,n:connector(a.wrapper.resolve(),r,s,n))))
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,sqlite3.Error,OSError,subprocess.SubprocessError):
        p.exit(1,"Capture blocked; inspect private workspace and connector receipts. Never retry an uncertain page.\n")


if __name__=="__main__":
    main()
