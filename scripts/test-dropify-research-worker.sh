#!/usr/bin/env bash
# Disposable hosted CI only. No AWS actions or supplier credentials.
set -euo pipefail
[[ ${GITHUB_ACTIONS:-} == true && ${RUNNER_ENVIRONMENT:-} == github-hosted ]]
[[ $# == 3 && -f $1 && -f $2 && -f $3 ]]
repo=$(cd "$(dirname "$0")/.." && pwd)
tag="bk-research-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
[[ $tag =~ ^bk-research-[0-9]+-[0-9]+$ ]]
temp=$(mktemp -d)
net="$tag-net"
db="$tag-db"
worker="$tag-worker"
image="$tag:fixture"
for name in "$db" "$worker"; do if docker inspect "$name" >/dev/null 2>&1; then exit 1; fi; done
if docker network inspect "$net" >/dev/null 2>&1; then exit 1; fi
if docker image inspect "$image" >/dev/null 2>&1; then exit 1; fi
cleanup() {
  docker rm -fv "$worker" "$db" >/dev/null 2>&1 || true
  docker network rm "$net" >/dev/null 2>&1 || true
  docker image rm "$image" >/dev/null 2>&1 || true
  rm -rf -- "$temp"
}
trap cleanup EXIT
sha=$(sha256sum "$2" | cut -d ' ' -f 1)
python3 "$repo/scripts/prepare-dropify-research-context.py" "$1" "$2" "$3" "$temp/context" --candidate-sha256 "$sha"
for base in mariadb:11.4 wordpress:php8.3-apache wordpress:cli-php8.3; do
  docker pull "$base" >/dev/null
done
docker build --network none --tag "$image" "$temp/context"
test "$(docker image inspect --format '{{.Config.User}}' "$image")" = 33:33
# No runtime flag => no WordPress bootstrap.
if docker run --rm --network none "$image"; then echo 'Expected disabled worker'; exit 1; fi
docker network create --internal "$net" >/dev/null
test "$(docker network inspect --format '{{.Internal}}' "$net")" = true
docker run -d --pull=never --name "$db" --network "$net" --memory 512m --cpus .5 \
  -e MARIADB_DATABASE=fixture -e MARIADB_USER=fixture -e MARIADB_PASSWORD=ci-research-only \
  -e MARIADB_ROOT_PASSWORD=ci-research-root-only mariadb:11.4 >/dev/null
for i in $(seq 1 60); do
  if docker exec "$db" healthcheck.sh --connect --innodb_initialized >/dev/null 2>&1; then break; fi
  test "$i" -lt 60
  sleep 2
done
# Shared network namespace models Fargate task-local localhost communication.
# No published ports, production mounts, external routes or Docker socket.
common=(--pull=never --network "container:$db" --read-only --tmpfs /tmp:rw,nosuid,nodev,noexec,size=64m,mode=1777 \
  --memory 768m --cpus .75 --pids-limit 64 --cap-drop ALL --security-opt no-new-privileges \
  -e BAKATA_RESEARCH_FIXTURE=1)
timeout 180 docker run --name "$worker" "${common[@]}" "$image" > "$temp/pages.jsonl"
test "$(docker inspect --format '{{.State.ExitCode}}' "$worker")" = 0
test "$(docker inspect --format '{{.HostConfig.ReadonlyRootfs}}' "$worker")" = true
test "$(docker inspect --format '{{.HostConfig.Memory}}' "$worker")" = 805306368
test -z "$(docker port "$db")"
# The ephemeral DB is not a durable authorization ledger. Reusing it is denied.
if timeout 30 docker run --rm "${common[@]}" "$image" >/dev/null 2>&1; then echo 'Expected nonempty database rejection'; exit 1; fi
PYTHONPATH="$repo/services/intelligence" python3 - "$temp/pages.jsonl" "$temp/catalog.sqlite" <<'PY'
from datetime import datetime,timezone
from pathlib import Path
import sqlite3,sys
from intelligence.dropify_bridge import BridgeArchive,decode
from intelligence.dropify_pagination import compare
raw=Path(sys.argv[1]).read_bytes().splitlines()
assert len(raw)==2
now=datetime.now(timezone.utc)
assert all(b"canary" not in x for x in raw)
assert [len(decode(x,now)[1]["rows"]) for x in raw]==[10,3]
summary=compare(raw,now=now)
assert summary["status"]=="no-observed-anomaly" and summary["unique_ids"]==13
with sqlite3.connect(sys.argv[2]) as db:
    archive=BridgeArchive(db)
    assert sum(archive.ingest(x,"ci-research",now)["inserted"] for x in raw)==13
    assert len(archive.candidates(store="7",in_stock=True))==13
    assert sum(archive.ingest(x,"ci-research",now)["inserted"] for x in raw)==0
print("CLI-only research worker: 13 distinct synthetic products, localhost DB, immutable root and no commercial mutations.")
PY
