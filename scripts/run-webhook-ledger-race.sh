#!/usr/bin/env bash
# Disposable local Docker only; see docs/webhook-receipts.md.
set -Eeuo pipefail
cd "$(dirname "$0")/.."

BAKATA_RACE_MARKER=$(openssl rand -hex 32)
BAKATA_RACE_OWNER=$(openssl rand -hex 32)
suffix=$(openssl rand -hex 16)
if [[ ! $BAKATA_RACE_MARKER =~ ^[a-f0-9]{64}$ || ! $BAKATA_RACE_OWNER =~ ^[a-f0-9]{64}$ || ! $suffix =~ ^[a-f0-9]{32}$ ]]; then
    echo 'Invalid random values; refusing to create resources.' >&2
    exit 1
fi
export BAKATA_RACE_MARKER BAKATA_RACE_OWNER
project="bakata-receipt-race-$suffix"
compose=(docker compose -f scripts/compose-receipt-race.yaml -p "$project")
filters=(--filter "label=com.docker.compose.project=$project" --filter "label=bakata.receipt-race.owner=$BAKATA_RACE_OWNER")
created=0

cleanup() {
    local status=$? failed=0 id
    trap - EXIT
    # A second Ctrl-C/TERM must not interrupt ownership checks halfway through.
    trap '' INT TERM
    if (( created )); then
        # Both labels must match. Never use compose down -v or delete by name.
        local containers='' volumes='' networks=''
        containers=$(docker ps -aq "${filters[@]}") || failed=1
        volumes=$(docker volume ls -q "${filters[@]}") || failed=1
        networks=$(docker network ls -q "${filters[@]}") || failed=1
        for id in $containers; do docker rm -f "$id" >/dev/null || failed=1; done
        for id in $volumes; do docker volume rm "$id" >/dev/null || failed=1; done
        for id in $networks; do docker network rm "$id" >/dev/null || failed=1; done
        if (( failed )); then
            echo "Cleanup incomplete; inspect project $project and owner label before manual removal." >&2
            if (( status == 0 )); then status=1; fi
        fi
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Reject endpoint overrides and pin the inspected context for all subsequent calls.
if [[ ${DOCKER_HOST+x} || ${DOCKER_CONTEXT+x} ]]; then
    echo 'Unset DOCKER_HOST and DOCKER_CONTEXT; explicit local context required.' >&2
    exit 1
fi
context=$(docker context show)
endpoint=$(docker context inspect "$context" --format '{{(index .Endpoints "docker").Host}}')
case "$endpoint" in
    unix:///var/run/docker.sock)
        if [[ ! -S /var/run/docker.sock ]]; then
            echo 'Local Docker socket not found.' >&2; exit 1
        fi ;;
    npipe:////./pipe/dockerDesktopLinuxEngine) ;;
    *) echo "Refusing unverified Docker endpoint: $endpoint" >&2; exit 1 ;;
esac
export DOCKER_CONTEXT="$context"

# Check both Compose labels and all expected names before creating anything.
# Enumeration errors are fatal, unlike an inspect error which can mean either
# "not found" or "cannot contact Docker".
docker info >/dev/null
existing_containers=$(docker ps -aq --filter "label=com.docker.compose.project=$project")
existing_volumes=$(docker volume ls -q --filter "label=com.docker.compose.project=$project")
existing_networks=$(docker network ls -q --filter "label=com.docker.compose.project=$project")
container_names=$(docker ps -a --format '{{.Names}}')
volume_names=$(docker volume ls --format '{{.Name}}')
network_names=$(docker network ls --format '{{.Name}}')
if [[ -n "$existing_containers$existing_volumes$existing_networks" ]]; then
    echo "Project collision; refusing to create or clean anything: $project" >&2
    exit 1
fi
for name in "${project}_race_db" "${project}_race_wp"; do
    if [[ $'\n'"$volume_names"$'\n' == *$'\n'"$name"$'\n'* ]]; then
        echo "Volume name collision: $name" >&2; exit 1
    fi
done
if [[ $'\n'"$network_names"$'\n' == *$'\n'"${project}_isolated"$'\n'* ]]; then
    echo "Network name collision for $project" >&2; exit 1
fi
for name in "${project}-db-1" "${project}-wordpress-1"; do
    if [[ $'\n'"$container_names"$'\n' == *$'\n'"$name"$'\n'* ]]; then
        echo "Container name collision: $name" >&2; exit 1
    fi
done

echo "Disposable project: $project"
created=1
"${compose[@]}" up -d --wait db wordpress
"${compose[@]}" exec -T db mariadb -urace -psynthetic_race_password bakata_receipt_race \
    -e "CREATE TABLE bakata_race_isolation_marker (marker CHAR(64) NOT NULL); INSERT INTO bakata_race_isolation_marker VALUES ('$BAKATA_RACE_MARKER');"

deadline=$((SECONDS + 90))
until "${compose[@]}" exec -T wordpress sh -c 'test -s /var/www/html/wp-config.php && test -s /var/www/html/wp-includes/version.php'; do
    if (( SECONDS >= deadline )); then
        echo "WordPress files not ready within 90 seconds." >&2
        exit 1
    fi
    sleep 1
done
"${compose[@]}" run --rm cli wp core install --url=http://localhost:18937 \
    --title='Receipt race' --admin_user=raceadmin --admin_password=synthetic_admin_password \
    --admin_email=race@example.invalid --skip-email
"${compose[@]}" run --rm cli wp eval 'require "/tmp/receipt-race.php";'
