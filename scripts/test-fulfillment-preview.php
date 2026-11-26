<?php
declare(strict_types=1);

use Bakata\Core\Fulfillment\FulfillmentEvent;
use Bakata\Core\Fulfillment\FulfillmentPreview;
use Bakata\Core\Fulfillment\FulfillmentState as S;
use Bakata\Core\Orders\OrderLine;
use Bakata\Core\Orders\OrderPreview;

require_once __DIR__ . '/../wp-content/plugins/bakata-core/src/Orders/OrderPreview.php';
require_once __DIR__ . '/../wp-content/plugins/bakata-core/src/Fulfillment/FulfillmentPreview.php';

$checks = 0;
function check(bool $condition, string $label): void {
    global $checks;
    if (!$condition) { throw new RuntimeException('Failed: '.$label); }
    $checks++;
}
function rejects(callable $fn, string $class, string $message): void {
    try { $fn(); } catch (Throwable $e) {
        check($e instanceof $class && str_contains($e->getMessage(),$message),$message);
        return;
    }
    throw new RuntimeException('Expected rejection: '.$message);
}

$now = new DateTimeImmutable('2026-01-01T00:00:10Z');
$source = hash('sha256','synthetic');
$order = (new OrderPreview())->prepare('ci-store',42,'processing',true,false,'CO',[
    new OrderLine(1,10,2,'supplier-a',$source),
    new OrderLine(2,11,1,'supplier-b',$source),
]);
[$a,$b] = $order['groups'];
$preview = new FulfillmentPreview();
$event = static fn(array $group, string $id, S $state, int $offset=0, ?string $carrier=null, ?string $tracking=null)
    => new FulfillmentEvent($group['operationReference'],$group['contentFingerprint'],$id,$state,
        $now->modify(sprintf('%+d seconds',$offset)),$carrier,$tracking);
$run = static fn(array $group,array $events) => $preview->replay(
    $group['operationReference'],$group['contentFingerprint'],$events,$now
);
$accept = $event($a,'a1',S::Accepted,-8);
$prep = $event($a,'a2',S::Preparing,-7);
$ship = $event($a,'a3',S::Shipped,-6,'ci-carrier','TEST-001');
$transit = $event($a,'a4',S::InTransit,-5);
$issue = $event($a,'a5',S::DeliveryException,-4);
$recover = $event($a,'a6',S::InTransit,-3);
$deliver = $event($a,'a7',S::Delivered,-2);
$return = $event($a,'a8',S::Returned,-1);
$history=[$accept,$prep,$ship,$transit,$issue,$recover,$deliver];
$empty=$run($a,[]);
check($empty->state===S::AwaitingConfirmation && $empty->lastEventAt===null && $empty->uniqueEvents===0,'empty replay');
check($run($a,[$accept])->state===S::Accepted,'accepted');
check($run($a,[$accept,$prep])->state===S::Preparing,'preparing');
$shipped=$run($a,[$accept,$prep,$ship]);
check($shipped->state===S::Shipped && $shipped->carrier==='ci-carrier' && $shipped->trackingNumber==='TEST-001','shipment tracking');
check($run($a,[$accept,$prep,$ship,$transit,$issue])->state===S::DeliveryException,'delivery exception');
$delivered=$run($a,$history);
check($delivered->state===S::Delivered && $delivered->trackingNumber==='TEST-001' && $delivered->uniqueEvents===7,'recovered and delivered');
check($delivered->lastEventAt==$deliver->occurredAt,'last event time');
$replay=$run($a,[...$history,$ship,$accept]);
check($replay->state===S::Delivered && $replay->uniqueEvents===7 && $replay->duplicateEvents===2,'late duplicate ignored');
check($run($a,[...$history,$return])->state===S::Returned,'return after delivery');
check($run($a,[$event($a,'reject',S::Rejected)])->state===S::Rejected,'rejected');
check($run($a,[$accept,$event($a,'cancel',S::Cancelled)])->state===S::Cancelled,'pre-shipment cancellation');
check($run($a,[$accept,$ship,$deliver])->state===S::Delivered,'accepted direct shipment and delivery');
rejects(fn()=>$run($a,[$deliver]),RuntimeException::class,'Invalid fulfillment state');
rejects(fn()=>$run($a,[$accept,$prep,$ship,$event($a,'cancel',S::Cancelled)]),RuntimeException::class,'Invalid fulfillment state');
rejects(fn()=>$run($a,[...$history,$event($a,'regress',S::InTransit)]),RuntimeException::class,'Invalid fulfillment state');
rejects(fn()=>$run($a,[$accept,$event($a,'a1',S::Preparing,-7)]),RuntimeException::class,'Conflicting fulfillment event');
rejects(fn()=>$run($a,[$accept,$event($a,'old',S::Preparing,-9)]),RuntimeException::class,'out of order');
rejects(fn()=>$run($a,[$event($a,'future',S::Accepted,1)]),RuntimeException::class,'future');
rejects(fn()=>$run($a,[$event($b,'wrong',S::Accepted)]),RuntimeException::class,'does not match');
$changed=$a;
$changed['contentFingerprint']=hash('sha256','edited');
rejects(fn()=>$run($a,[$event($changed,'changed',S::Accepted)]),RuntimeException::class,'does not match');
rejects(fn()=>$event($a,'bad',S::Shipped),InvalidArgumentException::class,'Shipment requires');
rejects(fn()=>$event($a,'bad',S::Shipped,0,'carrier','https://example.invalid'),InvalidArgumentException::class,'Shipment requires');
rejects(fn()=>$event($a,'bad',S::Preparing,0,'carrier','TEST'),InvalidArgumentException::class,'only supplied');
rejects(fn()=>$event($a,'bad',S::AwaitingConfirmation),InvalidArgumentException::class,'Invalid fulfillment event');
rejects(fn()=>$run($a,array_fill(0,1001,$accept)),InvalidArgumentException::class,'Invalid fulfillment replay');
$emptyB=$run($b,[]);
check($preview->summarize($order,[$empty,$emptyB])['state']==='awaiting_confirmation','aggregate initial');
check($preview->summarize($order,[$shipped,$emptyB])['state']==='in_progress','aggregate active');
check($preview->summarize($order,[$delivered,$emptyB])['state']==='partial_delivery','partial delivery');
$exception=$run($a,[$accept,$prep,$ship,$transit,$issue]);
check($preview->summarize($order,[$exception,$emptyB])['state']==='attention_required','exception takes priority');
$deliveredB=$run($b,[$event($b,'b1',S::Accepted,-4),$event($b,'b2',S::Shipped,-3,'ci-carrier','TEST-002'),$event($b,'b3',S::Delivered,-2)]);
$summary=$preview->summarize($order,[$deliveredB,$delivered]);
check($summary['state']==='all_delivered' && $summary['counts']['delivered']===2 && $summary['groupCount']===2,'all delivered');
check(!str_contains(json_encode($summary,JSON_THROW_ON_ERROR),'TEST-'),'tracking excluded from aggregate');
$cancelledB=$run($b,[$event($b,'cancel',S::Cancelled)]);
$rejectedA=$run($a,[$event($a,'reject',S::Rejected)]);
check($preview->summarize($order,[$rejectedA,$cancelledB])['state']==='closed_without_delivery','all closed without delivery');
check($preview->summarize($order,[$delivered,$cancelledB])['state']==='attention_required','partial delivery with cancellation requires attention');
rejects(fn()=>$preview->summarize($order,[$delivered]),InvalidArgumentException::class,'incomplete');
rejects(fn()=>$preview->summarize($order,[$delivered,$delivered]),RuntimeException::class,'does not match');
rejects(fn()=>$preview->summarize($order,[$run($changed,[]),$emptyB]),RuntimeException::class,'does not match');
echo "Fulfillment preview: {$checks} checks passed.\n";
