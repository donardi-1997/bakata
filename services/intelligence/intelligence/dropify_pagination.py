"""Review adjacent captured pages; a clean result never proves completeness."""
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path

from .dropify_bridge import decode
from .dropify_catalog import MAX_BYTES
from .storage import instant


def compare(raw_pages, *, now):
    if not isinstance(raw_pages,(list,tuple)) or not 2<=len(raw_pages)<=3:
        raise ValueError("Provide two or three adjacent snapshots")
    now=instant(now)
    pages=[]
    for raw in raw_pages:
        at,data=decode(raw,now)
        pages.append((datetime.fromisoformat(at),data,hashlib.sha256(raw).hexdigest()))
    pages.sort(key=lambda p:p[1]["page"])
    first=pages[0][1]
    if any((d["store_id"],d["page_size"],d["query_sha256"]) !=
           (first["store_id"],first["page_size"],first["query_sha256"]) for _,d,_ in pages):
        raise ValueError("Store, page size and query digest must match")
    if [d["page"] for _,d,_ in pages]!=list(range(first["page"],first["page"]+len(pages))):
        raise ValueError("Snapshots must represent adjacent distinct pages")
    if len({d["approval_ref"] for _,d,_ in pages})!=len(pages):
        raise ValueError("Each page needs a separate authorization reference")
    times=[at for at,_,_ in pages]
    if times!=sorted(times) or len(set(times))!=len(times) or times[-1]-times[0]>timedelta(minutes=30):
        raise ValueError("Snapshots must be sequential within 30 minutes")
    if times[-1]>now or now-times[0]>timedelta(days=1):
        raise ValueError("Review only recent, non-future snapshots")
    issues=[]
    seen=set()
    previous=None
    summary=[]
    for index,(at,data,sha) in enumerate(pages):
        ids=[int(r["external_id"]) for r in data["rows"]]
        if ids!=sorted(ids):
            issues.append({"page":data["page"],"issue":"unexpected-id-order"})
        overlap=len(seen.intersection(ids))
        if overlap:
            issues.append({"page":data["page"],"issue":"overlap","count":overlap})
        if previous is not None and ids and min(ids)<=previous:
            issues.append({"page":data["page"],"issue":"non-increasing-boundary"})
        if index<len(pages)-1 and len(ids)<data["page_size"]:
            issues.append({"page":data["page"],"issue":"partial-page-before-next"})
        seen.update(ids)
        if ids:
            previous=max(ids) if previous is None else max(previous,max(ids))
        summary.append({"page":data["page"],"offset":data["offset"],"rows":len(ids),
                        "captured_at":at.isoformat(),"sha256":sha})
    return {"status":"requires-review" if issues else "no-observed-anomaly",
            "store_id":first["store_id"],"query_sha256":first["query_sha256"],
            "pages":summary,"unique_ids":len(seen),"issues":issues,"coverage_verified":False,
            "provider_offset_semantics_verified":False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshots",nargs="+",type=Path)
    args=parser.parse_args()
    if not 2<=len(args.snapshots)<=3:
        parser.error("Select two or three snapshots")
    raw=[]
    for path in args.snapshots:
        with path.open("rb") as handle:
            raw.append(handle.read(MAX_BYTES+1))
    print(json.dumps(compare(raw,now=datetime.now(timezone.utc)),ensure_ascii=False))


if __name__=="__main__":
    main()
