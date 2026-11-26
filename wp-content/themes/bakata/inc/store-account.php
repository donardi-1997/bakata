<?php
declare(strict_types=1);

defined('ABSPATH') || exit;

/** Style the configured account page and its native endpoints, without
 * replacing the saved page, shortcode, sessions, capabilities or nonces. */
add_filter('page_template_hierarchy', static function (array $templates): array {
    if (function_exists('wc_get_page_id') && function_exists('is_account_page')
        && is_account_page() && is_page()
        && get_queried_object_id() === (int) wc_get_page_id('myaccount')) {
        array_unshift($templates, 'page-bakata-account.php');
    }
    return $templates;
});
