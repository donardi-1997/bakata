#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ ! -f .env ]]; then
  echo "Copia .env.example a .env y configura las contraseñas locales." >&2
  exit 1
fi
docker compose config --quiet
docker compose up -d db wordpress
for ((i=0; i<90; i++)); do
  if docker compose exec -T wordpress test -f /var/www/html/wp-config.php &&
     docker compose exec -T wordpress test -f /var/www/html/wp-includes/version.php &&
     docker compose exec -T wordpress test -f /var/www/html/.htaccess; then
    break
  fi
  if ((i == 89)); then
    echo "WordPress no terminó su inicialización; revisa docker compose logs wordpress." >&2
    exit 1
  fi
  sleep 2
done
docker compose run --rm -T cli sh -eu -c '
  if ! wp core is-installed; then
    wp core install --url="$WP_URL" --title="$WP_TITLE" --admin_user="$WP_ADMIN_USER" --admin_password="$WP_ADMIN_PASSWORD" --admin_email="$WP_ADMIN_EMAIL" --skip-email
    wp option update timezone_string America/Bogota
    wp option update blogdescription "Descubre soluciones para tu día a día"
    wp rewrite structure "/%postname%/"
    wp option update woocommerce_currency COP
    wp option update woocommerce_default_country CO
  fi
  if ! wp plugin is-installed woocommerce; then
    if [ -n "$WC_VERSION" ]; then
      wp plugin install woocommerce --version="$WC_VERSION"
    else
      wp plugin install woocommerce
    fi
  fi
  wp plugin activate woocommerce
  wp plugin activate bakata-core
  wp theme activate bakata
  wp rewrite flush
  wp plugin list
  wp theme list
  printf "\nTienda local: %s\n" "$WP_URL"
'
