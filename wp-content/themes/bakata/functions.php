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
        'bakata-fonts' => 'assets/fonts/fonts.css',
        'bakata-brand-tokens' => 'assets/brand/tokens.css',
        'bakata-design-system' => 'assets/css/design-system.css',
        'bakata-header' => 'assets/css/header.css',
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
                'bakata-header' => ['bakata-design-system'],
                default => [],
            },
            (string) filemtime($path)
        );
    }
});

require_once get_theme_file_path('inc/store-header.php');
