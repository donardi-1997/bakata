"""Fixture-only durable AWS capture protocol; no supplier client or live entry point.

Injected low-level DynamoDB and S3 clients. A reserved page is never retried,
even if its task disappears. Only validated evidence can release the store lock.
"""
import base64
from datetime import datetime,timezone
import hashlib
import json
import re
import uuid

from .dropify_bridge import decode
from .dropify_capture import approval,policy,PAUSE_SECONDS
from .dropify_catalog import MAX_BYTES,unique
from .storage import encode

PREFIX="fixture-research/v1/"


def timestamp(now):
    if type(now) is not int or not 0<now<4102444800:
        raise ValueError("Explicit UTC epoch required")
    return now


def plan_checked(plan):
    if not isinstance(plan,dict) or plan!=policy(plan["run"],plan["store"],plan["first"],
        plan["last"],plan["until"],plan["operator"],plan["source_ref"]):
        raise ValueError("Invalid immutable plan")
    if not plan["run"].startswith("fixture-"):
        raise ValueError("Fixture-only protocol")
    return plan


class ResearchReceipts:
    def __init__(self,ddb,s3,*,table,bucket):
        if not isinstance(table,str) or not re.fullmatch(r"[A-Za-z0-9_.-]{3,255}",table) or not isinstance(bucket,str) or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]",bucket):
            raise ValueError("Explicit AWS resources required")
        self.ddb,self.s3,self.table,self.bucket=ddb,s3,table,bucket

    def _key(self,store,sk):
        return {"pk":{"S":"FIXTURE#STORE#"+store},"sk":{"S":sk}}

    def _read(self,key):
        item=self.ddb.get_item(TableName=self.table,Key=key,ConsistentRead=True).get("Item")
        if item is None:
            return None
        raw=item["payload"]["S"]
        if len(raw)>16384:
            raise ValueError("Unexpected ledger payload")
        data=json.loads(raw,object_pairs_hook=unique)
        if encode(data)!=raw or not isinstance(data,dict):
            raise ValueError("Unexpected ledger encoding")
        return data

    def _put(self,key,old,new):
        # Compare the exact previous immutable representation, not only a status.
        params={"TableName":self.table,"Item":dict(key,payload={"S":encode(new)})}
        if old is None:
            params.update(ConditionExpression="attribute_not_exists(#pk)",ExpressionAttributeNames={"#pk":"pk"})
        else:
            params.update(ConditionExpression="#p = :old",ExpressionAttributeNames={"#p":"payload"},ExpressionAttributeValues={":old":{"S":encode(old)}})
        return {"Put":params}

    def _check(self,key,old):
        return {"ConditionCheck":{"TableName":self.table,"Key":key,
            "ConditionExpression":"#p = :old","ExpressionAttributeNames":{"#p":"payload"},"ExpressionAttributeValues":{":old":{"S":encode(old)}}}}

    def _txn(self,*items):
        # No application retry. Ambiguous transaction result must be reconciled.
        self.ddb.transact_write_items(TransactItems=list(items))

    def _keys(self,plan,page):
        return (self._key(plan["store"],"CONTROL"),self._key(plan["store"],"RUN#"+plan["run"]),
                self._key(plan["store"],f"PAGE#{plan['run']}#{page:04d}"))

    def register(self,plan,*,now):
        plan_checked(plan)
        timestamp(now)
        if not now<plan["until"]<=now+1800:
            raise ValueError("Current explicit authorization required")
        _,runkey,_=self._keys(plan,plan["first"])
        state={"plan":plan,"state":"open","next_page":plan["first"],"last_id":"0","last_at":0}
        self._txn(self._put(runkey,None,state))

    def reserve(self,plan,page,*,now):
        """Only a successful return grants permission to a future fixture caller."""
        plan_checked(plan)
        timestamp(now)
        if type(page) is not int or not plan["first"]<=page<=plan["last"] or not now<plan["until"]<=now+1800:
            raise ValueError("Outside authorized page or expiry")
        controlkey,runkey,pagekey=self._keys(plan,page)
        run=self._read(runkey)
        control=self._read(controlkey)
        if run is None or run["plan"]!=plan or run["state"]!="open" or run["next_page"]!=page:
            raise ValueError("Run not registered or unexpected page")
        if control is not None and (control["state"]!="idle" or now<control["not_before"]):
            raise ValueError("Store blocked by active or uncertain reservation, or cooldown")
        receipt={"plan":plan,"page":page,"attempt":uuid.uuid4().hex,"reserved_at":now,"state":"reserved"}
        lock={"state":"reserved","run":plan["run"],"page":page,"attempt":receipt["attempt"]}
        self._txn(self._check(runkey,run),self._put(controlkey,control,lock),self._put(pagekey,None,receipt))
        return receipt

    def _reserved(self,plan,page,attempt):
        plan_checked(plan)
        if type(page) is not int or not plan["first"]<=page<=plan["last"] or not isinstance(attempt,str) or not re.fullmatch(r"[0-9a-f]{32}",attempt):
            raise ValueError("Invalid reservation identity")
        keys=self._keys(plan,page)
        control,run,receipt=(self._read(k) for k in keys)
        expected={"state":"reserved","run":plan["run"],"page":page,"attempt":attempt}
        if control!=expected or run is None or run["plan"]!=plan or run["state"]!="open" or run["next_page"]!=page or receipt is None or receipt["plan"]!=plan or receipt["state"]!="reserved" or receipt["attempt"]!=attempt or receipt["page"]!=page:
            raise ValueError("No matching active reservation")
        return keys,control,run,receipt

    def _validate(self,raw,plan,page,run,receipt,now):
        timestamp(now)
        at,data=decode(raw,datetime.fromtimestamp(now,timezone.utc))
        captured=int(datetime.fromisoformat(at).timestamp())
        if (data["store_id"],data["page"],data["page_size"],data["approval_ref"],data["query_sha256"])!=(plan["store"],page,10,approval(plan["run"],page),hashlib.sha256(b"").hexdigest()):
            raise ValueError("Snapshot scope mismatch")
        if not receipt["reserved_at"]<=captured<plan["until"] or captured>now or captured<=run["last_at"]:
            raise ValueError("Invalid observation chronology")
        ids=[int(x["external_id"]) for x in data["rows"]]
        if ids!=sorted(ids) or (ids and ids[0]<=int(run["last_id"])):
            raise ValueError("Non-increasing catalog identity")
        return data,captured,str(ids[-1]) if ids else run["last_id"]

    def _object_key(self,plan,page):
        return f"{PREFIX}{plan['store']}/{plan['run']}/{page:04d}.json"

    def _read_evidence(self,key,attempt,version=None):
        args={"Bucket":self.bucket,"Key":key}
        if version is not None:
            args["VersionId"]=version
        response=self.s3.get_object(**args)
        stream=response["Body"]
        try:
            if not 0<response["ContentLength"]<=MAX_BYTES:
                raise ValueError("Unexpected evidence length")
            raw=stream.read(MAX_BYTES+1)
        finally:
            stream.close()
        digest=hashlib.sha256(raw).hexdigest()
        vid=response.get("VersionId")
        if (not isinstance(vid,str) or not vid or vid=="null" or (version is not None and vid!=version)
            or len(raw)!=response["ContentLength"] or response.get("Metadata")!={"attempt":attempt,"sha256":digest}):
            raise ValueError("Unverified versioned evidence")
        return raw,digest,vid

    def _finish(self,plan,page,attempt,now,reservation,raw,digest,version):
        keys,control,run,receipt=reservation
        data,captured,last_id=self._validate(raw,plan,page,run,receipt,now)
        result=dict(receipt,state="archived",sha256=digest,version_id=version,
                    object_key=self._object_key(plan,page),rows=len(data["rows"]),captured_at=captured)
        next_state="terminal-page-observed" if not data["possible_next"] else "window-complete" if page==plan["last"] else "open"
        next_run=dict(run,state=next_state,next_page=page+1,last_id=last_id,last_at=captured)
        idle={"state":"idle","not_before":now+PAUSE_SECONDS}
        self._txn(self._put(keys[0],control,idle),self._put(keys[1],run,next_run),self._put(keys[2],receipt,result))
        return {"state":next_state,"page":page,"rows":len(data["rows"]),"sha256":digest,
                "version_id":version,"next_page":page+1 if next_state=="open" else None,
                "coverage_verified":False,"provider_queries":0}

    def persist(self,plan,page,attempt,raw,*,now):
        """Write once, read exact version back, then atomically release reservation."""
        reservation=self._reserved(plan,page,attempt)
        self._validate(raw,plan,page,reservation[2],reservation[3],now)
        digest=hashlib.sha256(raw).hexdigest()
        key=self._object_key(plan,page)
        response=self.s3.put_object(Bucket=self.bucket,Key=key,Body=raw,ContentType="application/json",
            ServerSideEncryption="AES256",IfNoneMatch="*",ChecksumSHA256=base64.b64encode(bytes.fromhex(digest)).decode(),
            Metadata={"attempt":attempt,"sha256":digest})
        version=response.get("VersionId")
        if not isinstance(version,str) or not version or version=="null":
            raise ValueError("Versioned bucket required")
        verified,actual,vid=self._read_evidence(key,attempt,version)
        if verified!=raw or actual!=digest:
            raise ValueError("Evidence readback mismatch")
        return self._finish(plan,page,attempt,now,reservation,verified,actual,vid)

    def recover(self,plan,page,attempt,*,now):
        """Explicit recovery of already saved evidence, never a connector retry."""
        reservation=self._reserved(plan,page,attempt)
        raw,digest,version=self._read_evidence(self._object_key(plan,page),attempt)
        return self._finish(plan,page,attempt,now,reservation,raw,digest,version)

    def status(self,plan,page):
        plan_checked(plan)
        if type(page) is not int or not plan["first"]<=page<=plan["last"]:
            raise ValueError("Invalid page")
        controlkey,runkey,pagekey=self._keys(plan,page)
        run=self._read(runkey)
        receipt=self._read(pagekey)
        if run is None or run["plan"]!=plan or (receipt is not None and receipt["plan"]!=plan):
            raise ValueError("Scope mismatch")
        return {"run":run,"page":receipt,"control":self._read(controlkey),
                "requires_reconciliation":receipt is not None and receipt["state"]=="reserved"}
