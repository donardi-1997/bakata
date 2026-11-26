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
