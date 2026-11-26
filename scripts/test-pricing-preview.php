<?php
declare(strict_types=1);

use Bakata\Core\Pricing\UnitCosts;
use Bakata\Core\Pricing\PricingPolicy;
use Bakata\Core\Pricing\PricingPreview;

require_once __DIR__ . '/../wp-content/plugins/bakata-core/src/Pricing/PricingPreview.php';

$checks = 0;
function check(bool $condition, string $label): void {
    global $checks;
    if (!$condition) { throw new RuntimeException('Failed: ' . $label); }
    $checks++;
}
function rejects(callable $fn, string $class, string $message): void {
    try { $fn(); } catch (Throwable $e) {
        check($e instanceof $class && str_contains($e->getMessage(), $message), $message);
        return;
    }
    throw new RuntimeException('Expected rejection: ' . $message);
}
$preview = new PricingPreview();
$cost = new UnitCosts('COP', 2, 2_500_000, 1_200_000, 100_000, 200_000, 0);
$policy = new PricingPolicy('COP', 2, 400, 2500, 100_000, 20_000_000);
$quote = $preview->propose($cost, $policy);
check($cost->total() === 4_000_000, 'explicit unit costs');
check($quote->priceMinor === 5_700_000, 'aligned gross price');
check($quote->variableDeductionsMinor === 228_000, 'variable deductions');
check($quote->contributionMinor === 1_472_000, 'contribution');
check($quote->contributionBps === 2582 && $quote->meetsTarget, 'margin floor and target');
check(!$preview->evaluate($cost, $policy, 5_600_000)->meetsTarget, 'preceding aligned price fails');
check($quote->currency === 'COP' && $quote->minorUnit === 2, 'currency preserved');
$negative = $preview->evaluate($cost, $policy, 1_000_001);
check($negative->contributionMinor < 0 && $negative->contributionBps < 0 && !$negative->meetsTarget, 'loss is not suppressed');
$small = new UnitCosts('COP', 0, 1, 0, 0, 0, 0);
$round = new PricingPolicy('COP', 0, 3333, 3333, 1, 100);
check($preview->evaluate($small, $round, 3)->meetsTarget && $preview->propose($small, $round)->priceMinor === 3, 'small integer rounding');
$zero = new UnitCosts('COP', 0, 0, 0, 0, 0, 0);
check($preview->propose($zero,new PricingPolicy('COP',0,0,0,7,100))->priceMinor === 7,'positive price with zero costs');
$loss = $preview->evaluate(new UnitCosts('COP',0,5,0,0,0,0),new PricingPolicy('COP',0,0,0,1,20),3);
check($loss->contributionBps === -6667,'negative floor');
rejects(fn()=>new UnitCosts('COP',2,-1,0,0,0,0),InvalidArgumentException::class,'Invalid fixed');
rejects(fn()=>new UnitCosts('COP',2,UnitCosts::MAX_MINOR,1,0,0,0),InvalidArgumentException::class,'Total cost');
rejects(fn()=>new PricingPolicy('COP',2,5000,5000,1,100),InvalidArgumentException::class,'Invalid pricing policy');
rejects(fn()=>new PricingPolicy('COP',2,0,0,0,100),InvalidArgumentException::class,'Invalid pricing policy');
rejects(fn()=>$preview->propose($cost,new PricingPolicy('USD',2,400,2500,100,20_000_000)),InvalidArgumentException::class,'Currency or minor unit');
rejects(fn()=>$preview->propose($cost,new PricingPolicy('COP',0,400,2500,100,20_000_000)),InvalidArgumentException::class,'Currency or minor unit');
rejects(fn()=>$preview->propose($cost,new PricingPolicy('COP',2,400,2500,100_000,5_600_000)),RuntimeException::class,'No price meets');
rejects(fn()=>$preview->evaluate($cost,$policy,0),InvalidArgumentException::class,'Price outside');
rejects(fn()=>$preview->evaluate($cost,$policy,20_000_001),InvalidArgumentException::class,'Price outside');
$max = UnitCosts::MAX_MINOR;
check($preview->propose(new UnitCosts('COP',2,$max,0,0,0,0),new PricingPolicy('COP',2,0,0,1,$max))->priceMinor === $max,'integer upper bound');
// Exhaustive oracle on small scenarios, including rounding discontinuities.
foreach ([0,1,2,7,19] as $fixed) {
    foreach ([0,1234,3333,5000,9999] as $fee) {
        foreach ([0,777,3333,4999] as $target) {
            if ($fee + $target >= 10000) { continue; }
            foreach ([1,3,7] as $step) {
                $c = new UnitCosts('COP',0,$fixed,0,0,0,0);
                $p = new PricingPolicy('COP',0,$fee,$target,$step,100);
                $expected = null;
                for ($price=$step;$price<=100;$price+=$step) {
                    $deduction = intdiv($price*$fee+9999,10000);
                    if (($price-$fixed-$deduction)*10000 >= $price*$target) { $expected=$price; break; }
                }
                if ($expected === null) {
                    rejects(fn()=>$preview->propose($c,$p),RuntimeException::class,'No price meets');
                } else {
                    check($preview->propose($c,$p)->priceMinor === $expected,'small scenario oracle');
                }
            }
        }
    }
}
echo "Pricing preview: {$checks} checks passed.\n";
