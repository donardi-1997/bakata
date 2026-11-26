<?php
// Only disposable local CI, after the homepage and shop suites.
if (!defined('WP_CLI') || !WP_CLI || getenv('BAKATA_CI_FIXTURES') !== '1'
    || !in_array(wp_parse_url(home_url(), PHP_URL_HOST), ['localhost', '127.0.0.1'], true)
    || !function_exists('wc_get_products')) {
    throw new RuntimeException('Refusing fixtures outside isolated CI.');
}
require_once ABSPATH . 'wp-admin/includes/image.php';
$source = get_theme_file_path('assets/images/hero-editorial.webp');
$bytes = file_get_contents($source);
if (!$bytes) { throw new RuntimeException('Missing local CI gallery source.'); }
$images = [];
foreach (['CI gallery front', 'CI gallery detail'] as $title) {
    $upload = wp_upload_bits(sanitize_title($title) . '.webp', null, $bytes);
    if ($upload['error']) { throw new RuntimeException($upload['error']); }
    $id = wp_insert_attachment(['post_title'=>$title, 'post_mime_type'=>'image/webp', 'post_status'=>'inherit'], $upload['file'], 0, true);
    if (is_wp_error($id) || !$id) { throw new RuntimeException('Attachment creation failed.'); }
    wp_update_attachment_metadata($id, wp_generate_attachment_metadata($id, $upload['file']));
    update_post_meta($id, '_wp_attachment_image_alt', $title);
    $images[] = $id;
}
$term = wp_insert_term('CI QA Product Detail', 'product_cat', ['slug'=>'ci-qa-product-detail']);
if (is_wp_error($term)) { throw new RuntimeException($term->get_error_message()); }
$category = (int) $term['term_id'];
$simple = new WC_Product_Simple();
$simple->set_name('CI PDP Simple');
$simple->set_slug('ci-pdp-simple');
$simple->set_status('publish');
$simple->set_regular_price('85000');
$simple->set_sale_price('75000');
$simple->set_manage_stock(true);
$simple->set_stock_quantity(5);
$simple->set_description('CI long description only.');
$simple->set_short_description('CI short description only.');
$simple->set_image_id($images[0]);
$simple->set_gallery_image_ids([$images[1]]);
$simple->set_category_ids([$category]);
$simple->set_reviews_allowed(false);
$simple->save();
$variable = new WC_Product_Variable();
$variable->set_name('CI PDP Variable');
$variable->set_slug('ci-pdp-variable');
$variable->set_status('publish');
$variable->set_description('CI variable description only.');
$variable->set_image_id($images[0]);
$variable->set_gallery_image_ids([$images[1]]);
$variable->set_category_ids([$category]);
$variable->set_reviews_allowed(false);
$attribute = new WC_Product_Attribute();
$attribute->set_id(0);
$attribute->set_name('Color');
$attribute->set_options(['Verde', 'Arena']);
$attribute->set_visible(true);
$attribute->set_variation(true);
$variable->set_attributes([$attribute]);
$variable->save();
foreach ([['Verde', '95000', 5], ['Arena', '105000', 0]] as [$color, $price, $qty]) {
    $variation = new WC_Product_Variation();
    $variation->set_parent_id($variable->get_id());
    $variation->set_status('publish');
    $variation->set_attributes(['color'=>$color]);
    $variation->set_regular_price($price);
    $variation->set_manage_stock(true);
    $variation->set_stock_quantity($qty);
    $variation->set_stock_status($qty > 0 ? 'instock' : 'outofstock');
    $variation->save();
}
WC_Product_Variable::sync($variable->get_id());
$empty = new WC_Product_Simple();
$empty->set_name('CI PDP Sold Out');
$empty->set_slug('ci-pdp-sold-out');
$empty->set_status('publish');
$empty->set_regular_price('50000');
$empty->set_manage_stock(true);
$empty->set_stock_quantity(0);
$empty->set_stock_status('outofstock');
$empty->set_category_ids([$category]);
$empty->set_reviews_allowed(false);
$empty->save();
echo "Disposable product fixtures created.\n";
