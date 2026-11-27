#!/usr/bin/env bash
# Only the disposable GitHub Actions runner, never the dev host.
set -euo pipefail
[[ ${GITHUB_ACTIONS:-} == true && ${RUNNER_ENVIRONMENT:-} == github-hosted ]] || { echo 'Isolated hosted CI required'; exit 1; }
[[ $# == 2 && -f $1 && -f $2 ]] || { echo 'Pass validated Dropify ZIP and WooCommerce ZIP'; exit 1; }
dropify=$(realpath "$1")
woo=$(realpath "$2")
repo=$(cd "$(dirname "$0")/.." && pwd)
tag="bk-sandbox-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
[[ $tag =~ ^bk-sandbox-[0-9]+-[0-9]+$ ]]
network="$tag-net"
volume="$tag-wp"
db="$tag-db"
wp="$tag-wp"
dbvol="$tag-dbdata"
temp=$(mktemp -d)
chmod 755 "$temp"
cleanup() {
  docker rm -f "$wp" "$db" >/dev/null 2>&1 || true
  docker volume rm "$volume" "$dbvol" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  rm -rf -- "$temp"
}
# Refuse pre-existing resources; cleanup only unique resources created here.
for n in "$db" "$wp"; do if docker inspect "$n" >/dev/null 2>&1; then exit 1; fi; done
for v in "$volume" "$dbvol"; do if docker volume inspect "$v" >/dev/null 2>&1; then exit 1; fi; done
if docker network inspect "$network" >/dev/null 2>&1; then exit 1; fi
trap cleanup EXIT
cp "$dropify" "$temp/dropify.zip"
cp "$woo" "$temp/woocommerce.zip"
cp "$repo/tools/dropify-quarantine/sandbox-fixture.php" "$temp/sandbox-fixture.php"
cp "$repo/scripts/test-dropify-sandbox-http.php" "$temp/http.php"
chmod 644 "$temp/"*
for image in mariadb:11.4 wordpress:php8.3-apache wordpress:cli-php8.3; do
  docker pull "$image" >/dev/null
done
docker network create --internal "$network" >/dev/null
test "$(docker network inspect --format '{{.Internal}}' "$network")" = true
docker volume create "$volume" >/dev/null
docker volume create "$dbvol" >/dev/null
docker run -d --pull=never --name "$db" --network "$network" --network-alias db \
  -e MARIADB_DATABASE=fixture -e MARIADB_USER=fixture -e MARIADB_PASSWORD=ci-db-only \
  -e MARIADB_ROOT_PASSWORD=ci-root-only -v "$dbvol:/var/lib/mysql" mariadb:11.4 >/dev/null
common=(-e WORDPRESS_DB_HOST=db:3306 -e WORDPRESS_DB_NAME=fixture -e WORDPRESS_DB_USER=fixture \
  -e WORDPRESS_DB_PASSWORD=ci-db-only -e BAKATA_DROPIFY_SANDBOX=1 \
  -e "WORDPRESS_CONFIG_EXTRA=define('WP_ENVIRONMENT_TYPE','staging');" \
  -v "$volume:/var/www/html" -v "$temp:/fixtures:ro")
docker run -d --pull=never --name "$wp" --network "$network" "${common[@]}" wordpress:php8.3-apache >/dev/null
for i in $(seq 1 90); do
  if docker exec "$db" healthcheck.sh --connect --innodb_initialized >/dev/null 2>&1 &&
     docker exec "$wp" test -f /var/www/html/wp-config.php &&
     docker exec "$wp" test -f /var/www/html/wp-includes/version.php; then break; fi
  test "$i" -lt 90
  sleep 2
done
cli() {
  docker run --rm --pull=never --network "$network" --user 33:33 -e HOME=/tmp "${common[@]}" \
    wordpress:cli-php8.3 wp "$@"
}
cli core install --url=http://localhost --title='Dropify isolated fixture' --admin_user=sandbox_admin \
  --admin_password=ci-sandbox-only-password-2026 --admin_email=admin@example.invalid --skip-email
# The MU fixture blocks ALL external WP HTTP requests, independent of network isolation.
docker exec "$wp" sh -ec 'mkdir -p /var/www/html/wp-content/mu-plugins; cp /fixtures/sandbox-fixture.php /var/www/html/wp-content/mu-plugins/'
cli plugin install /fixtures/woocommerce.zip --activate
cli option update woocommerce_default_country CO
cli option update woocommerce_currency COP
cli user create sandbox_reader reader@example.invalid --role=subscriber --user_pass=ci-sandbox-only-password-2026
cli plugin install /fixtures/dropify.zip --activate
cli plugin is-active wc-dropi-integration
cli eval 'global $wpdb; $table=$wpdb->prefix."dropi_tokens"; if($wpdb->get_var($wpdb->prepare("SHOW TABLES LIKE %s",$wpdb->esc_like($table)))!==null) throw new RuntimeException("Activation migrated token table"); if($wpdb->query("CREATE TABLE `".$table."` (id int NOT NULL PRIMARY KEY, store tinytext NOT NULL, token varchar(1000) NOT NULL, create_prod_empr boolean, sync varchar(50))")===false) throw new RuntimeException("Fixture schema"); if($wpdb->insert($table,["id"=>7,"store"=>"Fixture store","token"=>"ci-only-token-canary","create_prod_empr"=>0,"sync"=>"MANUALMENTE"])!==1) throw new RuntimeException("Fixture token row");'
cli option update bk_fixture_http_calls 0
docker exec "$wp" php /fixtures/http.php disabled
test "$(cli option get bk_fixture_http_calls)" = 0
cli option update bk_fixture_expiry "$(($(date +%s)+600))"
cli option update bk_fixture_enabled 1
docker exec "$wp" php /fixtures/http.php subscriber
test "$(cli option get bk_fixture_http_calls)" = 0
docker exec "$wp" php /fixtures/http.php enabled > "$temp/snapshot.json"
test "$(cli option get bk_fixture_http_calls)" = 1
cli eval 'global $wpdb; foreach(["bk_fixture_unexpected_provider","bk_fixture_bad_request","bk_fixture_unsafe_hook"] as $key) if(get_option($key)!==false) throw new RuntimeException("Unexpected fixture behavior"); $name="bk_dropify_catalog_".hash("sha256","ci-wordpress-approval"); $rows=$wpdb->get_results($wpdb->prepare("SELECT autoload,option_value FROM $wpdb->options WHERE option_name=%s",$name)); if(count($rows)!==1||$rows[0]->autoload!=="no"||str_contains($rows[0]->option_value,"canary")) throw new RuntimeException("Invalid receipt"); if(wp_count_posts("product")->publish || wp_count_posts("product")->draft || wc_orders_count("processing")) throw new RuntimeException("Unexpected commercial mutation");'
PYTHONPATH="$repo/services/intelligence" python3 -m intelligence.dropify_bridge --db "$temp/catalog.sqlite" ingest "$temp/snapshot.json" --operator ci-wordpress
PYTHONPATH="$repo/services/intelligence" python3 -m intelligence.dropify_bridge --db "$temp/catalog.sqlite" candidates --store 7 --in-stock | python3 -c 'import json,sys; r=json.load(sys.stdin); assert len(r)==1 and r[0]["external_id"]=="96" and r[0]["base_price"]=="7000.25"'
echo 'Real WordPress/WooCommerce sandbox: activation, admin HTTP, MariaDB receipt and offline archive passed.'
