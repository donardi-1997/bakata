<?php
declare(strict_types=1);

namespace Bakata\Core\Fulfillment;

use DateTimeImmutable;
use InvalidArgumentException;
use RuntimeException;

enum FulfillmentState: string
{
    case AwaitingConfirmation = 'awaiting_confirmation';
    case Accepted = 'accepted';
    case Preparing = 'preparing';
    case Shipped = 'shipped';
    case InTransit = 'in_transit';
    case DeliveryException = 'delivery_exception';
    case Delivered = 'delivered';
    case Returned = 'returned';
    case Rejected = 'rejected';
    case Cancelled = 'cancelled';
}

/** Normalized synthetic or already-trusted input; this is NOT a webhook verifier. */
final readonly class FulfillmentEvent
{
    public function __construct(
        public string $operationReference,
        public string $contentFingerprint,
        public string $eventId,
        public FulfillmentState $state,
        public DateTimeImmutable $occurredAt,
        public ?string $carrier = null,
        public ?string $trackingNumber = null,
    ) {
        if (!preg_match('/\A[a-f0-9]{64}\z/D', $operationReference)
            || !preg_match('/\A[a-f0-9]{64}\z/D', $contentFingerprint)
            || !preg_match('/\A[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}\z/D', $eventId)
            || $state === FulfillmentState::AwaitingConfirmation) {
            throw new InvalidArgumentException('Invalid fulfillment event.');
        }
        if ($state === FulfillmentState::Shipped) {
            if ($carrier === null || $trackingNumber === null
                || !preg_match('/\A[a-z0-9][a-z0-9-]{0,63}\z/D', $carrier)
                || !preg_match('/\A[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}\z/D', $trackingNumber)) {
                throw new InvalidArgumentException('Shipment requires normalized carrier and tracking reference.');
            }
        } elseif ($carrier !== null || $trackingNumber !== null) {
            throw new InvalidArgumentException('Tracking reference is only supplied with shipment.');
        }
    }

    public function fingerprint(): string
    {
        return hash('sha256', json_encode([
            $this->operationReference, $this->contentFingerprint, $this->eventId,
            $this->state->value, $this->occurredAt->format('U.u'),
            $this->carrier, $this->trackingNumber,
        ], JSON_THROW_ON_ERROR));
    }
}

final readonly class FulfillmentSnapshot
{
    public function __construct(
        public string $operationReference,
        public string $contentFingerprint,
        public FulfillmentState $state,
        public ?DateTimeImmutable $lastEventAt,
        public ?string $carrier,
        public ?string $trackingNumber,
        public int $uniqueEvents,
        public int $duplicateEvents,
    ) {}
}

/**
 * In-memory replay of a complete trusted event history for a single group.
 * No payment or order mutations, provider I/O, signatures, persistence or
 * dispatch authorization. A duplicate event is deduped only within this replay.
 */
final class FulfillmentPreview
{
    /** @param list<FulfillmentEvent> $events */
    public function replay(
        string $operationReference,
        string $contentFingerprint,
        array $events,
        DateTimeImmutable $asOf,
    ): FulfillmentSnapshot {
        if (!preg_match('/\A[a-f0-9]{64}\z/D', $operationReference)
            || !preg_match('/\A[a-f0-9]{64}\z/D', $contentFingerprint)
            || !array_is_list($events) || count($events) > 1000) {
            throw new InvalidArgumentException('Invalid fulfillment replay inputs.');
        }
        $state = FulfillmentState::AwaitingConfirmation;
        $seen = [];
        $last = null;
        $carrier = null;
        $tracking = null;
        $duplicates = 0;
        foreach ($events as $event) {
            if (!$event instanceof FulfillmentEvent
                || $event->operationReference !== $operationReference
                || $event->contentFingerprint !== $contentFingerprint) {
                throw new RuntimeException('Event does not match operation and content.');
            }
            if ($event->occurredAt > $asOf) {
                throw new RuntimeException('Fulfillment event is from the future.');
            }
            $key = $event->eventId;
            $fingerprint = $event->fingerprint();
            if (isset($seen[$key])) {
                if (!hash_equals($seen[$key], $fingerprint)) {
                    throw new RuntimeException('Conflicting fulfillment event identifier.');
                }
                $duplicates++;
                continue;
            }
            if ($last !== null && $event->occurredAt < $last) {
                throw new RuntimeException('Fulfillment event is out of order.');
            }
            if (!$this->allows($state, $event->state)) {
                throw new RuntimeException('Invalid fulfillment state transition.');
            }
            if ($event->state === FulfillmentState::Shipped) {
                $carrier = $event->carrier;
                $tracking = $event->trackingNumber;
            }
            $seen[$key] = $fingerprint;
            $state = $event->state;
            $last = $event->occurredAt;
        }
        return new FulfillmentSnapshot(
            $operationReference, $contentFingerprint, $state, $last,
            $carrier, $tracking, count($seen), $duplicates,
        );
    }

    private function allows(FulfillmentState $from, FulfillmentState $to): bool
    {
        $next = match ($from) {
            FulfillmentState::AwaitingConfirmation => [FulfillmentState::Accepted, FulfillmentState::Rejected, FulfillmentState::Cancelled],
            FulfillmentState::Accepted => [FulfillmentState::Preparing, FulfillmentState::Shipped, FulfillmentState::Cancelled],
            FulfillmentState::Preparing => [FulfillmentState::Shipped, FulfillmentState::Cancelled],
            FulfillmentState::Shipped => [FulfillmentState::InTransit, FulfillmentState::DeliveryException, FulfillmentState::Delivered, FulfillmentState::Returned],
            FulfillmentState::InTransit => [FulfillmentState::DeliveryException, FulfillmentState::Delivered, FulfillmentState::Returned],
            FulfillmentState::DeliveryException => [FulfillmentState::InTransit, FulfillmentState::Delivered, FulfillmentState::Returned],
            FulfillmentState::Delivered => [FulfillmentState::Returned],
            FulfillmentState::Returned, FulfillmentState::Rejected, FulfillmentState::Cancelled => [],
        };
        return in_array($to, $next, true);
    }

    /**
     * Aggregate exactly the groups of a single OrderPreview result.
     * No automatic mapping back to WooCommerce status. Missing snapshots are
     * errors rather than silently treated as delivered/awaiting confirmation.
     * @param array{orderId:int,state:string,groups:list<array>} $orderPreview
     * @param list<FulfillmentSnapshot> $snapshots
     */
    public function summarize(array $orderPreview, array $snapshots): array
    {
        $orderId = $orderPreview['orderId'] ?? null;
        $groups = $orderPreview['groups'] ?? null;
        if (!is_int($orderId) || $orderId < 1 || ($orderPreview['state'] ?? null) !== 'preview_only'
            || !is_array($groups) || !array_is_list($groups) || count($groups) < 1 || count($groups) > 250
            || !array_is_list($snapshots) || count($groups) !== count($snapshots)) {
            throw new InvalidArgumentException('Invalid or incomplete fulfillment summary.');
        }
        $expected = [];
        foreach ($groups as $group) {
            if (!is_array($group)) { throw new InvalidArgumentException('Invalid order group.'); }
            $ref = $group['operationReference'] ?? null;
            $fingerprint = $group['contentFingerprint'] ?? null;
            if (!is_string($ref) || !preg_match('/\A[a-f0-9]{64}\z/D', $ref)
                || !is_string($fingerprint) || !preg_match('/\A[a-f0-9]{64}\z/D', $fingerprint)
                || isset($expected[$ref])) {
                throw new InvalidArgumentException('Invalid or duplicate order group.');
            }
            $expected[$ref] = $fingerprint;
        }
        $counts = array_fill_keys(array_map(static fn(FulfillmentState $s): string => $s->value, FulfillmentState::cases()), 0);
        foreach ($snapshots as $snapshot) {
            if (!$snapshot instanceof FulfillmentSnapshot
                || !isset($expected[$snapshot->operationReference])
                || !hash_equals($expected[$snapshot->operationReference], $snapshot->contentFingerprint)) {
                throw new RuntimeException('Snapshot does not match expected order group.');
            }
            unset($expected[$snapshot->operationReference]);
            $counts[$snapshot->state->value]++;
        }
        $total = count($groups);
        $delivered = $counts['delivered'];
        $closed = $counts['rejected'] + $counts['cancelled'] + $counts['returned'];
        $attention = $closed + $counts['delivery_exception'];
        $state = match (true) {
            $delivered === $total => 'all_delivered',
            $closed === $total => 'closed_without_delivery',
            $attention > 0 => 'attention_required',
            $delivered > 0 => 'partial_delivery',
            $counts['awaiting_confirmation'] === $total => 'awaiting_confirmation',
            default => 'in_progress',
        };
        // Do not return tracking identifiers or other private data in aggregate.
        return ['orderId' => $orderId, 'state' => $state, 'groupCount' => $total, 'counts' => $counts];
    }
}
