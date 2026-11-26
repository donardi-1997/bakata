<?php
declare(strict_types=1);
define('ABSPATH', __DIR__);
class WP_List_Table {}
class Rejected extends RuntimeException {}
function current_user_can($cap) { return $GLOBALS['allowed']; }
function check_ajax_referer($action, $key, $die) { return $GLOBALS['nonce']; }
function wp_send_json_error($data, $status) { throw new Rejected('Rejected', $status); }
$root = $argv[1];
require $root . '/clasess/Products.php';
require $root . '/clasess/Woocomerce.php';
$products = (new ReflectionClass(JPIODFW_Products::class))->newInstanceWithoutConstructor();
$orders = (new ReflectionClass(JPIODFW_Woocomerce::class))->newInstanceWithoutConstructor();
function rejected($call, $status) {
    try { $call(); } catch (Rejected $e) {
        if ($e->getCode() === $status) { return; }
        throw $e;
    }
    throw new RuntimeException('Expected rejection');
}
$_SERVER['REQUEST_METHOD'] = 'POST';
foreach ([[false, true], [true, false]] as [$allowed, $nonce]) {
    foreach ([[$products, 'my_import_product_event'], [$products, 'my_get_woo_products_cb2'], [$orders, 'send_order_to_dropi']] as $call) {
        rejected($call, 403);
    }
}
$allowed = $nonce = true;
$_SERVER['REQUEST_METHOD'] = 'GET';
rejected([$products, 'my_import_product_event'], 403);
$_SERVER['REQUEST_METHOD'] = 'POST';
$_REQUEST = ['product' => '0'];
rejected([$products, 'my_import_product_event'], 400);
echo "8 rejection cases passed\n";
