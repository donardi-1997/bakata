<?php
declare(strict_types=1);

if (!defined('WP_CLI') || !WP_CLI || getenv('BAKATA_CI_FIXTURES') !== '1'
    || !in_array(wp_parse_url(home_url(), PHP_URL_HOST), ['localhost', '127.0.0.1'], true)
    || !function_exists('wc_create_order')) {
    throw new RuntimeException('Refusing dispatch fixtures outside isolated CI.');
}
require __DIR__ . '/../tools/dropify-quarantine/dispatch-reservation.php';

$mode = getenv('BAKATA_DISPATCH_MODE');
if ($mode === 'create') {
    $order = wc_create_order(['status' => 'pending', 'created_via' => 'bakata-ci']);
    if (!$order instanceof WC_Order) {
        throw new RuntimeException('Synthetic order could not be created');
    }
    echo 'CI_ORDER_ID=' . $order->get_id() . PHP_EOL;
    return;
}
$id = filter_var(getenv('BAKATA_DISPATCH_ORDER_ID'), FILTER_VALIDATE_INT, ['options' => ['min_range' => 1]]);
$order = $id ? wc_get_order($id) : false;
if (!$order instanceof WC_Order || $order->get_created_via() !== 'bakata-ci') {
    throw new RuntimeException('Synthetic order required');
}
if ($mode === 'claim') {
    $worker = getenv('BAKATA_DISPATCH_WORKER');
    $gate = getenv('BAKATA_DISPATCH_GATE');
    if (!in_array($worker, ['a', 'b'], true) || !is_string($gate) || !is_dir($gate)) {
        throw new RuntimeException('Invalid barrier');
    }
    if (file_put_contents($gate . '/' . $worker, 'ready') === false) {
        throw new RuntimeException('Barrier write failed');
    }
    $deadline = microtime(true) + 20;
    do {
        clearstatcache();
        if (is_file($gate . '/a') && is_file($gate . '/b')) {
            echo bakata_dropify_reserve_dispatch($order, 'synthetic-ci-token') ? "CLAIMED\n" : "BLOCKED\n";
            return;
        }
        usleep(50000);
    } while (microtime(true) < $deadline);
    throw new RuntimeException('Concurrent worker did not reach barrier');
}
if ($mode === 'verify') {
    global $wpdb;
    $key = 'bakata_dropify_dispatch_' . $id;
    $rows = $wpdb->get_results($wpdb->prepare("SELECT option_value, autoload FROM {$wpdb->options} WHERE option_name = %s", $key), ARRAY_A);
    if ($rows !== [['option_value' => 'attempted', 'autoload' => 'no']]
        || bakata_dropify_reserve_dispatch($order, 'synthetic-ci-token') !== false) {
        throw new RuntimeException('Reservation not unique and durable');
    }
    $engine = \Automattic\WooCommerce\Utilities\OrderUtil::custom_orders_table_usage_is_enabled() ? 'HPOS' : 'legacy';
    echo "Reservation durable; active engine: {$engine}\n";
    return;
}
throw new RuntimeException('Unknown fixture mode');
