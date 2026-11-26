<?php
declare(strict_types=1);

namespace Bakata\Core\Suppliers;

use DateTimeImmutable;
use InvalidArgumentException;

/**
 * Read-only catalog adapter boundary. No commercial adapter is registered.
 * Each external ID identifies one independently purchasable SKU/variant;
 * adapters must normalize provider-specific identifiers before returning it.
 */
interface CatalogAdapter
{
    public function supplierId(): string;

    /** Cursor is opaque and null requests the first page. */
    public function fetchPage(?string $cursor, int $limit): CatalogPage;
}

final readonly class SupplierProduct
{
    public function __construct(
        public string $supplierId,
        public string $externalId,
        public string $title,
        public int $unitCostMinor,
        public string $currency,
        public int $currencyMinorUnit,
        public int $availableQuantity,
        public DateTimeImmutable $observedAt,
    ) {
        if (!preg_match('/\A[a-z][a-z0-9-]{0,63}\z/D', $supplierId)) {
            throw new InvalidArgumentException('Invalid supplier identifier.');
        }
        if (trim($externalId) !== $externalId || $externalId === '' || strlen($externalId) > 255
            || preg_match('/[\x00-\x1f\x7f]/', $externalId) !== 0 || preg_match('//u', $externalId) !== 1) {
            throw new InvalidArgumentException('Invalid external product identifier.');
        }
        if (trim($title) === '' || strlen($title) > 512 || preg_match('//u', $title) !== 1
            || preg_match('/[\x00-\x1f\x7f]/', $title) !== 0) {
            throw new InvalidArgumentException('Invalid product title.');
        }
        if ($unitCostMinor < 0 || $availableQuantity < 0
            || !preg_match('/\A[A-Z]{3}\z/D', $currency)
            || $currencyMinorUnit < 0 || $currencyMinorUnit > 4) {
            throw new InvalidArgumentException('Invalid product cost, currency or stock.');
        }
    }

    /** Stable identity, independent of price, stock, time, and mutable title. */
    public function identity(): string
    {
        return hash('sha256', json_encode([$this->supplierId, $this->externalId], JSON_THROW_ON_ERROR));
    }

    /** Full hash avoids truncating the external identity; no WC SKU reservation. */
    public function proposedSku(): string
    {
        return 'bk-' . $this->identity();
    }

    /** A change detector only; not a persistent transaction idempotency key. */
    public function fingerprint(): string
    {
        return hash('sha256', json_encode([
            $this->identity(), $this->title, $this->unitCostMinor,
            $this->currency, $this->currencyMinorUnit, $this->availableQuantity,
        ], JSON_THROW_ON_ERROR));
    }
}

final readonly class CatalogPage
{
    /** @param list<SupplierProduct> $products */
    public function __construct(public array $products, public ?string $nextCursor)
    {
        if (!array_is_list($products) || count($products) > 250) {
            throw new InvalidArgumentException('Invalid catalog page size.');
        }
        foreach ($products as $product) {
            if (!$product instanceof SupplierProduct) {
                throw new InvalidArgumentException('Invalid catalog product.');
            }
        }
        if ($nextCursor !== null && ($nextCursor === '' || strlen($nextCursor) > 4096)) {
            throw new InvalidArgumentException('Invalid pagination cursor.');
        }
    }
}
