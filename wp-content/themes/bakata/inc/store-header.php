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
    $category_links = [];
    if (taxonomy_exists('product_cat')) {
        $categories = get_terms([
            'taxonomy' => 'product_cat', 'hide_empty' => true, 'hierarchical' => true,
            'pad_counts' => true, 'exclude' => [(int) get_option('default_product_cat')],
            'orderby' => 'name',
        ]);
        if (!is_wp_error($categories)) {
            $by_parent = [];
            foreach ($categories as $category) {
                $by_parent[(int) $category->parent][] = $category;
            }
            $priority = array_flip(['hogar-y-decoracion', 'tecnologia', 'cocina', 'belleza-y-cuidado-personal', 'mascotas', 'moda-y-accesorios', 'deportes-y-bienestar', 'automotriz', 'herramientas']);
            $roots = $by_parent[0] ?? [];
            usort($roots, static fn ($a, $b): int => (($priority[$a->slug] ?? PHP_INT_MAX) <=> ($priority[$b->slug] ?? PHP_INT_MAX)) ?: strcasecmp($a->name, $b->name));
            foreach (array_slice($roots, 0, 9) as $category) {
                $url = get_term_link($category);
                if (is_wp_error($url)) { continue; }
                $children = [];
                foreach (array_slice($by_parent[(int) $category->term_id] ?? [], 0, 8) as $child) {
                    $child_url = get_term_link($child);
                    if (!is_wp_error($child_url)) { $children[$child_url] = $child->name; }
                }
                $category_links[$url] = ['name' => $category->name, 'children' => $children];
            }
        }
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
            <?php foreach ($category_links as $url => $category) : ?>
              <?php if ($category['children']) : ?>
                <details class="bk-mobile-category">
                  <summary><?php echo esc_html($category['name']); ?></summary>
                  <a href="<?php echo esc_url($url); ?>"><?php echo esc_html(sprintf(__('Ver todo: %s', 'bakata'), $category['name'])); ?></a>
                  <?php foreach ($category['children'] as $child_url => $child_name) : ?>
                    <a href="<?php echo esc_url($child_url); ?>"><?php echo esc_html($child_name); ?></a>
                  <?php endforeach; ?>
                </details>
              <?php else : ?>
                <a href="<?php echo esc_url($url); ?>"><?php echo esc_html($category['name']); ?></a>
              <?php endif; ?>
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
      <?php if ($category_links) : ?>
        <nav class="bk-category-nav" aria-label="<?php esc_attr_e('Categorías de productos', 'bakata'); ?>">
          <details class="bk-mega">
            <summary><?php esc_html_e('Todas las categorías', 'bakata'); ?></summary>
            <div class="bk-mega-panel">
              <?php foreach ($category_links as $url => $category) : ?>
                <div class="bk-mega-group">
                  <a class="bk-mega-heading" href="<?php echo esc_url($url); ?>"><?php echo esc_html($category['name']); ?></a>
                  <?php foreach ($category['children'] as $child_url => $child_name) : ?>
                    <a href="<?php echo esc_url($child_url); ?>"><?php echo esc_html($child_name); ?></a>
                  <?php endforeach; ?>
                </div>
              <?php endforeach; ?>
              <?php if ($shop) : ?><a class="bk-mega-all" href="<?php echo esc_url($shop); ?>"><?php esc_html_e('Explorar toda la tienda', 'bakata'); ?></a><?php endif; ?>
            </div>
          </details>
          <?php foreach ($category_links as $url => $category) : ?><a href="<?php echo esc_url($url); ?>"><?php echo esc_html($category['name']); ?></a><?php endforeach; ?>
        </nav>
      <?php endif; ?>
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
