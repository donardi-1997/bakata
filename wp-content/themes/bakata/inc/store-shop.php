<?php
declare(strict_types=1);

defined('ABSPATH') || exit;

/** Read-only catalog filters. WooCommerce owns the main product query. */
function bakata_shop_query_value(string $key): string {
    $value = $_GET[$key] ?? '';
    return is_string($value) ? sanitize_text_field(wp_unslash($value)) : '';
}

function bakata_shop_price_value(string $key): string {
    $value = bakata_shop_query_value($key);
    return preg_match('/^\d{1,12}(?:\.\d{1,6})?$/D', $value) ? $value : '';
}

function bakata_render_shop_filters(): string {
    if (!function_exists('is_shop') || !function_exists('get_woocommerce_currency')
        || !(is_shop() || is_product_taxonomy() || (is_search() && is_post_type_archive('product')))) {
        return '';
    }

    $shop = bakata_catalog_shop_url();
    if (!$shop) {
        return '';
    }
    $searching = is_search();
    $term = is_product_taxonomy() ? get_queried_object() : null;
    $term_url = $term instanceof WP_Term ? get_term_link($term) : '';
    $archive_url = is_string($term_url) && $term_url ? $term_url : $shop;
    $form_url = $searching ? home_url('/') : $archive_url;
    $parts = wp_parse_url($form_url);
    $fixed_args = [];
    if (!empty($parts['query'])) {
        wp_parse_str($parts['query'], $fixed_args);
    }
    $action = remove_query_arg(array_keys($fixed_args), $form_url);
    $query = $searching ? get_search_query(false) : '';
    $orderby = bakata_shop_query_value('orderby');
    if (!in_array($orderby, ['menu_order', 'popularity', 'rating', 'date', 'price', 'price-desc', 'relevance'], true)) {
        $orderby = '';
    }
    $min = bakata_shop_price_value('min_price');
    $max = bakata_shop_price_value('max_price');
    $reset = $searching ? add_query_arg(['s' => $query, 'post_type' => 'product'], home_url('/')) : $archive_url;
    $categories = get_terms([
        'taxonomy' => 'product_cat',
        'hide_empty' => true,
        'orderby' => 'name',
        'order' => 'ASC',
        'number' => 100,
        'exclude' => [(int) get_option('default_product_cat')],
    ]);
    if (is_wp_error($categories)) {
        $categories = [];
    }
    $title = wp_unique_id('bk-shop-filters-');
    $min_id = wp_unique_id('bk-min-price-');
    $max_id = wp_unique_id('bk-max-price-');
    $currency = get_woocommerce_currency();
    ob_start();
    ?>
    <section class="bk-shop-filters" aria-labelledby="<?php echo esc_attr($title); ?>">
      <h2 class="bk-heading bk-h3" id="<?php echo esc_attr($title); ?>"><?php esc_html_e('Explora el catálogo', 'bakata'); ?></h2>
      <?php if ($categories) : ?>
        <nav class="bk-shop-categories" aria-label="<?php esc_attr_e('Categorías de productos', 'bakata'); ?>">
          <ul>
            <li><a href="<?php echo esc_url($shop); ?>"<?php if (is_shop() && !$searching) : ?> aria-current="page"<?php endif; ?>><?php esc_html_e('Todos', 'bakata'); ?></a></li>
            <?php foreach ($categories as $category) :
                $url = get_term_link($category);
                if (is_wp_error($url)) {
                    continue;
                }
            ?>
              <li><a href="<?php echo esc_url($url); ?>"<?php if ($term instanceof WP_Term && $term->term_id === $category->term_id) : ?> aria-current="page"<?php endif; ?>><?php echo esc_html($category->name); ?></a></li>
            <?php endforeach; ?>
          </ul>
        </nav>
      <?php endif; ?>
      <form class="bk-shop-price-form" method="get" action="<?php echo esc_url($action); ?>">
        <?php foreach ($fixed_args as $key => $value) : if (is_scalar($value) && !in_array($key, ['s', 'post_type', 'min_price', 'max_price', 'orderby', 'paged'], true)) : ?>
          <input type="hidden" name="<?php echo esc_attr((string) $key); ?>" value="<?php echo esc_attr((string) $value); ?>">
        <?php endif; endforeach; ?>
        <?php if ($searching) : ?>
          <input type="hidden" name="s" value="<?php echo esc_attr($query); ?>">
          <input type="hidden" name="post_type" value="product">
        <?php endif; ?>
        <?php if ($orderby) : ?><input type="hidden" name="orderby" value="<?php echo esc_attr($orderby); ?>"><?php endif; ?>
        <div class="bk-form-field">
          <label class="bk-label" for="<?php echo esc_attr($min_id); ?>"><?php echo esc_html(sprintf(__('Precio mínimo (%s)', 'bakata'), $currency)); ?></label>
          <input class="bk-field" id="<?php echo esc_attr($min_id); ?>" type="number" name="min_price" min="0" max="999999999999" step="any" inputmode="decimal" value="<?php echo esc_attr($min); ?>">
        </div>
        <div class="bk-form-field">
          <label class="bk-label" for="<?php echo esc_attr($max_id); ?>"><?php echo esc_html(sprintf(__('Precio máximo (%s)', 'bakata'), $currency)); ?></label>
          <input class="bk-field" id="<?php echo esc_attr($max_id); ?>" type="number" name="max_price" min="0" max="999999999999" step="any" inputmode="decimal" value="<?php echo esc_attr($max); ?>">
        </div>
        <button class="bk-button" type="submit"><?php esc_html_e('Filtrar por precio', 'bakata'); ?></button>
        <a class="bk-link bk-shop-reset" href="<?php echo esc_url($reset); ?>"><?php esc_html_e('Limpiar filtros', 'bakata'); ?></a>
      </form>
      <?php if ($min !== '' && $max !== '' && (float) $min > (float) $max) : ?>
        <p class="bk-notice bk-notice--error"><?php esc_html_e('El precio mínimo debe ser menor o igual al máximo.', 'bakata'); ?></p>
      <?php endif; ?>
    </section>
    <?php
    return (string) ob_get_clean();
}
add_shortcode('bakata_shop_filters', 'bakata_render_shop_filters');

// Limit the standard archive page size. No separate WP_Query or direct SQL.
add_action('woocommerce_product_query', static function ($query): void {
    if ($query instanceof WP_Query && $query->is_main_query()) {
        $query->set('posts_per_page', 12);
    }
});

/**
 * The enclosing Bakatá block template already owns the main landmark.
 * Suppress only WooCommerce's default structural wrappers while rendering
 * the native archive block; retain every other hook and restore afterwards.
 */
function bakata_render_shop_archive(): string {
    if (!function_exists('is_shop') || !function_exists('is_product_taxonomy')
        || !(is_shop() || is_product_taxonomy() || (is_search() && is_post_type_archive('product')))) {
        return '';
    }
    if (!WP_Block_Type_Registry::get_instance()->is_registered('woocommerce/legacy-template')) {
        return '';
    }
    $wrappers = [
        'woocommerce_before_main_content' => 'woocommerce_output_content_wrapper',
        'woocommerce_after_main_content' => 'woocommerce_output_content_wrapper_end',
    ];
    $removed = [];
    foreach ($wrappers as $hook => $callback) {
        $priority = has_action($hook, $callback);
        if (false !== $priority && remove_action($hook, $callback, $priority)) {
            $removed[] = [$hook, $callback, $priority];
        }
    }
    try {
        return render_block([
            'blockName' => 'woocommerce/legacy-template',
            'attrs' => ['template' => 'archive-product'],
            'innerBlocks' => [],
            'innerHTML' => '',
            'innerContent' => [],
        ]);
    } finally {
        foreach ($removed as [$hook, $callback, $priority]) {
            add_action($hook, $callback, $priority);
        }
    }
}
add_shortcode('bakata_shop_archive', 'bakata_render_shop_archive');
