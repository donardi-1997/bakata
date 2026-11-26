<?php
declare(strict_types=1);

defined('ABSPATH') || exit;

/** Add only approved, published service information to the native summary. */
add_action('woocommerce_single_product_summary', static function (): void {
    if (!function_exists('is_product') || !is_product() || post_password_required()) {
        return;
    }
    $urls = bakata_footer_links();
    $links = [
        'shipping' => __('Información de envíos', 'bakata'),
        'returns' => __('Cambios y devoluciones', 'bakata'),
        'contact' => __('Contacto', 'bakata'),
    ];
    $links = array_filter($links, static fn(string $key): bool => !empty($urls[$key]), ARRAY_FILTER_USE_KEY);
    if (!$links) {
        return;
    }
    ?>
    <nav class="bk-product-service" aria-label="<?php esc_attr_e('Información para tu compra', 'bakata'); ?>">
      <ul>
        <?php foreach ($links as $key => $label) : ?>
          <li><a class="bk-link" href="<?php echo esc_url($urls[$key]); ?>"><?php echo esc_html($label); ?></a></li>
        <?php endforeach; ?>
      </ul>
    </nav>
    <?php
}, 45);

/** Product context uses WooCommerce state; variable availability remains native. */
add_action('woocommerce_single_product_summary', static function (): void {
    global $product;
    if (!function_exists('is_product') || !is_product() || post_password_required()
        || !$product instanceof WC_Product || 'publish' !== $product->get_status()) {
        return;
    }
    if ($product->is_type('variable')) {
        $message = __('Selecciona una opción para consultar su precio y disponibilidad.', 'bakata');
    } elseif ($product->is_type('simple') && $product->is_in_stock() && $product->is_on_backorder(1)) {
        $message = __('Disponible bajo pedido. Consulta las condiciones de entrega.', 'bakata');
    } else {
        return;
    }
    printf('<p class="bk-product-purchase-guide">%s</p>', esc_html($message));
}, 29);

/** Add real category context above the product name, without additional H1. */
add_action('woocommerce_single_product_summary', static function (): void {
    global $product;
    if (!function_exists('is_product') || !is_product() || post_password_required()
        || !$product instanceof WC_Product || 'publish' !== $product->get_status()) {
        return;
    }
    $terms = get_the_terms($product->get_id(), 'product_cat');
    if (!$terms || is_wp_error($terms)) {
        return;
    }
    foreach ($terms as $term) {
        if ((int) $term->term_id === (int) get_option('default_product_cat')) {
            continue;
        }
        $url = get_term_link($term);
        if (!is_wp_error($url)) {
            printf('<p class="bk-product-category-context"><a href="%s">%s</a></p>', esc_url($url), esc_html($term->name));
            return;
        }
    }
}, 4);
