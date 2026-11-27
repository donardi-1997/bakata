<?php
/**
 * Plugin Name: Bakatá Core
 * Description: Base modular para la operación comercial de Bakatá Store.
 * Version: 0.8.0
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
require_once __DIR__ . '/src/Fulfillment/FulfillmentPreview.php';
require_once __DIR__ . '/src/Webhooks/SignedEvent.php';
require_once __DIR__ . '/src/Webhooks/ReceiptLedger.php';
require_once __DIR__ . '/src/Webhooks/WebhookInbox.php';
require_once __DIR__ . '/src/Intelligence/PreviewSnapshot.php';
require_once __DIR__ . '/src/Intelligence/AdminPanel.php';
require_once __DIR__ . '/src/Intelligence/DraftBridge.php';
require_once __DIR__ . '/src/Intelligence/DropifyPreview.php';
require_once __DIR__ . '/src/Intelligence/DropifyDiagnostics.php';

require_once __DIR__ . '/src/Intelligence/CatalogReviewSnapshot.php';
require_once __DIR__ . '/src/Intelligence/CatalogReviewPanel.php';

require_once __DIR__ . '/src/Intelligence/ProfitabilitySnapshot.php';
require_once __DIR__ . '/src/Intelligence/ProfitabilityPanel.php';

require_once __DIR__ . '/src/Intelligence/AlertDashboardSnapshot.php';
require_once __DIR__ . '/src/Intelligence/AlertDashboardPanel.php';

Intelligence\AdminPanel::register();
Intelligence\CatalogReviewPanel::register();
Intelligence\ProfitabilityPanel::register();
Intelligence\AlertDashboardPanel::register();

// Export only visible catalog rows from the existing authenticated Dropify screen.
// No connector methods, token lookup, HTTP requests or catalog changes.
add_action('admin_enqueue_scripts', static function (): void {
    $page = isset($_GET['page']) && is_string($_GET['page']) ? wp_unslash($_GET['page']) : '';
    if ($page !== 'dropi-products' || !current_user_can('manage_options')) {
        return;
    }
    wp_enqueue_script('bakata-dropify-visible-export',
        plugins_url('assets/dropify-visible-export.js', __FILE__), [], '1.0.0', true);
});

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
