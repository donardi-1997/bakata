<?php
declare(strict_types=1);

// In-memory WooCommerce CRUD double: exercises the real importer and reader offline.
class WC_Product {
    public array $fields = [];
    public array $meta = [];
    public function __call(string $name, array $args): mixed {
        if (str_starts_with($name, 'set_')) { $this->fields[substr($name, 4)] = $args[0]; return null; }
        if (str_starts_with($name, 'get_')) { return $this->fields[substr($name, 4)] ?? null; }
        throw new RuntimeException('Unexpected method ' . $name);
    }
    public function is_type(string $type): bool { return $type === 'simple'; }
    public function update_meta_data(string $key, mixed $value): void { $this->meta[$key] = $value; }
    public function get_meta(string $key, bool $single = true, string $context = 'view'): mixed { return $this->meta[$key] ?? ''; }
    public function save(): int {
        $GLOBALS['fixture_product'] = clone $this;
        if ($GLOBALS['corrupt_on_save'] ?? false) {
            $GLOBALS['fixture_product']->meta['_bakata_observed_at'] = '2026-01-01T00:00:00.000000+00:00';
        }
        return 1;
    }
}
class WC_Product_Simple extends WC_Product {}
function wc_get_product(int $id): ?WC_Product { return $id === 1 && isset($GLOBALS['fixture_product']) ? clone $GLOBALS['fixture_product'] : null; }
function wc_get_product_id_by_sku(string $sku): int { return isset($GLOBALS['fixture_product']) ? 1 : 0; }
function current_user_can(string $capability, mixed ...$args): bool { return true; }
function get_woocommerce_currency(): string { return 'COP'; }
function wc_get_price_decimals(): int { return 2; }
function sanitize_text_field(string $text): string { return $text; }

require_once __DIR__ . '/../wp-content/plugins/bakata-core/src/Suppliers/Contracts.php';
require_once __DIR__ . '/../wp-content/plugins/bakata-core/src/Pricing/PricingPreview.php';
require_once __DIR__ . '/../wp-content/plugins/bakata-core/src/Catalog/DraftPlanner.php';
require_once __DIR__ . '/../wp-content/plugins/bakata-core/src/Inventory/InventoryPreview.php';
require_once __DIR__ . '/../wp-content/plugins/bakata-core/src/Catalog/WooDraftImporter.php';
require_once __DIR__ . '/../wp-content/plugins/bakata-core/src/Inventory/WooInventoryPreview.php';

use Bakata\Core\Catalog\WooDraftImporter;
use Bakata\Core\Catalog\DraftPlanner;
use Bakata\Core\Inventory\InventoryPolicy;
use Bakata\Core\Inventory\WooInventoryPreview;
use Bakata\Core\Pricing\PricingPolicy;
use Bakata\Core\Pricing\UnitCosts;
use Bakata\Core\Suppliers\SupplierProduct;

$checks = 0;
$check = static function (bool $ok, string $label) use (&$checks): void {
    if (!$ok) { throw new RuntimeException('Failed: ' . $label); }
    $checks++;
};
$reject = static function (callable $fn, string $message) use ($check): void {
    try { $fn(); } catch (Throwable $e) { $check(str_contains($e->getMessage(), $message), $message); return; }
    throw new RuntimeException('Expected rejection: ' . $message);
};
$now = new DateTimeImmutable('now');
$source = static fn(DateTimeImmutable $time, int $stock = 5) =>
    new SupplierProduct('ci-supplier', 'sku', 'Fixture', 100, 'COP', 2, $stock, $time);
$importer = new WooDraftImporter();
$costs = new UnitCosts('COP', 2, 100, 0, 0, 0, 0);
$pricePolicy = new PricingPolicy('COP', 2, 0, 0, 1, 1000);
$stockPolicy = new InventoryPolicy(3600, 0, 100);
$planner = new DraftPlanner();
$fixed = new DateTimeImmutable('2026-01-01T00:00:00.500000+00:00');
$check($planner->plan($source($fixed->modify('-3600 seconds')), $costs, $pricePolicy, $fixed, 3600) instanceof \Bakata\Core\Catalog\DraftPlan, 'planner inclusive freshness boundary');
$reject(fn()=>$planner->plan($source($fixed->modify('-3600 seconds -1 microsecond')), $costs, $pricePolicy, $fixed, 3600), 'stale or from the future');
$reject(fn()=>$planner->plan($source($fixed->modify('+1 microsecond')), $costs, $pricePolicy, $fixed, 3600), 'stale or from the future');
$dst = new DateTimeImmutable('2026-03-08T03:00:00.500000-04:00');
$check($planner->plan($source(new DateTimeImmutable('2026-03-08T01:00:00.500000-05:00')), $costs, $pricePolicy, $dst, 3600) instanceof \Bakata\Core\Catalog\DraftPlan, 'planner elapsed freshness across DST');
$GLOBALS['corrupt_on_save'] = true;
$reject(fn()=>$importer->create($source($now), $costs, $pricePolicy, 3600), 'Saved product does not satisfy');
$GLOBALS['corrupt_on_save'] = false;
$reject(fn()=>$importer->create($source($now), $costs, $pricePolicy, 3600), 'manual review');
$check(wc_get_product(1)->get_meta('_bakata_observed_at') === '2026-01-01T00:00:00.000000+00:00', 'corrupt retry does not repair stored value');
unset($GLOBALS['fixture_product']);
$id = $importer->create($source($now), $costs, $pricePolicy, 3600);
$stored = wc_get_product($id);
$raw = $now->setTimezone(new DateTimeZone('UTC'))->format('Y-m-d\TH:i:s.uP');
$check($stored->get_meta('_bakata_observed_at') === $raw, 'import preserves exact instant');
$inventory = new WooInventoryPreview();
$inspect = static fn(?SupplierProduct $incoming) => $inventory->inspect($id, $incoming, $stockPolicy, 0, $now->modify('+1 second'));
$check($inspect($source($now))->status === 'replay', 'exact replay');
$check($inspect($source($now, 6))->status === 'conflict', 'same instant conflict');
$check($inspect($source($now->modify('-1 microsecond')))->status === 'out_of_order', 'microsecond ordering');
$check($inspect($source($now->modify('+1 microsecond'), 6))->status === 'changed', 'microsecond change');
$check(wc_get_product($id)->get_meta('_bakata_observed_at') === $raw, 'preview is read only');
$check($importer->create($source($now->setTimezone(new DateTimeZone('America/Bogota'))), $costs, $pricePolicy, 3600) === $id, 'same instant in another timezone replays');
$reject(fn()=>$importer->create($source($now->modify('-1 microsecond')), $costs, $pricePolicy, 3600), 'manual review');
$stored->update_meta_data('_bakata_observed_at', $now->format(DATE_ATOM));
$stored->save();
$reject(fn()=>$inspect($source($now)), 'manual review');
$reject(fn()=>$inspect(null), 'manual review');
$reject(fn()=>$importer->create($source($now), $costs, $pricePolicy, 3600), 'manual review');
$check(wc_get_product($id)->get_meta('_bakata_observed_at') === $now->format(DATE_ATOM), 'legacy not silently migrated');
foreach (['2026-02-30T00:00:00.000000+00:00', '2026-01-01T00:00:00.1+00:00', "2026-01-01T00:00:00.000000\0:00"] as $bad) {
    $stored->update_meta_data('_bakata_observed_at', $bad);
    $stored->save();
    $reject(fn()=>$inspect($source($now)), 'manual review');
}
$reject(fn()=>$importer->create($source((new DateTimeImmutable())->setTimestamp(PHP_INT_MIN)), $costs, $pricePolicy, 3600), 'Unsupported inventory observation time');
echo "Offline inventory/import integration: {$checks} checks passed.\n";
