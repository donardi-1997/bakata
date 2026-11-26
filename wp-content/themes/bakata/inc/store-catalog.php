<?php
declare(strict_types=1);

defined('ABSPATH') || exit;

function bakata_catalog_shop_url(): string {
    if (!function_exists('wc_get_page_permalink') || !function_exists('wc_get_page_id')) {
        return '';
    }
    return wc_get_page_id('shop') > 0
        ? wc_get_page_permalink('shop')
        : (get_post_type_archive_link('product') ?: '');
}

/** Only configured top-level product categories with products, using Woo term counts. */
function bakata_render_categories(): string {
    if (!taxonomy_exists('product_cat')) {
        return '';
    }
    $terms = get_terms([
        'taxonomy' => 'product_cat',
        'parent' => 0,
        'hide_empty' => true,
        'hierarchical' => true,
        'pad_counts' => true,
        'exclude' => [(int) get_option('default_product_cat')],
        'orderby' => 'name',
        'order' => 'ASC',
        'number' => 6,
    ]);
    if (is_wp_error($terms)) {
        $terms = [];
    }
    $items = [];
    foreach ($terms as $term) {
        $url = get_term_link($term);
        if (!is_wp_error($url)) {
            $items[] = [$term, $url];
        }
    }
    $title = wp_unique_id('bk-categories-title-');
    $shop = bakata_catalog_shop_url();
    ob_start();
    ?>
    <section class="bk-catalog-section bk-categories" aria-labelledby="<?php echo esc_attr($title); ?>">
      <div class="bk-section-heading">
        <h2 class="bk-heading bk-h2" id="<?php echo esc_attr($title); ?>"><?php esc_html_e('Explora por categoría', 'bakata'); ?></h2>
        <?php if ($shop && $items) : ?><a class="bk-link" href="<?php echo esc_url($shop); ?>"><?php esc_html_e('Ver tienda', 'bakata'); ?></a><?php endif; ?>
      </div>
      <?php if (!$items) : ?>
        <p class="bk-catalog-empty"><?php esc_html_e('Todavía no hay categorías disponibles.', 'bakata'); ?></p>
      <?php else : ?>
        <ul class="bk-category-grid">
          <?php foreach ($items as [$term, $url]) :
              $image_id = (int) get_term_meta($term->term_id, 'thumbnail_id', true);
              $image = $image_id ? wp_get_attachment_image($image_id, 'woocommerce_thumbnail', false, ['alt' => '', 'loading' => 'lazy', 'decoding' => 'async']) : '';
          ?>
            <li><a class="bk-category bk-catalog-category" href="<?php echo esc_url($url); ?>">
              <span class="bk-category-media" aria-hidden="true">
                <?php if ($image) : echo wp_kses_post($image); else : ?>
                  <svg class="bk-icon" aria-hidden="true" focusable="false"><use href="<?php echo esc_url(get_theme_file_uri('assets/icons/sprite.svg') . '#box'); ?>"></use></svg>
                <?php endif; ?>
              </span>
              <span><?php echo esc_html($term->name); ?></span>
            </a></li>
          <?php endforeach; ?>
        </ul>
      <?php endif; ?>
    </section>
    <?php
    return (string) ob_get_clean();
}
add_shortcode('bakata_categories', 'bakata_render_categories');

/** Bounded queries through WooCommerce, respecting publication and catalog visibility. */
function bakata_home_products(): array {
    if (!function_exists('wc_get_products')) {
        return [];
    }
    $args = [
        'status' => 'publish',
        'visibility' => 'catalog',
        'featured' => true,
        'limit' => 12,
        'orderby' => 'date',
        'order' => 'DESC',
        'return' => 'objects',
        'type' => ['simple', 'variable', 'grouped', 'external'],
    ];
    if ('yes' === get_option('woocommerce_hide_out_of_stock_items')) {
        $args['stock_status'] = ['instock', 'onbackorder'];
    }
    $products = array_filter(wc_get_products($args), static function ($product): bool {
        return $product instanceof WC_Product
            && 'publish' === $product->get_status()
            && in_array($product->get_catalog_visibility(), ['visible', 'catalog'], true)
            && !post_password_required($product->get_id())
            && $product->is_visible();
    });
    return array_slice(array_values($products), 0, 4);
}

function bakata_render_featured_products(): string {
    if (!function_exists('wc_get_products')) {
        return '';
    }
    $products = bakata_home_products();
    $title = wp_unique_id('bk-featured-title-');
    $shop = bakata_catalog_shop_url();
    ob_start();
    ?>
    <section class="bk-catalog-section bk-featured" aria-labelledby="<?php echo esc_attr($title); ?>">
      <div class="bk-section-heading">
        <h2 class="bk-heading bk-h2" id="<?php echo esc_attr($title); ?>"><?php esc_html_e('Productos destacados', 'bakata'); ?></h2>
        <?php if ($shop) : ?><a class="bk-link" href="<?php echo esc_url($shop); ?>"><?php esc_html_e('Ver todos los productos', 'bakata'); ?></a><?php endif; ?>
      </div>
      <?php if (!$products) : ?>
        <p class="bk-catalog-empty"><?php esc_html_e('Todavía no hay productos destacados.', 'bakata'); ?></p>
      <?php else : ?>
        <ul class="bk-grid bk-product-grid">
          <?php foreach ($products as $product) :
              $url = $product->get_permalink();
              $price = $product->get_price_html();
              $count = (int) $product->get_rating_count();
              $rating = (float) $product->get_average_rating();
              $can_add = $product->is_type('simple') && $product->is_purchasable() && $product->is_in_stock()
                  && function_exists('wc_get_page_id') && wc_get_page_id('cart') > 0;
          ?>
            <li class="bk-card bk-product-card" data-product-id="<?php echo esc_attr((string) $product->get_id()); ?>">
              <a class="bk-product-media-link" href="<?php echo esc_url($url); ?>" aria-label="<?php echo esc_attr(sprintf(__('Ver %s', 'bakata'), $product->get_name())); ?>">
                <?php echo wp_kses_post($product->get_image('woocommerce_thumbnail', ['class' => 'bk-card__media', 'alt' => '', 'loading' => 'lazy', 'decoding' => 'async'])); ?>
              </a>
              <div class="bk-card__body">
                <h3 class="bk-heading bk-product-title"><a href="<?php echo esc_url($url); ?>"><?php echo esc_html($product->get_name()); ?></a></h3>
                <?php if (wc_review_ratings_enabled() && $count > 0 && $rating > 0) : ?>
                  <p class="bk-product-rating"><?php echo esc_html(sprintf(_n('%1$s/5 · %2$s valoración', '%1$s/5 · %2$s valoraciones', $count, 'bakata'), number_format_i18n($rating, 1), number_format_i18n($count))); ?></p>
                <?php endif; ?>
                <?php if ($price !== '') : ?><div class="bk-price"><?php echo wp_kses_post($price); ?></div><?php endif; ?>
                <?php if (!$product->is_in_stock()) : ?><p class="bk-product-stock"><?php esc_html_e('Agotado', 'bakata'); ?></p><?php endif; ?>
                <?php if ($can_add) : ?>
                  <form method="post" action="<?php echo esc_url(wc_get_cart_url()); ?>" class="bk-product-action">
                    <input type="hidden" name="add-to-cart" value="<?php echo esc_attr((string) $product->get_id()); ?>">
                    <button type="submit" class="bk-button" aria-label="<?php echo esc_attr(sprintf(__('Añadir al carrito: %s', 'bakata'), $product->get_name())); ?>"><?php esc_html_e('Añadir al carrito', 'bakata'); ?></button>
                  </form>
                <?php else : ?>
                  <a class="bk-button bk-button--secondary" href="<?php echo esc_url($url); ?>" aria-label="<?php echo esc_attr(sprintf(__('Ver detalles de %s', 'bakata'), $product->get_name())); ?>"><?php esc_html_e('Ver detalles', 'bakata'); ?></a>
                <?php endif; ?>
              </div>
            </li>
          <?php endforeach; ?>
        </ul>
      <?php endif; ?>
    </section>
    <?php
    return (string) ob_get_clean();
}
add_shortcode('bakata_featured_products', 'bakata_render_featured_products');
