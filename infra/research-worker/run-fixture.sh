#!/bin/sh
set -eu
umask 077
test "$#" -eq 0
test "${BAKATA_RESEARCH_FIXTURE:-}" = 1
test "${BAKATA_DROPIFY_SANDBOX:-}" = 1
# Refuse nonempty DB; don't resume a destroyed task with ephemeral receipts.
php -r '$db=new mysqli("127.0.0.1","fixture","ci-research-only","fixture",3306); if($db->query("SHOW TABLES")->num_rows!==0) exit(1);'
wpcli() { wp --path=/opt/bakata/wp "$@"; }
wpcli core install --url=http://localhost --title='Isolated research fixture' --admin_user=sandbox_admin --admin_email=admin@example.invalid --admin_password=ci-research-admin-only --skip-email >&2
wpcli plugin activate woocommerce wc-dropi-integration >&2
wpcli option update woocommerce_default_country CO >&2
wpcli option update woocommerce_currency COP >&2
wpcli eval 'global $wpdb; $table=$wpdb->prefix."dropi_tokens"; if($wpdb->query("CREATE TABLE `".$table."` (id int NOT NULL PRIMARY KEY, store tinytext NOT NULL, token varchar(1000) NOT NULL, create_prod_empr boolean, sync varchar(50))")===false) throw new RuntimeException("Fixture schema"); if($wpdb->insert($table,["id"=>7,"store"=>"Fixture store","token"=>"ci-only-token-canary","create_prod_empr"=>0,"sync"=>"MANUALMENTE"])!==1) throw new RuntimeException("Fixture token");' >&2
wpcli option update bk_fixture_http_calls 0 >&2
wpcli option update bk_fixture_batch_expiry "$(($(date +%s)+600))" >&2
wpcli option update bk_fixture_batch_enabled 1 >&2
wpcli --user=sandbox_admin eval-file /opt/bakata/dropify-capture-page.php ci-paged-capture 7 1 > /tmp/page1.json
sleep 10
wpcli --user=sandbox_admin eval-file /opt/bakata/dropify-capture-page.php ci-paged-capture 7 2 > /tmp/page2.json
if wpcli --user=sandbox_admin eval-file /opt/bakata/dropify-capture-page.php ci-paged-capture 7 3 >/dev/null 2>&1; then exit 1; fi
test "$(wpcli option get bk_fixture_http_calls)" = 2
wpcli eval 'foreach(["bk_fixture_unexpected_provider","bk_fixture_bad_request","bk_fixture_unsafe_hook"] as $key) if(get_option($key)!==false) throw new RuntimeException("Unexpected fixture behavior"); if(wp_count_posts("product")->publish || wp_count_posts("product")->draft || wc_orders_count("processing")) throw new RuntimeException("Unexpected mutation");' >&2
cat /tmp/page1.json /tmp/page2.json
