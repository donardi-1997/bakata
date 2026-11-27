<?php
// Run only with WP-CLI in a disposable installation containing product fixtures.
if (!defined('WP_CLI') || !WP_CLI || getenv('BAKATA_CI_FIXTURES') !== '1'
    || !in_array(wp_parse_url(home_url(), PHP_URL_HOST), ['localhost', '127.0.0.1'], true)) {
    throw new RuntimeException('Disposable local fixtures required.');
}
$ids = wc_get_products(['slug' => 'ci-pdp-simple', 'return' => 'ids', 'limit' => 1]);
if (count($ids) !== 1 || !($product = wc_get_product($ids[0]))) {
    throw new RuntimeException('Missing simple fixture.');
}
$callbacks = [];
foreach (($GLOBALS['wp_filter']['woocommerce_add_to_cart_redirect']->callbacks[10] ?? []) as $entry) {
    if ($entry['function'] instanceof Closure) {
        $reflection = new ReflectionFunction($entry['function']);
        $file = basename($reflection->getFileName());
        if (in_array($file, ['store-catalog.php', 'store-product.php'], true)) {
            $callbacks[] = $file;
        }
    }
}
if ($callbacks !== ['store-catalog.php', 'store-product.php']) {
    throw new RuntimeException('Unexpected priority/order: ' . wp_json_encode($callbacks));
}
$prior = home_url('/ci-existing-redirect/');
$cart = wc_get_cart_url();
$detail = get_permalink($product->get_id());
$tests = [
    ['normal', 'POST', ['bakata_product_redirect' => '1'], false, $detail],
    ['missing', 'POST', [], false, false],
    ['empty', 'POST', ['bakata_product_redirect' => ''], false, false],
    ['zero', 'POST', ['bakata_product_redirect' => '0'], false, false],
    ['array', 'POST', ['bakata_product_redirect' => ['1']], false, false],
    ['get', 'GET', ['bakata_product_redirect' => '1'], false, false],
    ['existing-url', 'POST', ['bakata_product_redirect' => '1'], $prior, $prior],
    ['catalog', 'POST', ['bakata_cart_redirect' => '1'], false, $cart],
    ['both', 'POST', ['bakata_cart_redirect' => '1', 'bakata_product_redirect' => '1'], false, $cart],
    ['both-existing-url', 'POST', ['bakata_cart_redirect' => '1', 'bakata_product_redirect' => '1'], $prior, $cart],
    ['bad-catalog-product', 'POST', ['bakata_cart_redirect' => ['1'], 'bakata_product_redirect' => '1'], false, $detail],
];
$optionNo = static fn() => 'no';
add_filter('pre_option_woocommerce_cart_redirect_after_add', $optionNo);
foreach ($tests as [$name, $method, $post, $initial, $expected]) {
    $_SERVER['REQUEST_METHOD'] = $method;
    $_POST = $post;
    $actual = apply_filters('woocommerce_add_to_cart_redirect', $initial, $product);
    if ($actual !== $expected) {
        throw new RuntimeException($name . ': ' . wp_json_encode([$actual, $expected]));
    }
    echo "PASS $name\n";
}
$_SERVER['REQUEST_METHOD'] = 'POST';
$_POST = ['bakata_product_redirect' => '1'];
if (apply_filters('woocommerce_add_to_cart_redirect', false, null) !== false
    || apply_filters('woocommerce_add_to_cart_redirect', false, new WC_Product_Grouped()) !== false) {
    throw new RuntimeException('Invalid or unsupported product changed redirect.');
}
$earlier = static fn() => $prior;
add_filter('woocommerce_add_to_cart_redirect', $earlier, 5);
if (apply_filters('woocommerce_add_to_cart_redirect', false, $product) !== $prior) {
    throw new RuntimeException('Earlier redirect was overwritten by product filter.');
}
remove_filter('woocommerce_add_to_cart_redirect', $earlier, 5);
echo "PASS unsupported-product\nPASS earlier-filter\n";
remove_filter('pre_option_woocommerce_cart_redirect_after_add', $optionNo);
add_filter('pre_option_woocommerce_cart_redirect_after_add', static fn() => 'yes');
$_SERVER['REQUEST_METHOD'] = 'POST';
$_POST = ['bakata_product_redirect' => '1'];
if (apply_filters('woocommerce_add_to_cart_redirect', false, $product) !== $cart) {
    throw new RuntimeException('Configured cart redirect not respected.');
}
add_filter('woocommerce_add_to_cart_redirect', static fn() => $prior, 20);
if (apply_filters('woocommerce_add_to_cart_redirect', false, $product) !== $prior) {
    throw new RuntimeException('Later filter cannot override.');
}
echo "PASS cart-option\nPASS later-filter\n";
