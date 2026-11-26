<?php
declare(strict_types=1);

defined('ABSPATH') || exit;

add_action('after_setup_theme', static function (): void {
    add_theme_support('woocommerce');
    add_theme_support('wp-block-styles');
});

/**
 * Shared component styles for the storefront and block editor.
 * Files are versioned with the theme; no external font or script requests.
 */
add_action('enqueue_block_assets', static function (): void {
    $assets = [
        'bakata-brand-tokens' => 'assets/brand/tokens.css',
        'bakata-design-system' => 'assets/css/design-system.css',
    ];
    foreach ($assets as $handle => $relative) {
        $path = get_theme_file_path($relative);
        if (!is_file($path)) {
            continue;
        }
        wp_enqueue_style(
            $handle,
            get_theme_file_uri($relative),
            $handle === 'bakata-design-system' ? ['bakata-brand-tokens'] : [],
            (string) filemtime($path)
        );
    }
});
