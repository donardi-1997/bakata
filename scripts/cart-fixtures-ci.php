<?php
// Create a coupon only in the isolated CI store, after prior suites.
if (!defined('WP_CLI') || !WP_CLI || getenv('BAKATA_CI_FIXTURES') !== '1'
    || !in_array(wp_parse_url(home_url(), PHP_URL_HOST), ['localhost', '127.0.0.1'], true)
    || !class_exists('WC_Coupon')) {
    throw new RuntimeException('Refusing fixtures outside isolated CI.');
}
if (wc_get_coupon_id_by_code('ci-bakata-cart-5000')) {
    throw new RuntimeException('Fixture coupon already exists.');
}
update_option('woocommerce_enable_coupons', 'yes');
$coupon = new WC_Coupon();
$coupon->set_code('ci-bakata-cart-5000');
$coupon->set_discount_type('fixed_cart');
$coupon->set_amount('5000');
$coupon->save();
echo "Disposable cart coupon configured.\n";
