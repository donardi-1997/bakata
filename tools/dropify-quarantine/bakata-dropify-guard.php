<?php
/**
 * Plugin Name: Bakatá Dropify Quarantine
 * Description: Staging-only containment, not an authorization to activate Dropify.
 */
declare(strict_types=1);
namespace Bakata\DropifyGuard;

defined('ABSPATH') || exit;

function isDropiUrl(string $url): bool
{
    $host = strtolower(rtrim((string) parse_url($url, PHP_URL_HOST), '.'));
    return preg_match('/(?:^|\.)dropi\.(?:co|pa|mx|ec|cl|pe|com\.es|com\.py|ar|cr)$/D', $host) === 1
        || $host === 'd39ru7awumhhs2.cloudfront.net';
}

// Quarantine all observed provider hosts regardless of method or credentials.
// This is defense in depth, not an OS/network firewall.
add_filter('pre_http_request', static function ($pre, $args, $url) {
    if (isDropiUrl($url)) {
        return new \WP_Error('bakata_dropify_quarantine', 'Dropify network access is disabled.');
    }
    return $pre;
}, PHP_INT_MAX, 3);

add_filter('http_request_args', static function (array $args, string $url): array {
    if (isDropiUrl($url)) {
        $args['sslverify'] = true;
        $args['reject_unsafe_urls'] = true;
        $args['redirection'] = 0;
    }
    return $args;
}, PHP_INT_MAX, 2);

// Disable legacy autosync setting; newer per-token settings are not covered.
add_filter('pre_option_dropi-woocomerce-autosync_orders', static fn () => '0', PHP_INT_MAX);

// Block observed AJAX entrypoints even for administrators during quarantine.
foreach (['import', 'get-woo-products', 'send_order_to_dropi'] as $action) {
    foreach (['wp_ajax_', 'wp_ajax_nopriv_'] as $prefix) {
        add_action($prefix . $action, static function (): void {
            wp_send_json_error(['message' => 'Dropify quarantine is active.'], 403);
        }, PHP_INT_MIN);
    }
}
