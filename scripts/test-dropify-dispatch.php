<?php
declare(strict_types=1);
define('ABSPATH', __DIR__);
define('OBJECT', 'OBJECT');
class WC_Order {
    public function __construct(public int $id, public array $meta = []) {}
    public function get_id() { return $this->id; }
    public function read_meta_data($force) { if (!$force) throw new RuntimeException('Expected fresh read'); }
    public function get_meta($key) { return $this->meta[$key] ?? ''; }
}
function wc_get_order($id) { return $GLOBALS['orders'][$id] ?? false; }
class FakeDb {
    public string $prefix = 'wp_';
    public string $options = 'wp_options';
    public bool $fail = false;
    public bool $suppressed = false;
    public array $claimed = [];
    public array $prepared = [];
    public function suppress_errors($value) { $old = $this->suppressed; $this->suppressed = $value; return $old; }
    public function insert($table, $data, $formats = []) {
        if ($this->fail || isset($this->claimed[$data['option_name']])) return false;
        if ($table !== $this->options || $data['autoload'] !== 'no') throw new RuntimeException('Invalid reservation');
        $this->claimed[$data['option_name']] = $data['option_value'];
        return 1;
    }
    public function prepare($query, ...$args) { $this->prepared[] = [$query, $args]; return 'prepared'; }
    public function get_results($query, $format) { if ($query !== 'prepared') throw new RuntimeException('Unprepared query'); return []; }
}
function verify($condition) { if (!$condition) throw new RuntimeException('Assertion failed'); }
$wpdb = new FakeDb();
$root = $argv[1];
require $root . '/clasess/models/OrdersModel.php';
$orders = [1 => new WC_Order(1), 2 => new WC_Order(2, ['_dropi_order_id' => 'abc']), 3 => new WC_Order(3, ['_is_dropi_order' => 'error']), 4 => new WC_Order(4)];
verify(bakata_dropify_reserve_dispatch($orders[1], 'synthetic-token') === true);
verify(bakata_dropify_reserve_dispatch($orders[1], 'synthetic-token') === false);
verify(bakata_dropify_reserve_dispatch($orders[2], 'synthetic-token') === false);
verify(bakata_dropify_reserve_dispatch($orders[3], 'synthetic-token') === false);
verify(bakata_dropify_reserve_dispatch($orders[4], '') === false);
verify(bakata_dropify_reserve_dispatch(new WC_Order(5), 'synthetic-token') === false);
$wpdb->fail = true;
verify(bakata_dropify_reserve_dispatch($orders[4], 'synthetic-token') === false);
verify($wpdb->suppressed === false);
verify($wpdb->claimed === ['bakata_dropify_dispatch_1' => 'attempted']);
$model = new JPIODFW_TokenModel();
$model->does_token_exist("synthetic'input");
$model->getTokenByStore('synthetic-store');
$model->getTokenById(123);
verify($wpdb->prepared === [
    ['SELECT * FROM wp_dropi_tokens WHERE token = %s', ["synthetic'input"]],
    ['SELECT * FROM wp_dropi_tokens WHERE store = %s', ['synthetic-store']],
    ['SELECT * FROM wp_dropi_tokens WHERE id = %d', [123]],
]);
verify($model->deleteToken(123) === false);
$items = $model->assignStoreName([(object) ['id' => 1]], (object) ['id' => 2, 'store' => 'Synthetic', 'token' => 'synthetic-secret']);
verify(!isset($items[0]->store->token) && $items[0]->store->id === 2);
echo "12 assertions passed (database and WooCommerce stubs; no network)\n";
