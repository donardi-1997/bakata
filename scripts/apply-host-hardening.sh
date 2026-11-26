#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Ejecutar como root'; exit 1; }
cd "$(dirname "$0")/.."
test -s /etc/nginx/.htpasswd-bakata
test -s /etc/letsencrypt/live/dev.bakata.store/fullchain.pem
test -s /etc/letsencrypt/live/dev.bakata.store/privkey.pem
backup=$(mktemp -d /root/bakata-host-backup.XXXXXXXX)
chmod 700 "$backup"
cp -a /etc/ssh /etc/nginx "$backup/"
rollback() {
  echo "Restaurando SSH y Nginx desde $backup" >&2
  rm -f /etc/ssh/sshd_config.d/00-bakata-hardening.conf
  cp -a "$backup/ssh/." /etc/ssh/
  rm -f /etc/nginx/sites-enabled/bakata-dev /etc/nginx/sites-enabled/bakata-default-deny
  rm -f /etc/nginx/sites-available/bakata-dev /etc/nginx/sites-available/bakata-default-deny
  cp -a "$backup/nginx/." /etc/nginx/
  sshd -t && systemctl reload ssh || true
  nginx -t && systemctl reload nginx || true
}
trap rollback ERR
install -m 644 infra/ssh/00-bakata-hardening.conf /etc/ssh/sshd_config.d/00-bakata-hardening.conf
sshd -t
sshd -T | grep -qx 'permitrootlogin no'
sshd -T | grep -qx 'passwordauthentication no'
install -d -m 755 /var/www/letsencrypt
install -m 644 infra/nginx/bakata-dev.conf /etc/nginx/sites-available/bakata-dev
install -m 644 infra/nginx/bakata-default-deny.conf /etc/nginx/sites-available/bakata-default-deny
ln -sfn /etc/nginx/sites-available/bakata-dev /etc/nginx/sites-enabled/bakata-dev
ln -sfn /etc/nginx/sites-available/bakata-default-deny /etc/nginx/sites-enabled/bakata-default-deny
rm -f /etc/nginx/sites-enabled/default
sed -i -E 's/ssl_protocols TLSv1 TLSv1\.1 TLSv1\.2 TLSv1\.3;/ssl_protocols TLSv1.2 TLSv1.3;/' /etc/nginx/nginx.conf
sed -i -E 's/^[[:space:]]*# server_tokens off;/\tserver_tokens off;/' /etc/nginx/nginx.conf
nginx -t
systemctl reload ssh nginx
trap - ERR
install -D -m 755 infra/letsencrypt/reload-nginx.sh /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
echo "Configuracion aplicada. Respaldo SSH/Nginx: $backup"
