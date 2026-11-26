<?php
declare(strict_types=1);
define('ABSPATH', __DIR__);
class WP_Error {
    public function __construct(public string $code, public string $message) {}
}
function add_filter($hook, $callback, $priority = 10, $args = 1) {
    $GLOBALS['hooks'][$hook] = [$callback, $priority, $args];
}
function add_action($hook, $callback, $priority = 10, $args = 1) {
    add_filter($hook, $callback, $priority, $args);
}
function wp_send_json_error($data, $status) {
    throw new RuntimeException('blocked', $status);
}
function check($value): void {
    if (!$value) { throw new RuntimeException('Guard assertion failed'); }
}
require __DIR__ . '/../tools/dropify-quarantine/bakata-dropify-guard.php';
$http = $hooks['pre_http_request'][0];
$tls = $hooks['http_request_args'][0];
foreach (['https://api.dropi.co/integrations/', 'https://API.DROPI.COM.ES./', 'https://d39ru7awumhhs2.cloudfront.net/'] as $url) {
    check($http(false, [], $url) instanceof WP_Error);
    $args = $tls(['sslverify' => false, 'redirection' => 5], $url);
    check($args['sslverify'] === true && $args['redirection'] === 0 && $args['reject_unsafe_urls'] === true);
}
foreach (['https://dropi.co.example.org', 'https://example.org/?next=api.dropi.co', 'https://notdropi.co'] as $url) {
    check($http(false, [], $url) === false);
    check($tls(['sslverify' => false], $url) === ['sslverify' => false]);
}
check($hooks['pre_option_dropi-woocomerce-autosync_orders'][0]() === '0');
foreach (['import', 'get-woo-products', 'send_order_to_dropi'] as $action) {
    foreach (['wp_ajax_', 'wp_ajax_nopriv_'] as $prefix) {
        try {
            $hooks[$prefix . $action][0]();
            throw new LogicException('Expected rejection');
        } catch (RuntimeException $e) {
            check($e->getCode() === 403);
        }
    }
}
echo "Dropify quarantine callback tests passed\n";
