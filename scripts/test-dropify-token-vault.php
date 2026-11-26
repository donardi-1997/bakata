<?php
declare(strict_types=1);
require __DIR__ . '/../tools/dropify-quarantine/token-vault.php';
use Bakata\Dropify\TokenVault;

$count = 0;
function check(bool $ok): void { global $count; if (!$ok) throw new RuntimeException('Vault assertion failed'); $count++; }
function reject(callable $call): void {
    try { $call(); } catch (RuntimeException|InvalidArgumentException) { check(true); return; }
    throw new RuntimeException('Expected vault rejection');
}
$key = random_bytes(32);
$vault = new TokenVault('key1', $key);
$secret = 'synthetic-token-not-a-real-credential';
$a = $vault->seal($secret, 'site1:store1');
$b = $vault->seal($secret, 'site1:store1');
check($vault->open($a, 'site1:store1') === $secret);
check($a !== $b);
check(!str_contains($a, $secret));
reject(fn() => $vault->open($a, 'site1:store2'));
reject(fn() => (new TokenVault('key1', random_bytes(32)))->open($a, 'site1:store1'));
reject(fn() => (new TokenVault('key2', $key))->open($a, 'site1:store1'));
$parts = explode('.', $a);
$raw = sodium_base642bin($parts[2], SODIUM_BASE64_VARIANT_URLSAFE_NO_PADDING);
$raw[25] = chr(ord($raw[25]) ^ 1);
$parts[2] = sodium_bin2base64($raw, SODIUM_BASE64_VARIANT_URLSAFE_NO_PADDING);
reject(fn() => $vault->open(implode('.', $parts), 'site1:store1'));
reject(fn() => $vault->open($secret, 'site1:store1'));
reject(fn() => $vault->open('v1.key1.!', 'site1:store1'));
reject(fn() => $vault->seal('', 'site1:store1'));
reject(fn() => $vault->seal('synthetic token', 'site1:store1'));
reject(fn() => $vault->seal(str_repeat('a', 1001), 'site1:store1'));
reject(fn() => new TokenVault('key1', 'short'));
reject(fn() => $vault->seal($secret, ''));
reject(fn() => serialize($vault));
check($vault->__debugInfo() === ['keyId' => 'key1']);
$new = new TokenVault('key2', random_bytes(32));
check($new->open($new->seal($vault->open($a, 'site1:store1'), 'site1:store1'), 'site1:store1') === $secret);
check($vault->open($vault->seal(str_repeat('a', 1000), 'site1:store1'), 'site1:store1') === str_repeat('a', 1000));
echo "{$count} token vault assertions passed\n";
