<?php
declare(strict_types=1);

use Bakata\Core\Orders\OrderLine;
use Bakata\Core\Orders\OrderPreview;

require_once __DIR__ . '/../wp-content/plugins/bakata-core/src/Orders/OrderPreview.php';

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
$preview = new OrderPreview();
$id = hash('sha256', 'fixture');
$a = new OrderLine(10,1,2,'supplier-a',$id);
$b = new OrderLine(11,2,1,'supplier-b',$id);
$c = new OrderLine(12,1,3,'supplier-a',$id);
$run = static fn(array $lines, string $status='processing', bool $paid=true, bool $refund=false,
    string $country='CO', string $scope='ci-store', int $order=42)
    => $preview->prepare($scope,$order,$status,$paid,$refund,$country,$lines);
$result = $run([$b,$c,$a]);
check($result['state']==='preview_only' && $result['orderId']===42,'preview only');
check(count($result['groups'])===2,'supplier grouping');
check($result['groups'][0]['supplierId']==='supplier-a','stable group order');
check(array_column($result['groups'][0]['lines'],'lineId')===[10,12],'stable line order');
check($result===$run([$a,$b,$c]),'deterministic regardless of input order');
$changed = $run([new OrderLine(10,1,5,'supplier-a',$id),$c,$b]);
check($changed['groups'][0]['operationReference']===$result['groups'][0]['operationReference'],'reference stable on line edit');
check($changed['groups'][0]['contentFingerprint']!==$result['groups'][0]['contentFingerprint'],'line edit changes fingerprint');
check($result['groups'][0]['operationReference']!==$result['groups'][1]['operationReference'],'supplier isolation');
check($result['groups'][0]['operationReference']!==$run([$a],scope:'other')['groups'][0]['operationReference'],'store isolation');
check($result['groups'][0]['operationReference']!==$run([$a],order:43)['groups'][0]['operationReference'],'order isolation');
foreach (['pending','on-hold','completed','cancelled','refunded','failed','checkout-draft'] as $status) {
    rejects(fn()=>$run([$a],status:$status),RuntimeException::class,'not eligible');
}
rejects(fn()=>$run([$a],paid:false),RuntimeException::class,'not eligible');
rejects(fn()=>$run([$a],refund:true),RuntimeException::class,'not eligible');
rejects(fn()=>$run([$a],country:'US'),RuntimeException::class,'Destination');
rejects(fn()=>$run([$a],country:''),RuntimeException::class,'Destination');
rejects(fn()=>$run([$a,$a]),InvalidArgumentException::class,'duplicate');
rejects(fn()=>$run([]),InvalidArgumentException::class,'Invalid order preview');
rejects(fn()=>$run(array_fill(0,251,$a)),InvalidArgumentException::class,'Invalid order preview');
rejects(fn()=>$run([$a],scope:''),InvalidArgumentException::class,'Invalid order preview');
rejects(fn()=>new OrderLine(0,1,2,'supplier-a',$id),InvalidArgumentException::class,'Invalid order line');
rejects(fn()=>new OrderLine(1,1,0,'supplier-a',$id),InvalidArgumentException::class,'Invalid order line');
rejects(fn()=>new OrderLine(1,1,2,'supplier-a','invalid'),InvalidArgumentException::class,'Invalid order line');
echo "Order preview: {$checks} checks passed.\n";
