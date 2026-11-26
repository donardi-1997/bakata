<?php
declare(strict_types=1);

defined('ABSPATH') || exit;

/** Resolve the configured cart page, not a language-dependent slug. */
add_filter('page_template_hierarchy', static function (array $templates): array {
    if (function_exists('wc_get_page_id') && function_exists('is_cart')
        && is_cart() && is_page() && get_queried_object_id() === (int) wc_get_page_id('cart')) {
        array_unshift($templates, 'page-bakata-cart.php');
    }
    return $templates;
});

/** Shared purchase progress, purely presentational and independent of cart session state. */
function bakata_purchase_steps(string $stage): string {
    if (!in_array($stage, ['cart', 'checkout'], true)) {
        return '';
    }
    $steps = [
        'cart' => __('Carrito', 'bakata'),
        'checkout' => __('Datos y pago', 'bakata'),
        'confirmation' => __('Confirmación', 'bakata'),
    ];
    $html = '<ol class="bk-purchase-steps" aria-label="' . esc_attr__('Progreso de compra', 'bakata') . '">';
    foreach ($steps as $key => $label) {
        $html .= '<li' . ($stage === $key ? ' aria-current="step"' : '') . '>' . esc_html($label) . '</li>';
    }
    return $html . '</ol>';
}

/** Keep a real route back to the catalog even when the cart is empty. */
function bakata_cart_navigation(): string {
    if (!function_exists('is_cart') || !is_cart() || post_password_required()) {
        return '';
    }
    $shop = bakata_catalog_shop_url();
    if (!$shop) {
        return '';
    }
    return bakata_purchase_steps('cart') . '<nav class="bk-cart-navigation" aria-label="' .
        esc_attr__('Navegación de compra', 'bakata') . '"><a class="bk-link" href="' .
        esc_url($shop) . '">' . esc_html__('Seguir explorando productos', 'bakata') . '</a></nav>';
}
add_shortcode('bakata_cart_navigation', 'bakata_cart_navigation');
