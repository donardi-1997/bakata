<?php
declare(strict_types=1);

use Bakata\Core\Inventory\InventoryPolicy;
use Bakata\Core\Inventory\InventoryPreview;
use Bakata\Core\Inventory\StockObservation;
use Bakata\Core\Suppliers\SupplierProduct;

require_once __DIR__ . '/../wp-content/plugins/bakata-core/src/Suppliers/Contracts.php';
require_once __DIR__ . '/../wp-content/plugins/bakata-core/src/Inventory/InventoryPreview.php';

$checks = 0;
function check(bool $condition, string $label): void {
    global $checks;
    if (!$condition) { throw new RuntimeException('Failed: ' . $label); }
    $checks++;
}
function rejects(callable $fn, string $message): void {
    try { $fn(); } catch (InvalidArgumentException $error) {
        check(str_contains($error->getMessage(), $message), $message);
        return;
    }
    throw new RuntimeException('Expected rejection: ' . $message);
}
$now = new DateTimeImmutable('2026-01-01T00:00:00Z');
$product = new SupplierProduct('ci-supplier','SKU-A','Fixture',25000,'COP',0,12,$now);
$id = $product->identity();
$other = hash('sha256', 'other');
$obs = static fn(int $quantity, int $offset=0, ?string $identity=null) => new StockObservation(
    $identity ?? $id,$quantity,$now->modify(sprintf('%+d seconds',$offset))
);
$policy = new InventoryPolicy(300,2,8);
$preview = new InventoryPreview();
$run = static fn(?StockObservation $previous, ?StockObservation $incoming, int $commitments=1)
    => $preview->compare($id,$previous,$incoming,$policy,$commitments,$now);
$initial = $run(null,StockObservation::fromProduct($product));
check($initial->status==='initial' && $initial->candidateQuantity===8, 'initial cap');
check($initial->observedQuantity===12 && $initial->previousQuantity===null, 'source separated');
$changed = $run($obs(12,-60),$obs(6));
check($changed->status==='changed' && $changed->candidateQuantity===3 && $changed->previousQuantity===12, 'decrease');
check($run($obs(6,-60),$obs(12))->candidateQuantity===8,'increase only proposed');
check($run($obs(5),$obs(5))->status==='replay','equal timestamp and stock');
check($run($obs(5,-1),$obs(5))->status==='refresh','new timestamp same stock');
check($run($obs(5,-1),$obs(0))->candidateQuantity===0,'confirmed exhaustion');
check($run(null,$obs(2))->candidateQuantity===0,'safety consumes stock');
check($run(null,$obs(6),10)->candidateQuantity===0,'commitments exceed stock');
check($run(null,$obs(8),0)->candidateQuantity===6,'no unreflected commitments');
foreach ([
    [$obs(5),null,'missing'],
    [null,$obs(5,-301),'stale'],
    [null,$obs(5,1),'future'],
    [$obs(5,1),$obs(5),'future'],
    [$obs(5,-20),$obs(3,-21),'out_of_order'],
    [$obs(5,-20),$obs(3,-20),'conflict'],
] as [$previous,$incoming,$reason]) {
    $result=$run($previous,$incoming);
    check($result->status===$reason && $result->candidateQuantity===null,'blocked '.$reason);
}
check($run(null,$obs(5,-300))->candidateQuantity===2,'inclusive freshness bound');
$fractionalNow = new DateTimeImmutable('2026-01-01T00:05:00.500000Z');
$fractional = static fn(int $quantity, string $time) => new StockObservation($id, $quantity, new DateTimeImmutable($time));
$fractionalRun = static fn(?StockObservation $previous, StockObservation $incoming) =>
    $preview->compare($id, $previous, $incoming, $policy, 0, $fractionalNow);
$at = $fractional(5, '2026-01-01T00:05:00.500000Z');
check($fractionalRun(null, $fractional(5, '2026-01-01T00:05:00.500001Z'))->status === 'future', 'fractional future blocked');
check($fractionalRun(null, $fractional(5, '2026-01-01T00:00:00.500000Z'))->status === 'initial', 'fractional freshness inclusive');
check($fractionalRun(null, $fractional(5, '2026-01-01T00:00:00.499999Z'))->status === 'stale', 'fractional stale blocked');
check($fractionalRun($at, $fractional(5, '2026-01-01T00:05:00.499999Z'))->status === 'out_of_order', 'fractional ordering');
check($fractionalRun($fractional(5, '2026-01-01T00:05:00.499999Z'), $at)->status === 'refresh', 'fractional refresh');
check($fractionalRun($at, $fractional(6, '2026-01-01T01:05:00.500000+01:00'))->status === 'conflict', 'same instant across time zones conflicts');
check($fractionalRun(null, $at)->observedAt === '2026-01-01T00:05:00.500000+00:00', 'timestamp preserves microseconds');
$minTime = (new DateTimeImmutable())->setTimestamp(PHP_INT_MIN);
$maxTime = (new DateTimeImmutable())->setTimestamp(PHP_INT_MAX);
rejects(fn()=>new StockObservation($id, 5, $minTime), 'Unsupported inventory observation time');
rejects(fn()=>new StockObservation($id, 5, $maxTime), 'Unsupported inventory observation time');
rejects(fn()=>$preview->compare($id, null, $obs(5), $policy, 0, $minTime), 'Unsupported inventory observation time');
rejects(fn()=>$preview->compare($id, null, $obs(5), $policy, 0, $maxTime), 'Unsupported inventory observation time');
$dstNow = new DateTimeImmutable('2026-03-08T03:00:00.500000-04:00');
$dstIncoming = $fractional(5, '2026-03-08T01:55:00.500000-05:00');
check($preview->compare($id, null, $dstIncoming, $policy, 0, $dstNow)->status === 'initial', 'freshness is elapsed time across DST');
$earliest = $fractional(5, '0001-01-01T00:00:00.000000+00:00');
check($preview->compare($id, null, $earliest, $policy, 0, $earliest->observedAt)->status === 'initial', 'minimum supported UTC instant');
$latest = $fractional(5, '9999-12-31T23:59:59.999999+00:00');
check($preview->compare($id, null, $latest, $policy, 0, $latest->observedAt)->status === 'initial', 'maximum supported UTC instant');
check($run(null,$obs(PHP_INT_MAX),PHP_INT_MAX)->candidateQuantity===0,'integer extremes safe');
check($preview->compare($id,null,$obs(8),new InventoryPolicy(300,0,0),0,$now)->candidateQuantity===0,'zero cap');
rejects(fn()=>$obs(-1),'Invalid stock observation');
rejects(fn()=>new InventoryPolicy(0,0,0),'Invalid inventory policy');
rejects(fn()=>new InventoryPolicy(301,-1,0),'Invalid inventory policy');
rejects(fn()=>new InventoryPolicy(301,0,-1),'Invalid inventory policy');
rejects(fn()=>$run(null,$obs(5,0,$other)),'another product');
rejects(fn()=>$run($obs(5,0,$other),$obs(5)),'another product');
rejects(fn()=>$run(null,$obs(5),-1),'Invalid reconciliation');
echo "Inventory preview: {$checks} checks passed.\n";
