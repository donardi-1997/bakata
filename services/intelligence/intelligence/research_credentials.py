"""Pinned Secrets Manager credential contract for the future isolated live worker.

No CLI, secret creation, provider request or automatic credential rotation.
Callers must be separately authorized; no existing fixture imports this module.
"""
from dataclasses import dataclass,field
import json
import re

from .dropify_catalog import unique

ARN_PATTERN=r"arn:aws:secretsmanager:us-east-1:([0-9]{12}):secret:bakata/research/dropify/[A-Za-z0-9_-]{1,64}-[A-Za-z0-9]{6}"
VERSION_PATTERN=r"[A-Za-z0-9-]{32,64}"
SCHEMA="bakata-dropify-research-secret-v1"


@dataclass(frozen=True,slots=True)
class SecretBinding:
    arn:str
    version:str
    account:str
    store:str

    def __post_init__(self):
        match=re.fullmatch(ARN_PATTERN,self.arn) if isinstance(self.arn,str) else None
        if (match is None or match.group(1)!=self.account
            or not isinstance(self.version,str) or not re.fullmatch(VERSION_PATTERN,self.version)
            or not isinstance(self.store,str) or not re.fullmatch(r"[1-9][0-9]{0,9}",self.store)):
            raise ValueError("Invalid pinned research credential binding")


@dataclass(frozen=True,slots=True)
class ResearchCredential:
    store:str
    token:str=field(repr=False)


def parse_secret(raw,store):
    try:
        if not isinstance(raw,str) or not 0<len(raw.encode("utf-8"))<=4096:
            raise ValueError()
        data=json.loads(raw,object_pairs_hook=unique)
        if (not isinstance(data,dict) or set(data)!={"schema","store_id","token"}
            or data["schema"]!=SCHEMA or data["store_id"]!=store
            or not isinstance(data["token"],str)
            or not re.fullmatch(r"[!-~]{1,1000}",data["token"])):
            raise ValueError()
        return ResearchCredential(store,data["token"])
    except (ValueError,TypeError,UnicodeError):
        raise ValueError("Invalid research credential envelope") from None


def load_pinned(client,binding):
    """One read, exact ARN/version and current stage; never fall back.

    Client must use the reviewed regional endpoint and bounded/no retry SDK config.
    No logging or response passthrough, including on provider exceptions.
    """
    if not isinstance(binding,SecretBinding):
        raise ValueError("Explicit research secret binding required")
    try:
        response=client.get_secret_value(SecretId=binding.arn,VersionId=binding.version,VersionStage="AWSCURRENT")
        if (response.get("ARN")!=binding.arn or response.get("VersionId")!=binding.version
            or "AWSCURRENT" not in response.get("VersionStages",[])
            or "SecretBinary" in response):
            raise ValueError()
        return parse_secret(response.get("SecretString"),binding.store)
    except Exception:
        raise ValueError("Pinned research credential unavailable; stop without retry") from None
