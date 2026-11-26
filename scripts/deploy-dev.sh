#!/usr/bin/env bash
# Instalar como /usr/local/sbin/bakata-deploy-dev, root:root 0755.
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Requiere root'; exit 1; }
target=$1
[[ $target =~ ^[0-9a-f]{40}$ ]] || { echo 'SHA invalido'; exit 1; }
exec 9>/run/lock/bakata-deploy.lock
flock -w 120 9
cd /home/ubuntu/bakata
git_user() { runuser -u ubuntu -- git -C /home/ubuntu/bakata "$@"; }
[[ -z $(git_user status --porcelain) ]] || { echo 'Repositorio con cambios locales'; exit 1; }
[[ $(git_user branch --show-current) == main ]] || { echo 'Rama incorrecta'; exit 1; }
git_user fetch origin main
git_user merge-base --is-ancestor "$target" origin/main || { echo 'Commit fuera de main'; exit 1; }
current=$(git_user rev-parse HEAD)
if [[ "$target" != "$current" ]] && git_user merge-base --is-ancestor "$target" "$current"; then
  echo 'Commit anterior al desplegado; se omite'
  exit 0
fi
git_user merge --ff-only "$target"
docker compose config --quiet
docker compose up -d --wait --wait-timeout 180 db wordpress
docker compose run --rm -T cli wp core is-installed
docker compose run --rm -T cli wp plugin is-active woocommerce
docker compose run --rm -T cli wp plugin is-active bakata-core
docker compose run --rm -T cli wp theme is-active bakata
curl --fail --silent --show-error --retry 5 --retry-all-errors --max-time 15 \
  -H 'Host: dev.bakata.store' -H 'X-Forwarded-Proto: https' \
  http://127.0.0.1:8080/ -o /dev/null
[[ $(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' https://dev.bakata.store/) == 401 ]]
echo "Deploy verificado: $(git_user rev-parse HEAD)"
