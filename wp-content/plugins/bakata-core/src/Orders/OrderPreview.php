<?php
declare(strict_types=1);

namespace Bakata\Core\Orders;

use InvalidArgumentException;
use RuntimeException;

/** Explicitly approved mapping supplied by caller, never inferred from a current product. */
final readonly class OrderLine
{
    public function __construct(
        public int $lineId,
        public int $productId,
        public int $quantity,
        public string $supplierId,
        public string $sourceIdentity,
    ) {
        if ($lineId < 1 || $productId < 1 || $quantity < 1
            || !preg_match('/\A[a-z][a-z0-9-]{0,63}\z/D', $supplierId)
            || !preg_match('/\A[a-f0-9]{64}\z/D', $sourceIdentity)) {
            throw new InvalidArgumentException('Invalid order line or supplier mapping.');
        }
    }
}

/** Pure preview, no stock reservation, supplier payload, or authorization to dispatch. */
final class OrderPreview
{
    /**
     * @param list<OrderLine> $lines
     * @return array{orderId:int,state:string,groups:list<array>}
     */
    public function prepare(
        string $storeScope,
        int $orderId,
        string $status,
        bool $hasPaidDate,
        bool $hasRefund,
        string $destinationCountry,
        array $lines,
    ): array {
        if (!preg_match('/\A[a-zA-Z0-9._-]{1,128}\z/D', $storeScope) || $orderId < 1
            || !array_is_list($lines) || count($lines) < 1 || count($lines) > 250) {
            throw new InvalidArgumentException('Invalid order preview inputs.');
        }
        // Only the standard paid, awaiting-fulfillment state is eligible.
        // A paid date is evidence in Woo, not independent settlement proof.
        if ($status !== 'processing' || !$hasPaidDate || $hasRefund) {
            throw new RuntimeException('Order is not eligible for fulfillment preview.');
        }
        if ($destinationCountry !== 'CO') {
            throw new RuntimeException('Destination requires manual review.');
        }

        $seen = [];
        $groups = [];
        foreach ($lines as $line) {
            if (!$line instanceof OrderLine || isset($seen[$line->lineId])) {
                throw new InvalidArgumentException('Invalid or duplicate order line.');
            }
            $seen[$line->lineId] = true;
            $groups[$line->supplierId][] = [
                'lineId' => $line->lineId,
                'productId' => $line->productId,
                'quantity' => $line->quantity,
                'sourceIdentity' => $line->sourceIdentity,
            ];
        }
        ksort($groups, SORT_STRING);
        $result = [];
        foreach ($groups as $supplier => $items) {
            usort($items, static fn(array $a, array $b): int => $a['lineId'] <=> $b['lineId']);
            // Reference deliberately excludes mutable lines: an edited order
            // must conflict with an existing operation, not create a second one.
            $reference = hash('sha256', json_encode([
                'bakata-order-v1', $storeScope, $orderId, $supplier,
            ], JSON_THROW_ON_ERROR));
            $fingerprint = hash('sha256', json_encode([
                $reference, $destinationCountry, $items,
            ], JSON_THROW_ON_ERROR));
            $result[] = [
                'supplierId' => $supplier,
                'operationReference' => $reference,
                'contentFingerprint' => $fingerprint,
                'lines' => $items,
            ];
        }
        return ['orderId' => $orderId, 'state' => 'preview_only', 'groups' => $result];
    }
}
