"""Scoped external expiry enforcement contract. No deployed trigger or AWS client.

Only a trusted controller may supply a persisted, immutable task binding.
Never discover tasks by tag, stop arbitrary tasks, or release a page reservation.
"""
from dataclasses import dataclass
import re

from .research_receipts import timestamp


@dataclass(frozen=True,slots=True)
class FixtureTaskBinding:
    cluster:str
    task:str
    definition:str
    run:str
    until:int

    def __post_init__(self):
        match=re.fullmatch(r"arn:aws:ecs:us-east-1:([0-9]{12}):cluster/(bakata-research-[A-Za-z0-9_-]{1,80})",self.cluster) if isinstance(self.cluster,str) else None
        if match is None:
            raise ValueError("Reviewed research cluster required")
        account,cluster=match.groups()
        base=f"arn:aws:ecs:us-east-1:{account}:"
        if (not isinstance(self.task,str) or not re.fullmatch(re.escape(base+"task/"+cluster+"/")+r"[0-9a-f]{32}",self.task)
            or not isinstance(self.definition,str) or not re.fullmatch(re.escape(base+"task-definition/")+r"bakata-research-[A-Za-z0-9_-]{1,80}-persistent-fixture:[1-9][0-9]*",self.definition)
            or not isinstance(self.run,str) or not re.fullmatch(r"fixture-[A-Za-z0-9_-]{1,56}",self.run)):
            raise ValueError("Reviewed fixture task identity required")
        timestamp(self.until)


def enforce_deadline(ecs,binding,*,now):
    if not isinstance(binding,FixtureTaskBinding):
        raise ValueError("Explicit task binding required")
    timestamp(now)
    if now<binding.until:
        return {"state":"before-deadline","stop_requested":False}
    try:
        result=ecs.describe_tasks(cluster=binding.cluster,tasks=[binding.task],include=["TAGS"])
        if result.get("failures") or len(result.get("tasks",[]))!=1:
            raise ValueError()
        task=result["tasks"][0]
        tags=task.get("tags",[])
        if not isinstance(tags,list) or len(tags)>50:
            raise ValueError()
        keys=[x["key"] for x in tags]
        tagmap={x["key"]:x["value"] for x in tags}
        if (len(keys)!=len(set(keys))
            or task.get("taskArn")!=binding.task or task.get("clusterArn")!=binding.cluster
            or task.get("taskDefinitionArn")!=binding.definition or task.get("launchType")!="FARGATE"
            or tagmap.get("bakata:purpose")!="research-fixture"
            or tagmap.get("bakata:run")!=binding.run or tagmap.get("bakata:until")!=str(binding.until)):
            raise ValueError()
        if task.get("lastStatus")=="STOPPED":
            return {"state":"stopped","stop_requested":False}
        if task.get("desiredStatus")=="STOPPED":
            return {"state":"stopping","stop_requested":False}
        if task.get("lastStatus") not in {"PROVISIONING","PENDING","ACTIVATING","RUNNING","DEACTIVATING"} or task.get("desiredStatus")!="RUNNING":
            raise ValueError()
        reply=ecs.stop_task(cluster=binding.cluster,task=binding.task,reason="Bakata research fixture deadline exceeded")
        if reply.get("task",{}).get("taskArn")!=binding.task or reply["task"].get("desiredStatus")!="STOPPED":
            raise ValueError()
        return {"state":"stop-requested","stop_requested":True}
    except Exception:
        # An ambiguous StopTask is not evidence of actual termination.
        # Reconcile by DescribeTasks; never start or repeat a provider request.
        raise ValueError("Research task stop state unverified; reconcile manually") from None
