<?php
declare(strict_types=1);

namespace Bakata\Core\Webhooks;

use DateTimeImmutable;
use InvalidArgumentException;
use RuntimeException;

enum ReceiptResult: string
{
    case Recorded = 'recorded';
    case Duplicate = 'duplicate';
}

/** Atomic claim of a receipt hash, not a claim of business execution. */
interface ReceiptLedger
{
    public function claim(string $key, string $fingerprint, DateTimeImmutable $now): ReceiptResult;
    public function matches(string $key, string $fingerprint): bool;
}

/**
 * Own plugin table, never WooCommerce order tables. Explicit setup only.
 * UNIQUE primary key + no-op duplicate insert; no check-then-insert race.
 * No payload, customer data, event body, tracking number or secret persisted.
 */
final class WpReceiptLedger implements ReceiptLedger
{
    private string $table;
    public function __construct(private readonly \wpdb $db)
    {
        $this->table = $db->prefix . 'bakata_receipts_v1';
        if (!preg_match('/\A[a-zA-Z0-9_]{1,64}\z/D', $this->table)) {
            throw new InvalidArgumentException('Invalid receipt table identifier.');
        }
    }

    public function install(): void
    {
        if (!current_user_can('manage_options')) {
            throw new RuntimeException('Receipt schema setup requires administrator capability.');
        }
        $sql = "CREATE TABLE IF NOT EXISTS {$this->table} (
            receipt_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
            fingerprint CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
            insertion_token CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
            received_at BIGINT UNSIGNED NOT NULL,
            PRIMARY KEY (receipt_key)
        ) ENGINE=InnoDB";
        if ($this->db->query($sql) === false) {
            throw new RuntimeException('Receipt schema setup failed.');
        }
        // Fail closed if an incompatible preexisting table is found.
        $status = $this->db->get_row($this->db->prepare(
            'SHOW TABLE STATUS WHERE Name = %s', $this->table
        ), ARRAY_A);
        $indexes = $this->db->get_results("SHOW INDEX FROM {$this->table} WHERE Key_name = 'PRIMARY'", ARRAY_A);
        if (!is_array($status) || strcasecmp((string) ($status['Engine'] ?? ''), 'InnoDB') !== 0
            || !is_array($indexes) || count($indexes) !== 1
            || ($indexes[0]['Column_name'] ?? '') !== 'receipt_key'
            || ($indexes[0]['Sub_part'] ?? null) !== null) {
            throw new RuntimeException('Incompatible receipt schema.');
        }
    }

    private function validate(string $key, string $fingerprint): void
    {
        if (!preg_match('/\A[a-f0-9]{64}\z/D', $key) || !preg_match('/\A[a-f0-9]{64}\z/D', $fingerprint)) {
            throw new InvalidArgumentException('Invalid receipt key or fingerprint.');
        }
    }

    private function read(string $key): ?array
    {
        $row = $this->db->get_row($this->db->prepare(
            "SELECT fingerprint, insertion_token FROM {$this->table} WHERE receipt_key = %s", $key
        ), ARRAY_A);
        if ($this->db->last_error !== '') {
            throw new RuntimeException('Receipt lookup failed.');
        }
        return is_array($row) ? $row : null;
    }

    public function matches(string $key, string $fingerprint): bool
    {
        $this->validate($key, $fingerprint);
        $row = $this->read($key);
        return $row !== null && hash_equals($row['fingerprint'], $fingerprint);
    }

    public function claim(string $key, string $fingerprint, DateTimeImmutable $now): ReceiptResult
    {
        $this->validate($key, $fingerprint);
        if ($now->getTimestamp() < 0) { throw new InvalidArgumentException('Invalid receipt time.'); }
        $token = bin2hex(random_bytes(16));
        // The unique key serializes concurrent insertions. Never overwrite a
        // conflicting fingerprint or rely on affected rows / FOUND_ROWS flags.
        $result = $this->db->query($this->db->prepare(
            "INSERT INTO {$this->table} (receipt_key, fingerprint, insertion_token, received_at)
             VALUES (%s, %s, %s, %d) ON DUPLICATE KEY UPDATE receipt_key = receipt_key",
            $key, $fingerprint, $token, $now->getTimestamp()
        ));
        if ($result === false) { throw new RuntimeException('Receipt write failed.'); }
        $row = $this->read($key);
        if ($row === null) { throw new RuntimeException('Receipt missing after write.'); }
        if (!hash_equals($row['fingerprint'], $fingerprint)) {
            throw new RuntimeException('Receipt identity conflict.');
        }
        return hash_equals($row['insertion_token'], $token) ? ReceiptResult::Recorded : ReceiptResult::Duplicate;
    }
}
