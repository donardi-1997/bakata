<?php
declare(strict_types=1);

namespace Bakata\Core\Webhooks;

use Bakata\Core\Fulfillment\FulfillmentEvent;
use Bakata\Core\Fulfillment\FulfillmentState;
use DateTimeImmutable;
use DateTimeZone;
use RuntimeException;
use InvalidArgumentException;

/** Explicit trusted configuration, never taken from an unsigned request. */
final readonly class EventScope
{
    public function __construct(public string $store, public string $supplier, public string $account)
    {
        if (!preg_match('/\A[a-zA-Z0-9._-]{1,128}\z/D', $store)
            || !preg_match('/\A[a-z][a-z0-9-]{0,63}\z/D', $supplier)
            || !preg_match('/\A[a-zA-Z0-9._-]{1,128}\z/D', $account)) {
            throw new InvalidArgumentException('Invalid webhook scope.');
        }
    }
    public function values(): array { return [$this->store, $this->supplier, $this->account]; }
}

/**
 * Internal reference HMAC protocol, not a commercial provider implementation.
 * Key supplied from trusted config at call time; no secrets or raw body logged.
 */
final class SignedEvent
{
    public function verify(
        EventScope $scope,
        string $keyId,
        #[\SensitiveParameter] string $secret,
        string $timestamp,
        string $signature,
        #[\SensitiveParameter] string $body,
        DateTimeImmutable $now,
        int $windowSeconds,
    ): FulfillmentEvent {
        if (!preg_match('/\A[a-zA-Z0-9._-]{1,64}\z/D', $keyId) || strlen($secret) < 32
            || $windowSeconds < 1 || $windowSeconds > 600
            || strlen($body) < 2 || strlen($body) > 16384
            || !preg_match('/\A[1-9][0-9]{9}\z/D', $timestamp)
            || !preg_match('/\Av1=[a-f0-9]{64}\z/D', $signature)) {
            throw new RuntimeException('Invalid signed event envelope.');
        }
        if (abs($now->getTimestamp() - (int) $timestamp) > $windowSeconds) {
            throw new RuntimeException('Signed event timestamp outside window.');
        }
        // Bind protocol, store, supplier, account, key, timestamp and exact body.
        $message = json_encode([
            'bakata-webhook-v1', ...$scope->values(), $keyId, $timestamp, hash('sha256', $body),
        ], JSON_THROW_ON_ERROR);
        if (!hash_equals('v1=' . hash_hmac('sha256', $message, $secret), $signature)) {
            throw new RuntimeException('Signed event authentication failed.');
        }

        try {
            $data = json_decode($body, true, 8, JSON_THROW_ON_ERROR);
            $fields = ['operationReference', 'contentFingerprint', 'eventId', 'state', 'occurredAt', 'carrier', 'trackingNumber'];
            if (!is_array($data) || array_is_list($data) || count($data) !== count($fields)
                || array_diff($fields, array_keys($data))) {
                throw new RuntimeException('Invalid event schema.');
            }
            foreach (array_slice($fields, 0, 5) as $field) {
                if (!is_string($data[$field])) { throw new RuntimeException('Invalid event schema.'); }
            }
            foreach (['carrier', 'trackingNumber'] as $field) {
                if ($data[$field] !== null && !is_string($data[$field])) {
                    throw new RuntimeException('Invalid event schema.');
                }
            }
            // Canonical UTC seconds for this synthetic wire protocol.
            $time = DateTimeImmutable::createFromFormat('!Y-m-d\TH:i:s\Z', $data['occurredAt'], new DateTimeZone('UTC'));
            if (!$time || $time->format('Y-m-d\TH:i:s\Z') !== $data['occurredAt'] || $time > $now
                || $time->getTimestamp() > (int) $timestamp) {
                throw new RuntimeException('Invalid event time.');
            }
            $state = FulfillmentState::tryFrom($data['state']);
            if (!$state) { throw new RuntimeException('Invalid event state.'); }
            return new FulfillmentEvent(
                $data['operationReference'], $data['contentFingerprint'], $data['eventId'], $state,
                $time, $data['carrier'], $data['trackingNumber'],
            );
        } catch (\JsonException | InvalidArgumentException | \ValueError) {
            // Do not propagate untrusted field values in exceptions.
            throw new RuntimeException('Invalid signed event content.');
        }
    }
}
