<?php
declare(strict_types=1);
define('ABSPATH', __DIR__);
class WC_Order {
    public function __construct(private array $meta, private string $type = 'shop_order') {}
    public function get_type() { return $this->type; }
    public function get_meta($key, $single = true) { return $this->meta[$key] ?? ''; }
}
function wc_get_order($id) { return $GLOBALS['orders'][$id] ?? false; }
function esc_html($value) { return htmlspecialchars($value, ENT_QUOTES, 'UTF-8'); }
function esc_html__($value, $domain) { return esc_html($value); }
function __($value, $domain) { return $value; }
function add_action($hook, $callback, $priority = 10, $args = 1) { $GLOBALS['hooks'][$hook] = $callback; }
function add_filter($hook, $callback, $priority = 10, $args = 1) { add_action($hook, $callback, $priority, $args); }
function check($condition) { if (!$condition) throw new RuntimeException('Assertion failed'); }
require $argv[1] . '/clasess/Woocomerce.php';
$ui = new JPIODFW_Woocomerce();
$orders = [1 => new WC_Order(['_is_dropi_order' => 'Yes', '_dropi_order_id' => '<script>', 'shipping_guide' => 'CI-123']), 2 => new WC_Order([]), 3 => new WC_Order([], 'shop_order_refund'), 4 => new WC_Order(['shipping_guide' => ['unexpected']])];
function render($ui, $column, $order) { ob_start(); $ui->show_custom_order_column_values($column, $order); return ob_get_clean(); }
check(render($ui, 'dropi_order_id', 1) === '&lt;script&gt;');
check(render($ui, 'dropi_order_id', $orders[1]) === '&lt;script&gt;');
check(render($ui, 'shipping_guide', $orders[1]) === 'CI-123');
check(str_contains(render($ui, 'is_dropi_order', 1), 'Orden sincronizada'));
check(str_contains(render($ui, 'is_dropi_order', 2), 'NO SYNC'));
check(render($ui, 'shipping_guide', 3) === '');
check(render($ui, 'shipping_guide', 4) === '');
check(render($ui, 'shipping_guide', 999) === '');
check(render($ui, 'unexpected', 1) === '');
$ui->init();
check(isset($hooks['manage_woocommerce_page_wc-orders_columns'], $hooks['manage_woocommerce_page_wc-orders_custom_column'], $hooks['manage_edit-shop_order_columns']));
foreach (['woocommerce_admin_order_actions', 'wp_ajax_send_order_to_dropi', 'woocommerce_order_status_changed', 'bulk_actions-edit-shop_order', 'handle_bulk_actions-edit-shop_order'] as $hook) check(!isset($hooks[$hook]));
$model = (new ReflectionClass(JPIODFW_OrdersModel::class))->newInstanceWithoutConstructor();
check($model->save($orders[1]) === 'Dropify dispatch disabled in read-only validation build');
echo "16 HPOS/read-only assertions passed\n";
