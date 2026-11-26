<?php
declare(strict_types=1);

defined('ABSPATH') || exit;

/** Use the configured checkout page, retaining its saved block content. */
add_filter('page_template_hierarchy', static function (array $templates): array {
    if (function_exists('wc_get_page_id') && function_exists('is_checkout')
        && is_checkout() && is_page() && get_queried_object_id() === (int) wc_get_page_id('checkout')
        && !is_wc_endpoint_url()) {
        array_unshift($templates, 'page-bakata-checkout.php');
    }
    return $templates;
});

/** Navigation only; no checkout submission, data collection or payment logic. */
function bakata_checkout_navigation(): string {
    if (!function_exists('is_checkout') || !is_checkout() || is_wc_endpoint_url() || post_password_required()) {
        return '';
    }
    $links = bakata_footer_links();
    if (empty($links['cart'])) {
        return '';
    }
    return '<nav class="bk-checkout-navigation" aria-label="' . esc_attr__('Navegación de compra', 'bakata') .
        '"><a class="bk-link" href="' . esc_url($links['cart']) . '">' .
        esc_html__('Volver al carrito', 'bakata') . '</a></nav>';
}
add_shortcode('bakata_checkout_navigation', 'bakata_checkout_navigation');
