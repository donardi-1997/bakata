<?php
/**
 * Plugin Name: Bakatá Core
 * Description: Base modular para la operación comercial de Bakatá Store.
 * Version: 0.6.0
 * Requires at least: 6.6
 * Requires PHP: 8.3
 * Author: Bakatá
 * Text Domain: bakata-core
 */

declare(strict_types=1);

namespace Bakata\Core;

defined('ABSPATH') || exit;

require_once __DIR__ . '/src/Suppliers/Contracts.php';
require_once __DIR__ . '/src/Suppliers/CatalogPreview.php';
require_once __DIR__ . '/src/Pricing/PricingPreview.php';
require_once __DIR__ . '/src/Catalog/DraftPlanner.php';
require_once __DIR__ . '/src/Catalog/WooDraftImporter.php';
require_once __DIR__ . '/src/Inventory/InventoryPreview.php';
require_once __DIR__ . '/src/Inventory/WooInventoryPreview.php';
require_once __DIR__ . '/src/Orders/OrderPreview.php';
require_once __DIR__ . '/src/Orders/WooOrderPreview.php';

add_action('before_woocommerce_init', static function (): void {
    if (class_exists(\Automattic\WooCommerce\Utilities\FeaturesUtil::class)) {
        \Automattic\WooCommerce\Utilities\FeaturesUtil::declare_compatibility(
            'custom_order_tables',
            __FILE__,
            true
        );
    }
});

add_action('plugins_loaded', static function (): void {
    if (!class_exists(\WooCommerce::class)) {
        add_action('admin_notices', static function (): void {
            if (current_user_can('activate_plugins')) {
                echo '<div class="notice notice-warning"><p>' .
                    esc_html__('Bakatá Core requiere WooCommerce activo.', 'bakata-core') .
                    '</p></div>';
            }
        });
        return;
    }

    // Contratos de proveedores disponibles; ningún adaptador comercial registrado.
    do_action('bakata_core_ready');
});
