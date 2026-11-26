<?php
declare(strict_types=1);

use Bakata\Core\Orders\OrderLine;
use Bakata\Core\Orders\WooOrderPreview;

if (!defined('WP_CLI') || !WP_CLI || getenv('BAKATA_CI_FIXTURES') !== '1'
    || !in_array(wp_parse_url(home_url(), PHP_URL_HOST), ['localhost','127.0.0.1'],true)
    || !class_exists(WooOrderPreview::class)) {
    throw new RuntimeException('Refusing order fixtures outside isolated CI.');
}
$GLOBALS['bakata_order_checks'] = 0;
function order_check(bool $condition, string $label): void {
    if (!$condition) { throw new RuntimeException('Failed: ' . $label); }
    $GLOBALS['bakata_order_checks']++;
}
function order_rejects(callable $fn, string $message): void {
    try { $fn(); } catch (RuntimeException $error) {
        order_check(str_contains($error->getMessage(), $message),$message);
        return;
    }
    throw new RuntimeException('Expected rejection: ' . $message);
}
$previous = get_current_user_id();
$admins = get_users(['role'=>'administrator','number'=>1,'fields'=>'ID']);
if (!$admins) { throw new RuntimeException('CI administrator missing.'); }
add_filter('pre_wp_mail','__return_true');
try {
    wp_set_current_user((int)$admins[0]);
    $product = new WC_Product_Simple();
    $product->set_name('CI Synthetic Order Product');
    $product->set_status('draft');
    $product->set_regular_price('25000');
    $product->set_manage_stock(false);
    $productId = $product->save();
    // Historical synthetic order, no checkout, payment transaction or provider.
    $order = new WC_Order();
    $order->set_created_via('ci-fixture');
    $order->set_currency('COP');
    $order->set_shipping_country('CO');
    $order->set_payment_method('ci-offline');
    $item = new WC_Order_Item_Product();
    $item->set_product($product);
    $item->set_quantity(2);
    $item->set_subtotal('50000');
    $item->set_total('50000');
    $order->add_item($item);
    $order->calculate_totals(false);
    $order->set_status('processing');
    $order->set_date_paid(time());
    $id = $order->save();
    $stored = wc_get_order($id);
    $lineId = (int) array_key_first($stored->get_items('line_item'));
    $mapping = new OrderLine($lineId,$productId,2,'ci-supplier',hash('sha256','synthetic'));
    $preview = new WooOrderPreview();
    $before = [$stored->get_status(),$stored->get_date_paid()->getTimestamp(),$stored->get_total()];
    $run = static fn(array $lines) => $preview->inspect($id,'ci-store',$lines);
    $result = $run([$mapping]);
    order_check($result['state']==='preview_only','preview state');
    order_check($result['groups'][0]['lines'][0]['quantity']===2,'historical quantity');
    order_check($result===$run([$mapping]),'deterministic repeat');
    order_rejects(fn()=>$run([]),'Every order line');
    order_rejects(fn()=>$run([new OrderLine($lineId,$productId,3,'ci-supplier',hash('sha256','synthetic'))]),'requires manual review');
    wp_set_current_user(0);
    order_rejects(fn()=>$run([$mapping]),'capability');
    wp_set_current_user((int)$admins[0]);
    $after = wc_get_order($id);
    order_check([$after->get_status(),$after->get_date_paid()->getTimestamp(),$after->get_total()]===array_slice($before,0,3),'order not mutated');
    $after->set_payment_method('cod');
    $after->save();
    order_rejects(fn()=>$run([$mapping]),'Payment requires manual review');
    $after->set_payment_method('ci-offline');
    $after->set_status('cancelled');
    $after->save();
    order_rejects(fn()=>$run([$mapping]),'not eligible');
} finally {
    wp_set_current_user($previous);
}
$checks = $GLOBALS['bakata_order_checks'];
if ($checks !== 9) { throw new RuntimeException('Unexpected order check count: '.$checks); }
echo "Woo order preview: {$checks} checks passed.\n";
