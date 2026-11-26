<?php
declare(strict_types=1);

defined('ABSPATH') || exit;

add_action('after_setup_theme', static function (): void {
    add_theme_support('woocommerce');
    add_theme_support('wc-product-gallery-zoom');
    add_theme_support('wc-product-gallery-slider');
    add_theme_support('wc-product-gallery-lightbox');
    add_theme_support('wp-block-styles');
});

/**
 * Shared component styles for the storefront and block editor.
 * Files are versioned with the theme; no external font or script requests.
 */
add_action('enqueue_block_assets', static function (): void {
    $assets = [
        'bakata-fonts' => 'assets/fonts/fonts.css',
        'bakata-brand-tokens' => 'assets/brand/tokens.css',
        'bakata-design-system' => 'assets/css/design-system.css',
        'bakata-header' => 'assets/css/header.css',
        'bakata-hero' => 'assets/css/hero.css',
        'bakata-catalog' => 'assets/css/catalog.css',
        'bakata-footer' => 'assets/css/footer.css',
        'bakata-shop' => 'assets/css/shop.css',
        'bakata-product' => 'assets/css/product.css',
        'bakata-cart' => 'assets/css/cart.css',
        'bakata-checkout' => 'assets/css/checkout.css',
        'bakata-account' => 'assets/css/account.css',
    ];
    foreach ($assets as $handle => $relative) {
        $path = get_theme_file_path($relative);
        if (!is_file($path)) {
            continue;
        }
        wp_enqueue_style(
            $handle,
            get_theme_file_uri($relative),
            match ($handle) {
                'bakata-design-system' => ['bakata-brand-tokens', 'bakata-fonts'],
                'bakata-header', 'bakata-hero', 'bakata-catalog', 'bakata-footer', 'bakata-shop', 'bakata-product', 'bakata-cart', 'bakata-checkout', 'bakata-account' => ['bakata-design-system'],
                default => [],
            },
            (string) filemtime($path)
        );
    }
});

require_once get_theme_file_path('inc/store-header.php');

require_once get_theme_file_path('inc/store-hero.php');

require_once get_theme_file_path('inc/store-catalog.php');

require_once get_theme_file_path('inc/store-footer.php');

require_once get_theme_file_path('inc/store-shop.php');

require_once get_theme_file_path('inc/store-product.php');

require_once get_theme_file_path('inc/store-cart.php');

require_once get_theme_file_path('inc/store-checkout.php');

require_once get_theme_file_path('inc/store-account.php');

/** Prioritize only the local body font on the editorial landing page. */
add_filter('wp_preload_resources', static function (array $resources): array {
    if (!is_front_page() || !is_file(get_theme_file_path('assets/fonts/inter.woff2'))) {
        return $resources;
    }
    $url = get_theme_file_uri('assets/fonts/inter.woff2');
    foreach ($resources as $resource) {
        if (($resource['href'] ?? '') === $url) {
            return $resources;
        }
    }
    $resources[] = ['href' => $url, 'as' => 'font', 'type' => 'font/woff2', 'crossorigin' => 'anonymous'];
    return $resources;
});

/** Keep transactional and internal search pages out of search indexes.
 * Preserve WordPress and plugin directives; do not override site-wide visibility.
 * Robots directives are not an access-control mechanism.
 */
add_filter('wp_robots', static function (array $robots): array {
    if (is_search()
        || (function_exists('is_cart') && is_cart())
        || (function_exists('is_checkout') && is_checkout())
        || (function_exists('is_account_page') && is_account_page())) {
        $robots['noindex'] = true;
        unset($robots['index']);
    }
    return $robots;
}, 20);
