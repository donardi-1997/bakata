<?php
declare(strict_types=1);

namespace Bakata\Core\Webhooks;

use DateTimeImmutable;
use RuntimeException;
use InvalidArgumentException;

/**
 * Internal reference inbox; no REST route, cron, dispatch or fulfillment write.
 * Records receipt only. Never interprets duplicate as "already processed".
 */
final class WebhookInbox
{
    public function __construct(private readonly ReceiptLedger $ledger) {}

    private function digest(array $values): string
    {
        return hash('sha256', json_encode($values, JSON_THROW_ON_ERROR));
    }

    private function operationKey(EventScope $scope, string $reference): string
    {
        return $this->digest(['operation-v1', $scope->store, $reference]);
    }

    private function operationFingerprint(EventScope $scope, string $content): string
    {
        return $this->digest(['binding-v1', ...$scope->values(), $content]);
    }

    /** Explicit administrative registration of a preview group, NOT dispatch approval. */
    public function registerPreview(EventScope $scope, array $group, DateTimeImmutable $now): ReceiptResult
    {
        $ref = $group['operationReference'] ?? null;
        $content = $group['contentFingerprint'] ?? null;
        if (($group['supplierId'] ?? null) !== $scope->supplier
            || !is_string($ref) || !preg_match('/\A[a-f0-9]{64}\z/D', $ref)
            || !is_string($content) || !preg_match('/\A[a-f0-9]{64}\z/D', $content)) {
            throw new InvalidArgumentException('Invalid operation binding.');
        }
        return $this->ledger->claim(
            $this->operationKey($scope, $ref), $this->operationFingerprint($scope, $content), $now
        );
    }

    public function receive(
        EventScope $scope,
        string $keyId,
        #[\SensitiveParameter] string $secret,
        string $timestamp,
        string $signature,
        #[\SensitiveParameter] string $body,
        DateTimeImmutable $now,
        int $windowSeconds,
    ): ReceiptResult {
        $event = (new SignedEvent())->verify($scope, $keyId, $secret, $timestamp, $signature, $body, $now, $windowSeconds);
        if (!$this->ledger->matches(
            $this->operationKey($scope, $event->operationReference),
            $this->operationFingerprint($scope, $event->contentFingerprint),
        )) {
            throw new RuntimeException('Unregistered or changed operation binding.');
        }
        // Event identity is scoped to the store, supplier and account, not to
        // the key ID (rotation must not reset deduplication) or operation.
        return $this->ledger->claim(
            $this->digest(['event-v1', ...$scope->values(), $event->eventId]),
            $event->fingerprint(), $now,
        );
    }
}
