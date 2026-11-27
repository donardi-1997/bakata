<?php
// Fixtures only in the disposable GitHub Actions WordPress instance.
if (!defined('WP_CLI') || !WP_CLI || getenv('BAKATA_CI_FIXTURES') !== '1'
    || !in_array(wp_parse_url(home_url(), PHP_URL_HOST), ['localhost', '127.0.0.1'], true)
    || !function_exists('wc_get_products')) {
    throw new RuntimeException('Refusing fixtures outside isolated CI.');
}
if (wc_get_products(['limit' => 1, 'return' => 'ids'])) {
    throw new RuntimeException('Expected empty CI catalog.');
}
$term = wp_insert_term('CI Category Alpha', 'product_cat', ['slug' => 'ci-category-alpha']);
if (is_wp_error($term)) {
    throw new RuntimeException($term->get_error_message());
}
$child = wp_insert_term('CI Category Child', 'product_cat', [
    'slug' => 'ci-category-child', 'parent' => (int) $term['term_id'],
]);
if (is_wp_error($child)) {
    throw new RuntimeException($child->get_error_message());
}
$collection = wp_insert_term('CI Editorial Collection', 'product_tag', ['slug' => 'hogar-en-armonia']);
if (is_wp_error($collection)) {
    throw new RuntimeException($collection->get_error_message());
}
foreach ([
    ['CI Featured Visible', 'publish', 'visible', true, 'instock'],
    ['CI Featured Catalog Only', 'publish', 'catalog', true, 'instock'],
    ['CI Featured Hidden', 'publish', 'hidden', true, 'instock'],
    ['CI Featured Search Only', 'publish', 'search', true, 'instock'],
    ['CI Featured Draft', 'draft', 'visible', true, 'instock'],
    ['CI Not Featured', 'publish', 'visible', false, 'instock'],
] as [$name, $status, $visibility, $featured, $stock]) {
    $p = new WC_Product_Simple();
    $p->set_name($name);
    $p->set_status($status);
    $p->set_catalog_visibility($visibility);
    $p->set_featured($featured);
    $p->set_regular_price('129900');
    $p->set_stock_status($stock);
    $p->set_category_ids($name === 'CI Featured Visible'
        ? [(int) $term['term_id'], (int) $child['term_id']]
        : [(int) $term['term_id']]);
    if ($name === 'CI Featured Visible') { $p->set_tag_ids([(int) $collection['term_id']]); }
    $p->save();
}
echo "Disposable CI catalog created.\n";
