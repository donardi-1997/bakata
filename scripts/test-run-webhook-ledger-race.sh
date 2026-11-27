#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
dir=$(mktemp -d)
trap 'rm -f "$dir/docker" "$dir/openssl" "$dir/log" "$dir/random-log" "$dir/output"; rmdir "$dir"' EXIT
cat > "$dir/openssl" <<'MOCK'
#!/usr/bin/env bash
echo call >> "$RANDOM_LOG"
count=$(wc -l < "$RANDOM_LOG")
if [[ $MOCK_MODE == "random-fail-$count" ]]; then exit 47; fi
if [[ $MOCK_MODE == "random-invalid-$count" ]]; then echo invalid; exit 0; fi
if [[ $* == 'rand -hex 32' ]]; then printf '%064d\n' 0
elif [[ $* == 'rand -hex 16' ]]; then printf '%032d\n' 0
else exit 99; fi
MOCK
cat > "$dir/docker" <<'MOCK'
#!/usr/bin/env bash
echo "$*" >> "$MOCK_LOG"
if [[ $MOCK_MODE == selective && $* == *bakata.receipt-race.owner=* ]]; then
    # The synthetic inventory also contains foreign objects; return owned
    # objects only when both exact filters are supplied.
    if [[ $* != *"label=com.docker.compose.project=bakata-receipt-race-00000000000000000000000000000000"* \
        || $* != *"label=bakata.receipt-race.owner=0000000000000000000000000000000000000000000000000000000000000000"* ]]; then
        echo foreign-object
        exit 0
    fi
fi
case "$*" in
  'context show') if [[ $MOCK_MODE == context-fail ]]; then exit 43; fi; echo mock ;;
  'context inspect '*)
    if [[ $MOCK_MODE == inspect-fail ]]; then exit 48; fi
    if [[ $MOCK_MODE == remote ]]; then echo tcp://remote.example:2376
    else echo npipe:////./pipe/dockerDesktopLinuxEngine; fi ;;
  'info') if [[ $MOCK_MODE == info-fail ]]; then exit 44; fi ;;
  'ps -aq '*)
    if [[ $MOCK_MODE == project-collision && $* != *bakata.receipt-race.owner=* ]]; then echo foreign-project-container; fi
    if [[ $MOCK_MODE == *cleanup-fail && $(grep -c '^compose .* up ' "$MOCK_LOG") -gt 0 ]]; then exit 55; fi
    if [[ $MOCK_MODE == selective && $* == *bakata.receipt-race.owner=* && $(grep -c '^compose .* up ' "$MOCK_LOG") -gt 0 ]]; then echo own-container; fi ;;
  'volume ls -q '*|'network ls -q '*)
    if [[ $MOCK_MODE == selective && $* == *bakata.receipt-race.owner=* ]]; then
      if [[ $* == volume* ]]; then echo own-volume; else echo own-network; fi
    fi ;;
  'ps -a --format '*)
    if [[ $MOCK_MODE == enumerate-fail ]]; then exit 42; fi
    if [[ $MOCK_MODE == container-collision ]]; then echo bakata-receipt-race-00000000000000000000000000000000-db-1; fi ;;
  'volume ls --format '*)
    if [[ $MOCK_MODE == volume-fail ]]; then exit 45; fi
    if [[ $MOCK_MODE == volume-collision ]]; then echo bakata-receipt-race-00000000000000000000000000000000_race_db; fi ;;
  'network ls --format '*)
    if [[ $MOCK_MODE == network-fail ]]; then exit 46; fi
    if [[ $MOCK_MODE == network-collision ]]; then echo bakata-receipt-race-00000000000000000000000000000000_isolated; fi ;;
  'compose '*)
    if [[ $MOCK_MODE == run-fail* && $* == *' wp eval '* ]]; then exit 42; fi ;;
  'rm -f own-container'|'volume rm own-volume'|'network rm own-network') ;;
  *) echo "Unexpected docker call: $*" >&2; exit 99 ;;
esac
MOCK
chmod +x "$dir/docker" "$dir/openssl"
export PATH="$dir:$PATH" MOCK_LOG="$dir/log" RANDOM_LOG="$dir/random-log"
run_case() {
    local mode=$1 expected=$2 result
    : > "$MOCK_LOG"
    : > "$RANDOM_LOG"
    set +e
    env -u DOCKER_HOST -u DOCKER_CONTEXT MOCK_MODE="$mode" bash scripts/run-webhook-ledger-race.sh >"$dir/output" 2>&1
    result=$?
    set -e
    if [[ $result != "$expected" ]]; then
        cat "$dir/output" >&2
        echo "$mode: expected $expected, got $result" >&2; exit 1
    fi
}
run_case remote 1
if grep -q '^compose ' "$MOCK_LOG"; then echo 'Remote endpoint reached Compose.' >&2; exit 1; fi
run_case context-fail 43
run_case inspect-fail 48
run_case info-fail 44
run_case enumerate-fail 42
if grep -q '^compose ' "$MOCK_LOG"; then echo 'Enumeration failure reached Compose.' >&2; exit 1; fi
run_case volume-fail 45
if grep -q '^compose ' "$MOCK_LOG"; then echo 'Volume enumeration failure reached Compose.' >&2; exit 1; fi
run_case network-fail 46
if grep -q '^compose ' "$MOCK_LOG"; then echo 'Network enumeration failure reached Compose.' >&2; exit 1; fi
: > "$MOCK_LOG"
set +e
env -u DOCKER_CONTEXT DOCKER_HOST=tcp://remote.example:2376 MOCK_MODE=success bash scripts/run-webhook-ledger-race.sh >"$dir/output" 2>&1
result=$?
set -e
if [[ $result != 1 || -s $MOCK_LOG ]]; then echo 'DOCKER_HOST override not rejected before Docker.' >&2; exit 1; fi
set +e
env -u DOCKER_HOST DOCKER_CONTEXT=remote MOCK_MODE=success bash scripts/run-webhook-ledger-race.sh >"$dir/output" 2>&1
result=$?
set -e
if [[ $result != 1 || -s $MOCK_LOG ]]; then echo 'DOCKER_CONTEXT override not rejected before Docker.' >&2; exit 1; fi
for n in 1 2 3; do
    run_case "random-fail-$n" 47
    if [[ -s $MOCK_LOG ]]; then echo 'Docker called after random generator failure.' >&2; exit 1; fi
    run_case "random-invalid-$n" 1
    if [[ -s $MOCK_LOG ]]; then echo 'Docker called with invalid random value.' >&2; exit 1; fi
done
for collision in project container volume network; do
    run_case "$collision-collision" 1
    if grep -Eq '^(compose |rm |volume rm |network rm )' "$MOCK_LOG"; then echo "Unsafe action after $collision collision." >&2; exit 1; fi
done
run_case run-fail 42
run_case cleanup-fail 1
run_case run-fail-cleanup-fail 42
run_case selective 0
for action in 'rm -f own-container' 'volume rm own-volume' 'network rm own-network'; do
    if ! grep -Fxq "$action" "$MOCK_LOG"; then echo "Missing selective cleanup: $action" >&2; exit 1; fi
done
if grep -E '^(rm |volume rm |network rm )' "$MOCK_LOG" | grep -Ev '^(rm -f own-container|volume rm own-volume|network rm own-network)$'; then
    echo 'Cleanup attempted to remove an unowned resource.' >&2; exit 1
fi
run_case success 0
echo 'Wrapper mocks: endpoint rejection, fail-closed enumeration, status preservation, cleanup failure and success passed.'
