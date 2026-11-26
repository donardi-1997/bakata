<?php
// Disposable Colombian shipping and offline payment display, never in dev/prod.
if (!defined('WP_CLI') || !WP_CLI || getenv('BAKATA_CI_FIXTURES') !== '1'
    || !in_array(wp_parse_url(home_url(), PHP_URL_HOST), ['localhost', '127.0.0.1'], true)
    || !class_exists('WC_Shipping_Zone')) {
    throw new RuntimeException('Refusing fixtures outside isolated CI.');
}
update_option('woocommerce_default_country', 'CO');
update_option('woocommerce_allowed_countries', 'specific');
update_option('woocommerce_specific_allowed_countries', ['CO']);
update_option('woocommerce_ship_to_countries', 'specific');
update_option('woocommerce_specific_ship_to_countries', ['CO']);
update_option('woocommerce_enable_guest_checkout', 'yes');
$zone = new WC_Shipping_Zone();
$zone->set_zone_name('CI QA Colombia');
$zone->set_zone_order(0);
$zone->add_location('CO', 'country');
$zone->save();
$instance = $zone->add_shipping_method('flat_rate');
if (!$instance) { throw new RuntimeException('Missing fixture shipping method'); }
update_option('woocommerce_flat_rate_' . $instance . '_settings', [
    'title' => 'CI QA Delivery',
    'tax_status' => 'none',
    'cost' => '12000',
]);
$settings = get_option('woocommerce_bacs_settings', []);
$settings['enabled'] = 'yes';
$settings['title'] = 'CI QA Offline payment';
$settings['description'] = 'Disposable CI only. No payment will be submitted.';
update_option('woocommerce_bacs_settings', $settings);
echo "Disposable checkout configuration created.\n";
