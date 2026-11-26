<?php
declare(strict_types=1);

defined('ABSPATH') || exit;

/** Link only to real, published, publicly readable pages. */
function bakata_public_page_url(int $id): string {
    $page = $id > 0 ? get_post($id) : null;
    if (!$page || 'page' !== $page->post_type || 'publish' !== $page->post_status || '' !== $page->post_password) {
        return '';
    }
    return get_permalink($page) ?: '';
}

function bakata_footer_links(): array {
    $wc = function_exists('wc_get_page_id');
    return [
        'shop' => $wc ? bakata_public_page_url((int) wc_get_page_id('shop')) : '',
        'account' => $wc ? bakata_public_page_url((int) wc_get_page_id('myaccount')) : '',
        'cart' => $wc ? bakata_public_page_url((int) wc_get_page_id('cart')) : '',
        'privacy' => bakata_public_page_url((int) get_option('wp_page_for_privacy_policy')),
        'terms' => $wc ? bakata_public_page_url((int) wc_get_page_id('terms')) : '',
        'shipping' => bakata_public_page_url((int) get_option('bakata_shipping_page_id')),
        'returns' => bakata_public_page_url((int) get_option('bakata_returns_page_id')),
        'contact' => bakata_public_page_url((int) get_option('bakata_contact_page_id')),
    ];
}

function bakata_footer_icon(string $id): string {
    if (!in_array($id, ['box', 'account', 'truck', 'return', 'document', 'headphones'], true)) {
        return '';
    }
    return '<svg class="bk-icon" aria-hidden="true" focusable="false"><use href="' .
        esc_url(get_theme_file_uri('assets/icons/sprite.svg') . '#' . $id) . '"></use></svg>';
}

/** Contextual service links rather than unverified commercial guarantees. */
function bakata_render_trust(): string {
    $urls = bakata_footer_links();
    $items = [
        ['shop', 'box', __('Explora el catálogo', 'bakata'), __('Consulta los productos y sus detalles.', 'bakata')],
        ['account', 'account', __('Tus pedidos', 'bakata'), __('Accede a tu cuenta y consulta tus compras.', 'bakata')],
        ['shipping', 'truck', __('Información de envíos', 'bakata'), __('Consulta la política de envíos.', 'bakata')],
        ['returns', 'return', __('Cambios y devoluciones', 'bakata'), __('Consulta la política de devoluciones.', 'bakata')],
        ['contact', 'headphones', __('Contacto', 'bakata'), __('Consulta nuestros canales de contacto.', 'bakata')],
    ];
    $items = array_values(array_filter($items, static fn(array $item): bool => !empty($urls[$item[0]])));
    if (!$items) {
        return '';
    }
    $title = wp_unique_id('bk-trust-title-');
    ob_start();
    ?>
    <section class="bk-trust" aria-labelledby="<?php echo esc_attr($title); ?>">
      <h2 class="bk-visually-hidden" id="<?php echo esc_attr($title); ?>"><?php esc_html_e('Información para tu compra', 'bakata'); ?></h2>
      <ul class="bk-trust-list">
        <?php foreach ($items as [$key, $icon, $label, $description]) : ?>
          <li><a class="bk-trust-item" href="<?php echo esc_url($urls[$key]); ?>">
            <?php echo bakata_footer_icon($icon); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped ?>
            <span><strong><?php echo esc_html($label); ?></strong><small><?php echo esc_html($description); ?></small></span>
          </a></li>
        <?php endforeach; ?>
      </ul>
    </section>
    <?php
    return (string) ob_get_clean();
}
add_shortcode('bakata_trust', 'bakata_render_trust');

function bakata_render_footer(): string {
    $urls = bakata_footer_links();
    $groups = [
        [
            'label' => __('Tienda', 'bakata'),
            'links' => [
                [home_url('/'), __('Inicio', 'bakata')],
                [$urls['shop'], __('Explorar productos', 'bakata')],
                [$urls['cart'], __('Carrito', 'bakata')],
                [$urls['account'], __('Mi cuenta', 'bakata')],
            ],
        ],
        [
            'label' => __('Información y ayuda', 'bakata'),
            'links' => [
                [$urls['contact'], __('Contacto', 'bakata')],
                [$urls['shipping'], __('Envíos', 'bakata')],
                [$urls['returns'], __('Cambios y devoluciones', 'bakata')],
                [$urls['privacy'], __('Política de privacidad', 'bakata')],
                [$urls['terms'], __('Términos y condiciones', 'bakata')],
            ],
        ],
    ];
    ob_start();
    ?>
    <div class="bk-store-footer bk-inverse">
      <div class="bk-footer-inner">
        <div class="bk-footer-brand">
          <a href="<?php echo esc_url(home_url('/')); ?>"><img class="bk-logo" src="<?php echo esc_url(get_theme_file_uri('assets/brand/logo-negativo.svg')); ?>" width="830" height="252" loading="lazy" decoding="async" alt="Bakatá"></a>
          <p><?php esc_html_e('Curado para tu día a día.', 'bakata'); ?></p>
          <p><?php esc_html_e('Descubre. Simplifica. Disfruta.', 'bakata'); ?></p>
        </div>
        <?php foreach ($groups as $group) :
            $links = array_filter($group['links'], static fn(array $link): bool => '' !== $link[0]);
            if (!$links) {
                continue;
            }
        ?>
          <nav class="bk-footer-nav" aria-label="<?php echo esc_attr($group['label']); ?>">
            <p class="bk-footer-heading"><?php echo esc_html($group['label']); ?></p>
            <ul>
              <?php foreach ($links as [$url, $label]) : ?><li><a href="<?php echo esc_url($url); ?>"><?php echo esc_html($label); ?></a></li><?php endforeach; ?>
            </ul>
          </nav>
        <?php endforeach; ?>
      </div>
      <div class="bk-footer-bottom">
        <small><?php echo esc_html(sprintf(__('© %s Bakatá.', 'bakata'), wp_date('Y'))); ?></small>
        <a href="<?php echo esc_url(home_url('/')); ?>"><?php esc_html_e('Inicio', 'bakata'); ?></a>
      </div>
    </div>
    <?php
    return (string) ob_get_clean();
}
add_shortcode('bakata_footer', 'bakata_render_footer');
