<?php
// Synthetic customers and cancelled order records in disposable CI only.
if (!defined('WP_CLI') || !WP_CLI || getenv('BAKATA_CI_FIXTURES') !== '1'
    || !in_array(wp_parse_url(home_url(), PHP_URL_HOST), ['localhost', '127.0.0.1'], true)
    || !class_exists('WC_Customer') || !class_exists('WC_Order')) {
    throw new RuntimeException('Refusing fixtures outside isolated CI.');
}
$password = getenv('BAKATA_CI_ACCOUNT_PASSWORD');
if (!is_string($password) || strlen($password) < 24) {
    throw new RuntimeException('Missing ephemeral fixture credential.');
}
add_filter('pre_wp_mail', '__return_true');
update_option('woocommerce_enable_myaccount_registration', 'yes');
update_option('woocommerce_registration_generate_username', 'yes');
update_option('woocommerce_registration_generate_password', 'yes');
$ids = [];
foreach (['own', 'other'] as $kind) {
    $username = 'ci-bakata-account-' . $kind;
    $email = $username . '@example.invalid';
    $id = wp_insert_user([
        'user_login' => $username,
        'user_email' => $email,
        'user_pass' => $kind === 'own' ? $password : wp_generate_password(32, true, true),
        'role' => 'customer',
        'first_name' => 'CI',
        'last_name' => 'Fixture',
        'display_name' => 'CI Customer ' . $kind,
    ]);
    if (is_wp_error($id)) { throw new RuntimeException($id->get_error_message()); }
    $customer = new WC_Customer($id);
    foreach (['billing', 'shipping'] as $address) {
        foreach ([
            'first_name' => 'CI', 'last_name' => 'Fixture', 'country' => 'CO',
            'state' => 'CO-DC', 'city' => 'Bogotá', 'address_1' => 'Calle de prueba 123',
            'postcode' => '', 'phone' => '3000000000',
        ] as $field => $value) {
            $setter = 'set_' . $address . '_' . $field;
            if (is_callable([$customer, $setter])) { $customer->$setter($value); }
        }
    }
    $customer->set_billing_email($email);
    $customer->save();
    // No checkout, payment, stock reduction or fulfillment. Cancelled historical fixture.
    $order = new WC_Order();
    $order->set_customer_id($id);
    $order->set_created_via('ci-fixture');
    $order->set_currency('COP');
    $order->set_status('cancelled');
    $order->set_billing_first_name('CI');
    $order->set_billing_last_name('Fixture');
    $order->set_billing_email($email);
    $item = new WC_Order_Item_Product();
    $item->set_name('CI Account Order ' . $kind);
    $item->set_quantity(1);
    $item->set_subtotal('25000');
    $item->set_total('25000');
    $order->add_item($item);
    $order->calculate_totals(false);
    $order->save();
    $ids[$kind] = $order->get_id();
}
echo 'BAKATA_CI_OWN_ORDER=' . $ids['own'] . "\n";
echo 'BAKATA_CI_OTHER_ORDER=' . $ids['other'] . "\n";
