<?php
declare(strict_types=1);

namespace Bakata\Core\Inventory;

use Bakata\Core\Suppliers\SupplierProduct;
use DateTimeImmutable;
use InvalidArgumentException;

final readonly class StockObservation
{
    public function __construct(
        public string $identity,
        public int $quantity,
        public DateTimeImmutable $observedAt,
    ) {
        if (!preg_match('/\A[a-f0-9]{64}\z/D', $identity) || $quantity < 0) {
            throw new InvalidArgumentException('Invalid stock observation.');
        }
    }

    public static function fromProduct(SupplierProduct $product): self
    {
        return new self($product->identity(), $product->availableQuantity, $product->observedAt);
    }
}

/** Explicit scenario values, not production defaults or guaranteed availability. */
final readonly class InventoryPolicy
{
    public function __construct(
        public int $maxAgeSeconds,
        public int $safetyUnits,
        public int $maxCandidateUnits,
    ) {
        if ($maxAgeSeconds < 1 || $maxAgeSeconds > 30 * 86400
            || $safetyUnits < 0 || $maxCandidateUnits < 0) {
            throw new InvalidArgumentException('Invalid inventory policy.');
        }
    }
}

final readonly class InventoryResult
{
    public function __construct(
        public string $status,
        public ?int $observedQuantity,
        public ?int $candidateQuantity,
        public ?int $previousQuantity,
        public ?string $observedAt,
    ) {}
}

/**
 * Read-only reconciliation. Null incoming means missing/unknown, not zero.
 * A null candidate is blocked, not permission to retain or increase live stock.
 * A candidate is a scenario upper bound, never a reservation or sale authorization.
 */
final class InventoryPreview
{
    public function compare(
        string $identity,
        ?StockObservation $previous,
        ?StockObservation $incoming,
        InventoryPolicy $policy,
        int $unreflectedCommitments,
        DateTimeImmutable $asOf,
    ): InventoryResult {
        if (!preg_match('/\A[a-f0-9]{64}\z/D', $identity) || $unreflectedCommitments < 0) {
            throw new InvalidArgumentException('Invalid reconciliation identity or commitments.');
        }
        if (($previous && $previous->identity !== $identity)
            || ($incoming && $incoming->identity !== $identity)) {
            throw new InvalidArgumentException('Observation belongs to another product.');
        }
        $blocked = static fn(string $reason): InventoryResult => new InventoryResult(
            $reason, $incoming?->quantity, null, $previous?->quantity,
            $incoming?->observedAt->format(DATE_ATOM),
        );
        if (!$incoming) { return $blocked('missing'); }
        $now = $asOf->getTimestamp();
        $time = $incoming->observedAt->getTimestamp();
        if ($time > $now || ($previous && $previous->observedAt->getTimestamp() > $now)) {
            return $blocked('future');
        }
        if ($previous) {
            $last = $previous->observedAt->getTimestamp();
            if ($time < $last) { return $blocked('out_of_order'); }
            if ($time === $last && $incoming->quantity !== $previous->quantity) {
                return $blocked('conflict');
            }
        }
        if ($now - $time > $policy->maxAgeSeconds) { return $blocked('stale'); }
        // Subtract separately and clamp at each step to avoid integer underflow.
        $afterSafety = max(0, $incoming->quantity - $policy->safetyUnits);
        $candidate = min($policy->maxCandidateUnits, max(0, $afterSafety - $unreflectedCommitments));
        $status = !$previous ? 'initial'
            : ($time === $previous->observedAt->getTimestamp() ? 'replay'
                : ($incoming->quantity === $previous->quantity ? 'refresh' : 'changed'));
        return new InventoryResult(
            $status, $incoming->quantity, $candidate, $previous?->quantity,
            $incoming->observedAt->format(DATE_ATOM),
        );
    }
}
