<?php
// Only disposable GitHub Actions WordPress, no real policy content.
if (!defined('WP_CLI') || !WP_CLI || getenv('BAKATA_CI_FIXTURES') !== '1'
    || !in_array(wp_parse_url(home_url(), PHP_URL_HOST), ['localhost', '127.0.0.1'], true)) {
    throw new RuntimeException('Refusing fixtures outside isolated CI.');
}
foreach ([
    ['bakata_shipping_page_id', 'ci-shipping-public', 'publish', ''],
    ['bakata_returns_page_id', 'ci-returns-draft', 'draft', ''],
    ['bakata_contact_page_id', 'ci-contact-protected', 'publish', 'test-only'],
    ['wp_page_for_privacy_policy', 'ci-privacy-public', 'publish', ''],
    ['woocommerce_terms_page_id', 'ci-terms-private', 'private', ''],
] as [$option, $slug, $status, $password]) {
    $id = wp_insert_post([
        'post_type' => 'page', 'post_title' => $slug, 'post_name' => $slug,
        'post_status' => $status, 'post_password' => $password,
        'post_content' => 'Fixture de CI; no es una política comercial.',
    ], true);
    if (is_wp_error($id) || !$id) {
        throw new RuntimeException('Could not create disposable page.');
    }
    update_option($option, $id);
}
echo "Disposable footer pages configured.\n";
