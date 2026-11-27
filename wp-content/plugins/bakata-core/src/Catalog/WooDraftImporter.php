<?php
declare(strict_types=1);

namespace Bakata\Core\Catalog;

use Bakata\Core\Inventory\StockObservation;
use Bakata\Core\Pricing\PricingPolicy;
use Bakata\Core\Pricing\UnitCosts;
use Bakata\Core\Suppliers\SupplierProduct;
use DateTimeImmutable;
use DateTimeZone;
use RuntimeException;

/**
 * Internal, explicit create-only API. No endpoint, UI, cron, hook or automatic
 * caller is registered. A future orchestrator must serialize imports by SKU.
 * No update, publish, stock reconciliation or fulfillment behavior.
 */
final class WooDraftImporter
{
    public function create(
        SupplierProduct $source,
        UnitCosts $costs,
        PricingPolicy $policy,
        int $maxAgeSeconds,
    ): int {
        if (!class_exists(\WC_Product_Simple::class) || !function_exists('wc_get_product_id_by_sku')
            || !current_user_can('edit_products')) {
            throw new RuntimeException('Draft import requires WooCommerce and product editing capability.');
        }
        StockObservation::validateTime($source->observedAt);
        // Recalculate from validated inputs instead of accepting a fabricated quote.
        $plan = (new DraftPlanner())->plan($source, $costs, $policy, new DateTimeImmutable('now'), $maxAgeSeconds);
        if ($source->currency !== get_woocommerce_currency()
            || $source->currencyMinorUnit !== wc_get_price_decimals()) {
            throw new RuntimeException('Store currency or price decimals mismatch.');
        }
        $title = sanitize_text_field($source->title);
        if ($title === '' || $title !== $source->title) {
            throw new RuntimeException('Source title requires editorial normalization.');
        }
        $sku = $source->proposedSku();
        $observedAt = $source->observedAt->setTimezone(new DateTimeZone('UTC'))->format('Y-m-d\TH:i:s.uP');
        $existingId = (int) wc_get_product_id_by_sku($sku);
        if ($existingId > 0) {
            $existing = wc_get_product($existingId);
            // Never take ownership of an existing merchant product, variation,
            // changed draft or a product that has already become sellable.
            if (!$existing || !current_user_can('edit_post', $existingId)
                || !$existing->is_type('simple')
                || $existing->get_meta('_bakata_source_identity', true, 'edit') !== $source->identity()
                || $existing->get_meta('_bakata_import_fingerprint', true, 'edit') !== $plan->fingerprint
                || $existing->get_meta('_bakata_observed_at', true, 'edit') !== $observedAt
                || $existing->get_meta('_bakata_supplier_id', true, 'edit') !== $source->supplierId
                || $existing->get_meta('_bakata_source_stock', true, 'edit') !== (string) $source->availableQuantity
                || $existing->get_sku('edit') !== $sku
                || $existing->get_name('edit') !== $title
                || !$this->isInertDraft($existing)) {
                throw new RuntimeException('Existing SKU conflicts with requested inert draft; manual review required.');
            }
            return $existingId;
        }

        $product = new \WC_Product_Simple();
        $product->set_status('draft');
        $product->set_catalog_visibility('hidden');
        $product->set_name($title);
        $product->set_sku($sku);
        $product->set_regular_price('');
        $product->set_sale_price('');
        $product->set_price('');
        $product->set_manage_stock(true);
        $product->set_stock_quantity(0);
        $product->set_stock_status('outofstock');
        $product->set_backorders('no');
        $product->update_meta_data('_bakata_source_identity', $source->identity());
        $product->update_meta_data('_bakata_supplier_id', $source->supplierId);
        $product->update_meta_data('_bakata_import_fingerprint', $plan->fingerprint);
        $product->update_meta_data('_bakata_observed_at', $observedAt);
        $product->update_meta_data('_bakata_source_stock', (string) $source->availableQuantity);
        $product->update_meta_data('_bakata_candidate_price_minor', (string) $plan->quote->priceMinor);
        $product->update_meta_data('_bakata_candidate_currency', $plan->quote->currency);
        $product->update_meta_data('_bakata_candidate_minor_unit', (string) $plan->quote->minorUnit);
        $id = (int) $product->save();
        if ($id < 1) {
            throw new RuntimeException('Draft could not be saved.');
        }
        $stored = wc_get_product($id);
        if (!$stored || !$this->isInertDraft($stored)
            || $stored->get_sku('edit') !== $sku
            || $stored->get_meta('_bakata_import_fingerprint', true, 'edit') !== $plan->fingerprint
            || $stored->get_meta('_bakata_source_identity', true, 'edit') !== $source->identity()
            || $stored->get_meta('_bakata_supplier_id', true, 'edit') !== $source->supplierId
            || $stored->get_meta('_bakata_source_stock', true, 'edit') !== (string) $source->availableQuantity
            || $stored->get_name('edit') !== $title
            || !$stored->is_type('simple')
            || $stored->get_meta('_bakata_observed_at', true, 'edit') !== $observedAt) {
            // A third-party hook may have changed the stored object. Do not
            // overwrite or delete it blindly; report a hard failure.
            throw new RuntimeException('Saved product does not satisfy draft invariants; manual review required.');
        }
        return $id;
    }

    private function isInertDraft(\WC_Product $product): bool
    {
        return $product->get_status('edit') === 'draft'
            && $product->get_catalog_visibility('edit') === 'hidden'
            && $product->get_price('edit') === ''
            && $product->get_regular_price('edit') === ''
            && $product->get_sale_price('edit') === ''
            && $product->get_manage_stock('edit')
            && $product->get_stock_quantity('edit') === 0
            && $product->get_stock_status('edit') === 'outofstock'
            && $product->get_backorders('edit') === 'no';
    }
}
