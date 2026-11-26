<?php
declare(strict_types=1);

defined('ABSPATH') || exit;

/** Render a trusted theme icon; identifier is allowlisted. */
function bakata_header_icon(string $id): string {
    if (!in_array($id, ['menu', 'search', 'account', 'cart'], true)) {
        return '';
    }
    return '<svg class="bk-icon" aria-hidden="true" focusable="false"><use href="' .
        esc_url(get_theme_file_uri('assets/icons/sprite.svg') . '#' . $id) . '"></use></svg>';
}

/** Server-rendered header: canonical URLs, no dependency on client-side JS. */
function bakata_render_store_header(): string {
    $home = home_url('/');
    $has_woo = function_exists('wc_get_page_permalink') && function_exists('wc_get_cart_url');
    $shop = $has_woo ? wc_get_page_permalink('shop') : '';
    $account = $has_woo ? wc_get_page_permalink('myaccount') : '';
    $cart = $has_woo ? wc_get_cart_url() : '';
    $links = [$home => __('Inicio', 'bakata')];
    if ($shop && $shop !== $home) {
        $links[$shop] = __('Tienda', 'bakata');
    }
    $current_search = is_search() ? get_search_query(false) : '';
    $search_id = wp_unique_id('bk-search-');
    ob_start();
    ?>
    <div class="bk-store-header">
      <div class="bk-header-strip"><?php esc_html_e('Curado para tu día a día.', 'bakata'); ?></div>
      <div class="bk-header-inner">
        <details class="bk-header-menu">
          <summary class="bk-header-control" aria-label="<?php esc_attr_e('Menú de navegación', 'bakata'); ?>"><?php echo bakata_header_icon('menu'); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped ?></summary>
          <nav aria-label="<?php esc_attr_e('Navegación móvil', 'bakata'); ?>" class="bk-header-mobile-nav">
            <?php foreach ($links as $url => $label) : ?>
              <a href="<?php echo esc_url($url); ?>"><?php echo esc_html($label); ?></a>
            <?php endforeach; ?>
            <?php if ($account) : ?><a href="<?php echo esc_url($account); ?>"><?php esc_html_e('Mi cuenta', 'bakata'); ?></a><?php endif; ?>
          </nav>
        </details>
        <a class="bk-header-brand" href="<?php echo esc_url($home); ?>">
          <img class="bk-logo" src="<?php echo esc_url(get_theme_file_uri('assets/brand/logo-horizontal.svg')); ?>" width="830" height="252" alt="Bakatá">
        </a>
        <nav class="bk-header-desktop-nav" aria-label="<?php esc_attr_e('Navegación principal', 'bakata'); ?>">
          <?php foreach ($links as $url => $label) : ?>
            <a href="<?php echo esc_url($url); ?>"<?php if (($url === $home && is_front_page()) || ($shop && $url === $shop && function_exists('is_shop') && is_shop())) : ?> aria-current="page"<?php endif; ?>><?php echo esc_html($label); ?></a>
          <?php endforeach; ?>
        </nav>
        <form class="bk-header-search" role="search" method="get" action="<?php echo esc_url($home); ?>">
          <label class="bk-visually-hidden" for="<?php echo esc_attr($search_id); ?>"><?php esc_html_e('Buscar productos', 'bakata'); ?></label>
          <input class="bk-field" id="<?php echo esc_attr($search_id); ?>" type="search" name="s" value="<?php echo esc_attr($current_search); ?>" placeholder="<?php esc_attr_e('Buscar productos…', 'bakata'); ?>" required>
          <?php if ($has_woo) : ?><input type="hidden" name="post_type" value="product"><?php endif; ?>
          <button type="submit" class="bk-header-control" aria-label="<?php esc_attr_e('Buscar', 'bakata'); ?>"><?php echo bakata_header_icon('search'); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped ?></button>
        </form>
        <div class="bk-header-actions">
          <?php if ($account) : ?>
            <a class="bk-header-control bk-header-account" href="<?php echo esc_url($account); ?>" aria-label="<?php esc_attr_e('Mi cuenta', 'bakata'); ?>"><?php echo bakata_header_icon('account'); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped ?><span><?php esc_html_e('Mi cuenta', 'bakata'); ?></span></a>
          <?php endif; ?>
          <?php if ($cart) : ?>
            <a class="bk-header-control" href="<?php echo esc_url($cart); ?>" aria-label="<?php esc_attr_e('Carrito', 'bakata'); ?>"><?php echo bakata_header_icon('cart'); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped ?></a>
          <?php endif; ?>
        </div>
      </div>
    </div>
    <?php
    return (string) ob_get_clean();
}
add_shortcode('bakata_header', 'bakata_render_store_header');

/** Preserve the site icon selected in WordPress; otherwise use the brand SVG. */
add_action('wp_head', static function (): void {
    if (!has_site_icon()) {
        printf('<link rel="icon" type="image/svg+xml" href="%s">', esc_url(get_theme_file_uri('assets/brand/favicon.svg')));
    }
});
