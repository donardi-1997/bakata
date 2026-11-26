"""Explicit operator CLI for the offline queue; never starts a daemon."""
import argparse
from contextlib import closing
import json
import sqlite3
import time

from .admin_export import fixture_snapshot
from .jobs import JobQueue


def run_once(queue: JobQueue, clock=lambda: int(time.time())) -> str | None:
    claim = queue.claim(clock())
    if claim is None:
        return None
    try:
        snapshot = fixture_snapshot()
    except Exception:
        queue.fail(claim, clock())
        return claim.job_id
    queue.succeed(claim, snapshot, clock())
    return claim.job_id


def main():
    parser = argparse.ArgumentParser(description="Offline fixture job queue")
    parser.add_argument("--db", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    enqueue = sub.add_parser("enqueue")
    enqueue.add_argument("job_id")
    enqueue.add_argument("--due",type=int,required=True)
    schedule = sub.add_parser("schedule")
    schedule.add_argument("schedule_id")
    schedule.add_argument("--interval",type=int,required=True)
    schedule.add_argument("--first-due",type=int,required=True)
    disable = sub.add_parser("disable")
    disable.add_argument("schedule_id")
    sub.add_parser("tick")
    sub.add_parser("run-once")
    sub.add_parser("list")
    for command in ("result","events"):
        sub.add_parser(command).add_argument("job_id")
    args = parser.parse_args()
    now = int(time.time())
    with closing(sqlite3.connect(args.db, timeout=5)) as db:
        queue = JobQueue(db)
        if args.command == "enqueue":
            data = {"queued":queue.enqueue(args.job_id, args.due, now)}
        elif args.command == "schedule":
            queue.configure_schedule(args.schedule_id,args.interval,args.first_due)
            data = {"configured":args.schedule_id}
        elif args.command == "disable":
            queue.disable_schedule(args.schedule_id)
            data = {"disabled":args.schedule_id}
        elif args.command == "tick":
            data = {"enqueued":queue.tick(now)}
        elif args.command == "run-once":
            data = {"job":run_once(queue)}
        elif args.command == "list":
            data = queue.list_jobs()
        elif args.command == "result":
            data = queue.result(args.job_id)
        else:
            data = queue.events(args.job_id)
        print(json.dumps(data,ensure_ascii=False))


if __name__ == "__main__":
    main()
