<?php
declare(strict_types=1);

use Bakata\Core\Webhooks\EventScope;
use Bakata\Core\Webhooks\ReceiptLedger;
use Bakata\Core\Webhooks\ReceiptResult as R;
use Bakata\Core\Webhooks\WebhookInbox;
use Bakata\Core\Orders\OrderLine;
use Bakata\Core\Orders\OrderPreview;

require_once __DIR__.'/../wp-content/plugins/bakata-core/src/Fulfillment/FulfillmentPreview.php';
require_once __DIR__.'/../wp-content/plugins/bakata-core/src/Orders/OrderPreview.php';
require_once __DIR__.'/../wp-content/plugins/bakata-core/src/Webhooks/SignedEvent.php';
require_once __DIR__.'/../wp-content/plugins/bakata-core/src/Webhooks/ReceiptLedger.php';
require_once __DIR__.'/../wp-content/plugins/bakata-core/src/Webhooks/WebhookInbox.php';

final class MemoryLedger implements ReceiptLedger {
    public array $rows = [];
    public function claim(string $key,string $fingerprint,DateTimeImmutable $now): R {
        if (isset($this->rows[$key])) {
            if ($this->rows[$key] !== $fingerprint) { throw new RuntimeException('Receipt identity conflict.'); }
            return R::Duplicate;
        }
        $this->rows[$key]=$fingerprint;
        return R::Recorded;
    }
    public function matches(string $key,string $fingerprint): bool { return ($this->rows[$key]??null)===$fingerprint; }
}
$checks=0;
function check(bool $condition,string $label): void {
    global $checks;
    if (!$condition) { throw new RuntimeException('Failed: '.$label); }
    $checks++;
}
function rejects(callable $fn,string $message): void {
    try { $fn(); } catch (RuntimeException|InvalidArgumentException $e) {
        check(str_contains($e->getMessage(),$message),$message); return;
    }
    throw new RuntimeException('Expected rejection: '.$message);
}
$now=new DateTimeImmutable('2026-01-01T00:00:10Z');
$ts=(string)$now->getTimestamp();
$scope=new EventScope('ci-store','ci-supplier','ci-account');
$other=new EventScope('ci-store','ci-supplier','other-account');
$secret=random_bytes(32);
$rotated=random_bytes(32);
$group=(new OrderPreview())->prepare('ci-store',42,'processing',true,false,'CO',[
    new OrderLine(1,10,2,'ci-supplier',hash('sha256','sku')),
])['groups'][0];
$data=[
    'operationReference'=>$group['operationReference'],'contentFingerprint'=>$group['contentFingerprint'],
    'eventId'=>'event-1','state'=>'accepted','occurredAt'=>'2026-01-01T00:00:00Z','carrier'=>null,'trackingNumber'=>null,
];
$encode=static fn(array $d)=>json_encode($d,JSON_THROW_ON_ERROR);
$body=$encode($data);
$sign=static fn(EventScope $s,string $key,string $t,string $b,string $k)=>'v1='.hash_hmac('sha256',
    json_encode(['bakata-webhook-v1',...$s->values(),$key,$t,hash('sha256',$b)],JSON_THROW_ON_ERROR),$k);
$ledger=new MemoryLedger();
$inbox=new WebhookInbox($ledger);
$receive=static fn(string $b,?string $sig=null,?string $time=null,?EventScope $s=null,string $key='key-1',?string $k=null)
    =>$inbox->receive($s??$scope,$key,$k??$secret,$time??$ts,
        $sig??$sign($s??$scope,$key,$time??$ts,$b,$k??$secret),$b,$now,300);
rejects(fn()=>$receive($body),'Unregistered');
check(count($ledger->rows)===0,'unregistered event not recorded');
check($inbox->registerPreview($scope,$group,$now)===R::Recorded,'register operation');
check($inbox->registerPreview($scope,$group,$now)===R::Duplicate,'operation replay');
rejects(fn()=>$inbox->registerPreview($other,$group,$now),'identity conflict');
rejects(fn()=>$inbox->registerPreview($scope,array_replace($group,['contentFingerprint'=>hash('sha256','edit')]),$now),'identity conflict');
rejects(fn()=>$receive($body.' ',$sign($scope,'key-1',$ts,$body,$secret)),'authentication failed');
rejects(fn()=>$receive($body,$sign($scope,'key-1',$ts,$body,$secret),s:$other),'authentication failed');
rejects(fn()=>$receive($body,time:(string)($now->getTimestamp()-301)),'outside window');
rejects(fn()=>$receive($body,time:(string)($now->getTimestamp()+301)),'outside window');
rejects(fn()=>$receive($body,'bad'),'Invalid signed event envelope');
rejects(fn()=>$receive($body,k:'too-short'),'Invalid signed event envelope');
rejects(fn()=>$receive(str_repeat('x',16385)),'Invalid signed event envelope');
rejects(fn()=>$receive('{broken'),'Invalid signed event content');
rejects(fn()=>$receive($encode($data+['extra'=>'unexpected'])),'Invalid event schema');
rejects(fn()=>$receive($encode(array_replace($data,['state'=>'unknown']))),'Invalid event state');
rejects(fn()=>$receive($encode(array_replace($data,['occurredAt'=>'2026-01-01T00:00:11Z']))),'Invalid event time');
rejects(fn()=>$receive($encode(array_replace($data,['occurredAt'=>'2026-02-30T00:00:00Z']))),'Invalid event time');
rejects(fn()=>$receive($encode(array_replace($data,['state'=>'shipped']))),'Invalid signed event content');
rejects(fn()=>$receive($body,s:$other),'Unregistered');
check(count($ledger->rows)===1,'rejections do not write event receipt');
check($receive($body)===R::Recorded,'valid event');
check($receive($body)===R::Duplicate,'event retry');
check($receive($body,key:'key-2',k:$rotated)===R::Duplicate,'key rotation retains receipt identity');
check($receive($encode(array_reverse($data,true)))===R::Duplicate,'normalized fingerprint independent of field order');
rejects(fn()=>$receive($encode(array_replace($data,['state'=>'preparing']))),'identity conflict');
check(count($ledger->rows)===2,'only binding and unique receipt');
check($receive($encode(array_replace($data,['eventId'=>'event-2','state'=>'shipped','carrier'=>'ci-carrier','trackingNumber'=>'TEST-123'])))===R::Recorded,'shipment receipt');
check(!str_contains(json_encode($ledger->rows,JSON_THROW_ON_ERROR),'TEST-123'),'no tracking data in ledger');
echo "Webhook reference protocol: {$checks} checks passed.\n";
