<?php
// Only after homepage QA in the disposable local CI store.
if (!defined('WP_CLI') || !WP_CLI || getenv('BAKATA_CI_FIXTURES') !== '1'
    || !in_array(wp_parse_url(home_url(), PHP_URL_HOST), ['localhost', '127.0.0.1'], true)
    || !function_exists('wc_get_products')) {
    throw new RuntimeException('Refusing fixtures outside isolated CI.');
}
$term = wp_insert_term('CI QA Shop Beta', 'product_cat', ['slug' => 'ci-qa-shop-beta']);
if (is_wp_error($term)) {
    throw new RuntimeException($term->get_error_message());
}
for ($i = 1; $i <= 13; $i++) {
    $p = new WC_Product_Simple();
    $p->set_name(sprintf('CI QA Shop %02d', $i));
    $p->set_status('publish');
    $p->set_catalog_visibility('visible');
    $p->set_regular_price((string) ($i * 10000));
    $p->set_stock_status('instock');
    $p->set_category_ids([(int) $term['term_id']]);
    $p->save();
}
echo "Disposable shop pagination fixtures created.\n";
