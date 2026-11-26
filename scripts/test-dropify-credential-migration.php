<?php
declare(strict_types=1);

require __DIR__ . '/../tools/dropify-quarantine/credential-migration.php';
use Bakata\Dropify\CredentialMigration;
use Bakata\Dropify\TokenVault;

$count = 0;
function check(bool $value): void {
    if (!$value) throw new RuntimeException('Migration assertion failed');
    $GLOBALS['count']++;
}
function reject(callable $fn): void {
    try { $fn(); } catch (RuntimeException|InvalidArgumentException) { check(true); return; }
    throw new RuntimeException('Expected migration rejection');
}

$vault = new TokenVault('ci-key', random_bytes(32));
$m = new CredentialMigration($vault, 'ci-site');
$a = 'synthetic-secret-alpha';
$b = 'synthetic-secret-beta';
$stores = [['id' => '20', 'token' => $b], ['id' => 10, 'token' => $a]];
$products = [['post_id' => '101', 'token' => $b], ['post_id' => 100, 'token' => $a], ['post_id' => 102, 'token' => $a]];
$ids = [102, '101', 100];
$plan = $m->plan($stores, $products, $ids);
check($plan['site'] === 'ci-site' && $plan['version'] === 1);
check(array_column($plan['credentials'], 'store_id') === [10, 20]);
check($vault->open($plan['credentials'][0]['envelope'], $m->context(10)) === $a);
check($vault->open($plan['credentials'][1]['envelope'], $m->context(20)) === $b);
check($plan['product_references'] === [
    ['post_id' => 100, 'store_id' => 10],
    ['post_id' => 101, 'store_id' => 20],
    ['post_id' => 102, 'store_id' => 10],
]);
$json = json_encode($plan, JSON_THROW_ON_ERROR);
check(!str_contains($json, $a) && !str_contains($json, $b));
check($m->plan([], [], [])['credentials'] === []);
check($m->plan($stores, $products, $ids)['credentials'] !== $plan['credentials']);
reject(fn() => $vault->open($plan['credentials'][0]['envelope'], $m->context(20)));
reject(fn() => $m->plan($stores, $products, $ids, $a));
reject(fn() => $m->plan([...$stores, ['id' => 30, 'token' => $a]], $products, $ids));
reject(fn() => $m->plan([...$stores, ['id' => 10, 'token' => 'different']], $products, $ids));
reject(fn() => $m->plan($stores, [...$products, $products[0]], $ids));
reject(fn() => $m->plan($stores, [$products[0]], $ids));
reject(fn() => $m->plan($stores, [...$products, ['post_id' => 999, 'token' => $a]], $ids));
reject(fn() => $m->plan($stores, [['post_id' => 100, 'token' => 'unknown']], [100]));
reject(fn() => $m->plan($stores, $products, [...$ids, 102]));
reject(fn() => $m->plan([['id' => '01', 'token' => $a]], [], []));
reject(fn() => $m->plan([['id' => 2147483648, 'token' => $a]], [], []));
reject(fn() => $m->plan([['id' => 1, 'token' => '']], [], []));
reject(fn() => new CredentialMigration($vault, 'bad:site'));
reject(fn() => $m->plan(array_fill(0, 1001, $stores[0]), [], []));
echo "{$count} migration assertions passed\n";
