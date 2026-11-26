<?php
declare(strict_types=1);

defined('ABSPATH') || exit;

/**
 * Homepage hero. Only editorial content: no fabricated catalog or promotions.
 */
function bakata_render_store_hero(): string {
    $shop_url = '';
    if (function_exists('wc_get_page_id') && function_exists('wc_get_page_permalink') && wc_get_page_id('shop') > 0) {
        $shop_url = wc_get_page_permalink('shop');
    } elseif (post_type_exists('product')) {
        $shop_url = get_post_type_archive_link('product') ?: '';
    }

    $title_id = wp_unique_id('bk-hero-title-');
    ob_start();
    ?>
    <section class="bk-hero" aria-labelledby="<?php echo esc_attr($title_id); ?>">
      <div class="bk-hero__content">
        <p class="bk-hero__eyebrow"><?php esc_html_e('Curado para tu día a día', 'bakata'); ?></p>
        <h1 id="<?php echo esc_attr($title_id); ?>" class="bk-heading bk-h1 bk-hero__title"><?php esc_html_e('Descubre. Simplifica. Disfruta.', 'bakata'); ?></h1>
        <p class="bk-hero__lead"><?php esc_html_e('Selecciones pensadas para tu día a día.', 'bakata'); ?></p>
        <?php if ($shop_url) : ?>
          <a class="bk-button bk-hero__cta" href="<?php echo esc_url($shop_url); ?>"><?php esc_html_e('Explorar productos', 'bakata'); ?>
            <svg class="bk-icon" aria-hidden="true" focusable="false"><use href="<?php echo esc_url(get_theme_file_uri('assets/icons/sprite.svg') . '#arrow'); ?>"></use></svg>
          </a>
        <?php endif; ?>
      </div>
      <div class="bk-hero__media" aria-hidden="true">
        <img src="<?php echo esc_url(get_theme_file_uri('assets/images/hero-editorial.webp')); ?>" width="600" height="305" alt="" loading="eager" fetchpriority="high" decoding="async">
      </div>
    </section>
    <?php
    return (string) ob_get_clean();
}

add_shortcode('bakata_hero', 'bakata_render_store_hero');
