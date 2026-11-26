#!/usr/bin/env bash
# Root-only local and S3 recovery points.
set -euo pipefail
umask 077
[[ $EUID == 0 ]] || { echo 'Requiere root'; exit 1; }
base=/var/backups/bakata
install -d -o root -g root -m 700 "$base"
exec 9>/run/lock/bakata-deploy.lock
flock -w 120 9
cd /home/ubuntu/bakata
# Refuse to start when free space is less than 2 GiB.
available=$(df -Pk "$base" | awk 'NR==2 {print $4}')
(( available >= 2097152 )) || { echo 'Espacio insuficiente'; exit 1; }
stamp=$(date -u +%Y%m%dT%H%M%SZ)
stage=$(mktemp -d "$base/.partial.XXXXXXXX")
trap 'rm -rf -- "$stage"' EXIT
docker compose exec -T db sh -ec '
  export MYSQL_PWD="$MARIADB_ROOT_PASSWORD"
  exec mariadb-dump --user=root --single-transaction --quick --routines --events --triggers --databases "$MARIADB_DATABASE"
' | gzip -c > "$stage/database.sql.gz"
docker compose exec -T wordpress tar -C /var/www/html -czf - . > "$stage/wordpress.tar.gz"
tar -C / -czf "$stage/host-config.tar.gz" \
  home/ubuntu/bakata/.env \
  etc/nginx/sites-available/bakata-dev \
  etc/nginx/sites-available/bakata-default-deny \
  etc/nginx/.htpasswd-bakata \
  etc/ssh/sshd_config.d/00-bakata-hardening.conf \
  etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
runuser -u ubuntu -- git -C /home/ubuntu/bakata rev-parse HEAD > "$stage/git-commit"
docker inspect --format '{{.Name}} {{.Image}}' bakata-db-1 bakata-wordpress-1 > "$stage/image-ids"
gzip -t "$stage/database.sql.gz"
tar -tzf "$stage/wordpress.tar.gz" >/dev/null
tar -tzf "$stage/host-config.tar.gz" >/dev/null
(
  cd "$stage"
  sha256sum database.sql.gz wordpress.tar.gz host-config.tar.gz git-commit image-ids > SHA256SUMS
  sha256sum -c SHA256SUMS
)
mv -T -- "$stage" "$base/backup-$stamp"
trap - EXIT
# Remove only our own completed backup directories older than seven days.
find "$base" -mindepth 1 -maxdepth 1 -regextype posix-extended -type d \
  -regex "$base/backup-[0-9]{8}T[0-9]{6}Z" -mmin +10080 -exec rm -rf -- {} +
echo "Backup local verificado: $base/backup-$stamp"
du -sh "$base/backup-$stamp"

/usr/bin/python3 /usr/local/sbin/bakata-upload-backup "$base/backup-$stamp"
