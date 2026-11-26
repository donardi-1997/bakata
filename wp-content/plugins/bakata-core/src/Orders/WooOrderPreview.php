<?php
declare(strict_types=1);

namespace Bakata\Core\Orders;

use RuntimeException;

/**
 * Internal HPOS-compatible read-only entry point. Mapping must be supplied
 * explicitly for each historical order line; no live product inference.
 * No PII returned, no supplier call, no order/stock writes or automatic caller.
 */
final class WooOrderPreview
{
    /** @param list<OrderLine> $approvedLines */
    public function inspect(int $orderId, string $storeScope, array $approvedLines): array
    {
        if ($orderId < 1 || !function_exists('wc_get_order')
            || !current_user_can('edit_shop_orders') || !current_user_can('edit_shop_order', $orderId)) {
            throw new RuntimeException('Order preview requires order editing capability.');
        }
        $order = wc_get_order($orderId);
        if (!$order instanceof \WC_Order || $order->get_type() !== 'shop_order') {
            throw new RuntimeException('Order unavailable for preview.');
        }
        if ($order->get_status() !== 'processing' || !$order->get_date_paid()
            || count($order->get_refunds()) > 0 || (float) $order->get_total_refunded() > 0) {
            throw new RuntimeException('Order is not eligible for fulfillment preview.');
        }
        // Reject zero totals and unpaid/unsupported flows. Settlement and COD
        // policy will be verified separately before any dispatch integration.
        if ((float) $order->get_total() <= 0 || $order->get_payment_method() === ''
            || $order->get_payment_method() === 'cod' || !$order->is_paid()) {
            throw new RuntimeException('Payment requires manual review.');
        }
        if (!array_is_list($approvedLines) || count($approvedLines) > 250) {
            throw new RuntimeException('Invalid approved order mappings.');
        }
        $mapped = [];
        foreach ($approvedLines as $line) {
            if (!$line instanceof OrderLine || isset($mapped[$line->lineId])) {
                throw new RuntimeException('Invalid approved order mappings.');
            }
            $mapped[$line->lineId] = $line;
        }
        $items = $order->get_items('line_item');
        if (count($items) < 1 || count($items) !== count($mapped)) {
            throw new RuntimeException('Every order line requires an approved mapping.');
        }
        foreach ($items as $id => $item) {
            $line = $mapped[(int) $id] ?? null;
            // Strict simple physical product support only. Variations and
            // deleted products must be manually reviewed rather than guessed.
            $product = $item->get_product();
            $quantity = $item->get_quantity();
            if (!$line || !$product instanceof \WC_Product_Simple || $product->is_virtual()
                || $product->is_downloadable() || $item->get_variation_id() !== 0
                || $line->productId !== $item->get_product_id()
                || !is_numeric($quantity) || (float) $quantity !== (float) $line->quantity) {
                throw new RuntimeException('Order line or approved mapping requires manual review.');
            }
        }

        // Country only, no billing fallback, address or recipient data.
        return (new OrderPreview())->prepare(
            $storeScope, $orderId, $order->get_status(), true, false,
            $order->get_shipping_country(), $approvedLines,
        );
    }
}
