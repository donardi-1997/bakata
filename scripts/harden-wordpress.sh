#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
docker compose run --rm -T cli wp config set DISALLOW_FILE_EDIT true --raw
docker compose run --rm -T cli wp config set WP_DEBUG_DISPLAY false --raw
docker compose run --rm -T cli wp option update blog_public 0
