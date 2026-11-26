"""CI runtime gate for the Linux offline fixture container."""
import json
import os
from pathlib import Path
import resource


def main():
    if os.getuid() != 65532 or os.getgid() != 65532:
        raise RuntimeError("Unexpected runtime identity")
    if not os.statvfs("/app").f_flag & os.ST_RDONLY:
        raise RuntimeError("Application filesystem is writable")
    interfaces = sorted(p.name for p in Path("/sys/class/net").iterdir())
    if interfaces != ["lo"]:
        raise RuntimeError("Unexpected network interfaces")
    status = dict(line.split(":",1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
    if int(status["CapEff"].strip(),16) != 0 or status["NoNewPrivs"].strip() != "1":
        raise RuntimeError("Unexpected process privileges")
    # GitHub-hosted Linux runner uses cgroup v2. Fail closed if its accounting
    # layout changes; do not silently assume the limits are enforced.
    root = Path("/sys/fs/cgroup")
    memory = int((root/"memory.max").read_text().strip())
    quota, period = (root/"cpu.max").read_text().split()
    pids = int((root/"pids.max").read_text().strip())
    if memory != 128*1024*1024 or int(quota)*2 != int(period) or pids != 64:
        raise RuntimeError("Unexpected container resource limits")
    print(json.dumps({"uid":os.getuid(),"interfaces":interfaces,"memory_limit_bytes":memory,
                      "cpu_limit":0.5,"pids_limit":pids,
                      "probe_peak_rss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}))


if __name__ == "__main__":
    main()
