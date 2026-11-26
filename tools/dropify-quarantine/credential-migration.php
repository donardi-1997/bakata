<?php
declare(strict_types=1);

namespace Bakata\Dropify;

use InvalidArgumentException;
use RuntimeException;

require_once __DIR__ . '/token-vault.php';

/** Offline migration planner. No database writes, hooks or provider requests. */
final class CredentialMigration
{
    public function __construct(private readonly TokenVault $vault, private readonly string $site)
    {
        if (preg_match('/\A[A-Za-z0-9_-]{1,64}\z/D', $site) !== 1) {
            throw new InvalidArgumentException('Invalid site identity');
        }
    }

    private static function id(mixed $value): int
    {
        if ((!is_int($value) && !is_string($value))
            || preg_match('/\A[1-9][0-9]{0,9}\z/D', (string) $value) !== 1
            || (int) $value > 2147483647) {
            throw new InvalidArgumentException('Invalid migration identity');
        }
        return (int) $value;
    }

    public function context(int $storeId): string
    {
        return $this->site . ':store:' . self::id($storeId);
    }

    /**
     * Inputs are complete snapshots of legacy token rows, _dropi_token metadata
     * and the distinct IDs of products with Dropify mappings.
     * No plaintext or lookup fingerprint is returned.
     */
    public function plan(
        #[\SensitiveParameter] array $stores,
        #[\SensitiveParameter] array $productTokens,
        array $mappedProductIds,
        #[\SensitiveParameter] mixed $legacyOption = null
    ): array {
        if ($legacyOption !== null && $legacyOption !== '') {
            throw new RuntimeException('Legacy token option must be reconciled first');
        }
        if (!array_is_list($stores) || !array_is_list($productTokens) || !array_is_list($mappedProductIds)
            || count($stores) > 1000 || count($productTokens) > 10000 || count($mappedProductIds) > 10000) {
            throw new InvalidArgumentException('Invalid migration snapshot');
        }
        $lookupKey = random_bytes(32);
        $lookup = [];
        $encrypted = [];
        $refs = [];
        $expected = [];
        try {
            foreach ($stores as $row) {
                if (!is_array($row) || !is_string($row['token'] ?? null)) {
                    throw new InvalidArgumentException('Invalid credential row');
                }
                $id = self::id($row['id'] ?? null);
                $token = $row['token'];
                $digest = hash_hmac('sha256', $token, $lookupKey);
                if (isset($encrypted[$id]) || isset($lookup[$digest])) {
                    throw new RuntimeException('Duplicate store identity or credential');
                }
                $encrypted[$id] = [
                    'store_id' => $id,
                    'envelope' => $this->vault->seal($token, $this->context($id)),
                ];
                $lookup[$digest] = $id;
            }
            foreach ($mappedProductIds as $rawId) {
                $id = self::id($rawId);
                if (isset($expected[$id])) {
                    throw new RuntimeException('Duplicate mapped product identity');
                }
                $expected[$id] = true;
            }
            foreach ($productTokens as $row) {
                if (!is_array($row) || !is_string($row['token'] ?? null) || $row['token'] === '') {
                    throw new InvalidArgumentException('Invalid product credential row');
                }
                $id = self::id($row['post_id'] ?? null);
                $digest = hash_hmac('sha256', $row['token'], $lookupKey);
                if (!isset($expected[$id]) || isset($refs[$id]) || !isset($lookup[$digest])) {
                    throw new RuntimeException('Orphan or ambiguous product credential');
                }
                $refs[$id] = ['post_id' => $id, 'store_id' => $lookup[$digest]];
            }
            if (count($refs) !== count($expected)) {
                throw new RuntimeException('Mapped product missing credential');
            }
            ksort($encrypted, SORT_NUMERIC);
            ksort($refs, SORT_NUMERIC);
            return [
                'version' => 1,
                'site' => $this->site,
                'credentials' => array_values($encrypted),
                'product_references' => array_values($refs),
            ];
        } finally {
            sodium_memzero($lookupKey);
        }
    }
}
