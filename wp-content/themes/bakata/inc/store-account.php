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

/** Dashboard shortcuts use enabled native account endpoints, never order queries. */
add_action('woocommerce_account_dashboard', static function (): void {
    if (!is_user_logged_in() || !function_exists('wc_get_account_menu_items')
        || !function_exists('wc_get_account_endpoint_url') || !is_account_page() || post_password_required()) {
        return;
    }
    $menu = wc_get_account_menu_items();
    $cards = [
        'orders' => [__('Mis pedidos', 'bakata'), __('Consulta el historial y los detalles de tus compras.', 'bakata')],
        'edit-address' => [__('Mis direcciones', 'bakata'), __('Gestiona tus datos de envío y facturación.', 'bakata')],
        'edit-account' => [__('Mi perfil', 'bakata'), __('Actualiza tus datos personales y contraseña.', 'bakata')],
    ];
    $cards = array_intersect_key($cards, $menu);
    if (!$cards) {
        return;
    }
    $id = wp_unique_id('bk-account-shortcuts-');
    ?>
    <section class="bk-account-shortcuts" aria-labelledby="<?php echo esc_attr($id); ?>">
      <h2 id="<?php echo esc_attr($id); ?>"><?php esc_html_e('Tu espacio bakatá', 'bakata'); ?></h2>
      <ul class="bk-account-shortcut-grid">
        <?php foreach ($cards as $endpoint => [$title, $description]) : ?>
          <li><a class="bk-account-shortcut" href="<?php echo esc_url(wc_get_account_endpoint_url($endpoint)); ?>"><span class="bk-account-shortcut-title"><?php echo esc_html($title); ?></span><span><?php echo esc_html($description); ?></span><span class="bk-account-shortcut-arrow" aria-hidden="true">&#8594;</span></a></li>
        <?php endforeach; ?>
      </ul>
    </section>
    <?php
}, 20);
