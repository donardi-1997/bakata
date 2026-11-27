<?php
/**
 * Plugin Name: Bakatá isolated catalog fixture
 * Test-only MU plugin, never packaged with Dropify.
 */
defined('ABSPATH') || exit;
if (getenv('BAKATA_DROPIFY_SANDBOX') !== '1' || wp_get_environment_type() !== 'staging'
    || home_url() !== 'http://localhost') {
    throw new RuntimeException('Refusing catalog fixture outside the disposable sandbox.');
}

if (get_option('bk_fixture_enabled') === '1') {
    define('BAKATA_DROPIFY_CATALOG_READ', true);
    define('BAKATA_DROPIFY_CATALOG_APPROVAL_REF', 'ci-wordpress-approval');
    define('BAKATA_DROPIFY_CATALOG_APPROVED_UNTIL', (int)get_option('bk_fixture_expiry'));
    define('BAKATA_DROPIFY_CATALOG_APPROVED_STORE', '7');
    define('BAKATA_DROPIFY_CATALOG_APPROVED_OFFSET', 0);
    define('BAKATA_DROPIFY_CATALOG_APPROVED_QUERY', 'fixture');
}

// Every WordPress HTTP request is intercepted. The Docker network independently
// prevents egress even for code that does not use the WordPress HTTP API.
add_filter('pre_http_request', static function ($pre, $args, $url) {
    if ($url !== 'https://api.dropi.co/integrations/products/index') {
        if (preg_match('/dropi|cloudfront/i', $url)) {
            update_option('bk_fixture_unexpected_provider', '1', false);
        }
        return new WP_Error('bk_fixture_offline', 'External traffic blocked in sandbox.');
    }
    $count = (int)get_option('bk_fixture_http_calls', 0) + 1;
    update_option('bk_fixture_http_calls', (string)$count, false);
    $receipt = 'bk_dropify_catalog_' . hash('sha256', 'ci-wordpress-approval');
    $body = json_decode($args['body'] ?? '', true);
    if ($count !== 1 || get_option($receipt) === false
        || ($args['method'] ?? null) !== 'POST' || ($args['sslverify'] ?? null) !== true
        || ($args['redirection'] ?? null) !== 0 || ($args['reject_unsafe_urls'] ?? null) !== true
        || ($args['timeout'] ?? null) !== 15 || ($args['limit_response_size'] ?? null) !== 524288
        || ($args['headers']['dropi-integration-key'] ?? '') !== 'ci-only-token-canary'
        || ($body['startData'] ?? null) !== 0 || ($body['pageSize'] ?? null) !== 10
        || ($body['keywords'] ?? null) !== 'fixture') {
        update_option('bk_fixture_bad_request', '1', false);
        return new WP_Error('bk_fixture_bad_request', 'Invalid fixture request.');
    }
    $item = ['id'=>96,'name'=>'Fixture <script>unsafe</script>','sku'=>'025216',
        'type'=>'SIMPLE','stock'=>5,'sale_price'=>'7000.25','suggested_price'=>17000,
        'description'=>'opaque-canary','user'=>['name'=>'Fixture warehouse','email'=>'private-canary']];
    return ['headers'=>[], 'body'=>wp_json_encode(['isSuccess'=>true,'objects'=>[$item]]),
        'response'=>['code'=>200,'message'=>'OK'],'cookies'=>[], 'filename'=>null];
}, PHP_INT_MAX, 3);

add_action('admin_init', static function () {
    if (($_GET['page'] ?? '') !== 'dropi-products') { return; }
    foreach (['wp_ajax_import','wp_ajax_nopriv_import','wp_ajax_get-woo-products',
        'wp_ajax_nopriv_get-woo-products','wp_ajax_send_order_to_dropi',
        'wp_ajax_nopriv_send_order_to_dropi'] as $hook) {
        if (has_action($hook)) {
            update_option('bk_fixture_unsafe_hook', '1', false);
            wp_die('Unexpected commercial action registered.');
        }
    }
});
