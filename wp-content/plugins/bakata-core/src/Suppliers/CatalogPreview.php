<?php
declare(strict_types=1);

namespace Bakata\Core\Suppliers;

use DateTimeImmutable;
use InvalidArgumentException;
use RuntimeException;

/**
 * Bounded, all-or-nothing preview in memory. No WordPress mutations, pricing,
 * inventory changes, scheduled tasks, HTTP implementation or order operations.
 */
final class CatalogPreview
{
    /**
     * Currency and age policy must be provided explicitly by the caller.
     * Reject ambiguous/partial results rather than silently accepting them.
     * @return list<array{identity:string,sku:string,supplierId:string,externalId:string,title:string,unitCostMinor:int,currency:string,currencyMinorUnit:int,availableQuantity:int,observedAt:string,fingerprint:string}>
     */
    public function collect(
        CatalogAdapter $adapter,
        DateTimeImmutable $asOf,
        string $currency,
        int $currencyMinorUnit,
        int $maxAgeSeconds,
        int $pageSize = 100,
        int $maxPages = 10,
    ): array {
        $supplierId = $adapter->supplierId();
        if (!preg_match('/\A[a-z][a-z0-9-]{0,63}\z/D', $supplierId)
            || !preg_match('/\A[A-Z]{3}\z/D', $currency)
            || $currencyMinorUnit < 0 || $currencyMinorUnit > 4
            || $maxAgeSeconds < 1 || $maxAgeSeconds > 86400 * 30
            || $pageSize < 1 || $pageSize > 250 || $maxPages < 1 || $maxPages > 100
            || $pageSize * $maxPages > 10000) {
            throw new InvalidArgumentException('Invalid preview limits or currency policy.');
        }

        $cursor = null;
        $seenCursors = [];
        $seenProducts = [];
        $rows = [];
        for ($i = 0; $i < $maxPages; $i++) {
            $page = $adapter->fetchPage($cursor, $pageSize);
            if (count($page->products) > $pageSize) {
                throw new RuntimeException('Adapter exceeded requested page size.');
            }
            foreach ($page->products as $product) {
                if ($product->supplierId !== $supplierId) {
                    throw new RuntimeException('Product belongs to another supplier.');
                }
                if ($product->currency !== $currency || $product->currencyMinorUnit !== $currencyMinorUnit) {
                    throw new RuntimeException('Currency mismatch; conversion is not implemented.');
                }
                $age = $asOf->getTimestamp() - $product->observedAt->getTimestamp();
                if ($age < 0 || $age > $maxAgeSeconds) {
                    throw new RuntimeException('Catalog observation is stale or from the future.');
                }
                $identity = $product->identity();
                if (isset($seenProducts[$identity])) {
                    throw new RuntimeException('Duplicate external product identity.');
                }
                $seenProducts[$identity] = true;
                $rows[] = [
                    'identity' => $identity,
                    'sku' => $product->proposedSku(),
                    'supplierId' => $supplierId,
                    'externalId' => $product->externalId,
                    'title' => $product->title,
                    'unitCostMinor' => $product->unitCostMinor,
                    'currency' => $currency,
                    'currencyMinorUnit' => $currencyMinorUnit,
                    'availableQuantity' => $product->availableQuantity,
                    'observedAt' => $product->observedAt->format(DATE_ATOM),
                    'fingerprint' => $product->fingerprint(),
                ];
            }
            if ($page->nextCursor === null) {
                return $rows;
            }
            $key = hash('sha256', $page->nextCursor);
            if (isset($seenCursors[$key])) {
                throw new RuntimeException('Repeated pagination cursor.');
            }
            $seenCursors[$key] = true;
            $cursor = $page->nextCursor;
        }
        throw new RuntimeException('Catalog page limit reached before completion.');
    }
}
