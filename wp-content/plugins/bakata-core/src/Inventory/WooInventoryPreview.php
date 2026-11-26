<?php
declare(strict_types=1);

namespace Bakata\Core\Inventory;

use Bakata\Core\Suppliers\SupplierProduct;
use DateTimeImmutable;
use RuntimeException;

/**
 * Reads the existing import metadata via WooCommerce CRUD.
 * Restricted to mapped inert simple drafts. No update/save, no automatic caller.
 */
final class WooInventoryPreview
{
    public function inspect(
        int $productId,
        ?SupplierProduct $incoming,
        InventoryPolicy $policy,
        int $unreflectedCommitments,
        DateTimeImmutable $asOf,
    ): InventoryResult {
        if ($productId < 1 || !function_exists('wc_get_product')
            || !current_user_can('edit_products') || !current_user_can('edit_post', $productId)) {
            throw new RuntimeException('Inventory preview requires product editing capability.');
        }
        $product = wc_get_product($productId);
        if (!$product || !$product->is_type('simple') || $product->get_status('edit') !== 'draft'
            || $product->get_catalog_visibility('edit') !== 'hidden'
            || $product->get_price('edit') !== '' || $product->get_regular_price('edit') !== ''
            || $product->get_sale_price('edit') !== '' || !$product->get_manage_stock('edit')
            || $product->get_stock_quantity('edit') !== 0 || $product->get_stock_status('edit') !== 'outofstock'
            || $product->get_backorders('edit') !== 'no') {
            throw new RuntimeException('Inventory preview requires an inert mapped draft.');
        }
        $identity = $product->get_meta('_bakata_source_identity', true, 'edit');
        $supplierId = $product->get_meta('_bakata_supplier_id', true, 'edit');
        $fingerprint = $product->get_meta('_bakata_import_fingerprint', true, 'edit');
        if (!is_string($identity) || !preg_match('/\A[a-f0-9]{64}\z/D', $identity)
            || $product->get_sku('edit') !== 'bk-' . $identity
            || !is_string($supplierId) || !preg_match('/\A[a-z][a-z0-9-]{0,63}\z/D', $supplierId)
            || !is_string($fingerprint) || !preg_match('/\A[a-f0-9]{64}\z/D', $fingerprint)) {
            throw new RuntimeException('Missing or inconsistent source mapping.');
        }
        if ($incoming && ($incoming->identity() !== $identity || $incoming->supplierId !== $supplierId)) {
            throw new RuntimeException('Incoming observation does not match mapped product.');
        }
        $rawQuantity = $product->get_meta('_bakata_source_stock', true, 'edit');
        $rawTime = $product->get_meta('_bakata_observed_at', true, 'edit');
        $quantity = is_string($rawQuantity) && preg_match('/\A(?:0|[1-9][0-9]*)\z/D', $rawQuantity)
            ? filter_var($rawQuantity, FILTER_VALIDATE_INT, ['options' => ['min_range' => 0]]) : false;
        $time = is_string($rawTime) && strlen($rawTime) === 25 && !str_contains($rawTime, "\0")
            ? DateTimeImmutable::createFromFormat(DATE_ATOM, $rawTime) : false;
        if ($quantity === false || $time === false || $time->format(DATE_ATOM) !== $rawTime) {
            throw new RuntimeException('Invalid stored stock observation; manual review required.');
        }
        return (new InventoryPreview())->compare(
            $identity, new StockObservation($identity, $quantity, $time),
            $incoming ? StockObservation::fromProduct($incoming) : null,
            $policy, $unreflectedCommitments, $asOf,
        );
    }
}
