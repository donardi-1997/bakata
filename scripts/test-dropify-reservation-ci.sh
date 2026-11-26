#!/bin/sh
# Runs inside the disposable CI WP-CLI container; no Dropify activation.
set -eu
test "${BAKATA_CI_FIXTURES:-}" = 1
fixture=/bakata-ci/scripts/test-dropify-reservation-ci.php
gate=$(mktemp -d)
trap 'rm -rf "$gate"' EXIT
output=$(BAKATA_DISPATCH_MODE=create wp eval-file "$fixture")
id=$(printf '%s\n' "$output" | sed -n 's/^CI_ORDER_ID=\([0-9][0-9]*\)$/\1/p')
case "$id" in ''|*[!0-9]*) exit 1;; esac
export BAKATA_DISPATCH_ORDER_ID="$id" BAKATA_DISPATCH_GATE="$gate"
BAKATA_DISPATCH_MODE=claim BAKATA_DISPATCH_WORKER=a wp eval-file "$fixture" > "$gate/result-a" &
a=$!
BAKATA_DISPATCH_MODE=claim BAKATA_DISPATCH_WORKER=b wp eval-file "$fixture" > "$gate/result-b" &
b=$!
status=0
wait "$a" || status=1
wait "$b" || status=1
test "$status" = 0
cat "$gate/result-a" "$gate/result-b"
test "$(grep -hxc CLAIMED "$gate/result-a" "$gate/result-b" | awk '{s+=$1} END {print s+0}')" = 1
test "$(grep -hxc BLOCKED "$gate/result-a" "$gate/result-b" | awk '{s+=$1} END {print s+0}')" = 1
BAKATA_DISPATCH_MODE=verify wp eval-file "$fixture"
