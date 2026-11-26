<?php
declare(strict_types=1);

use Bakata\Core\Webhooks\EventScope;
use Bakata\Core\Webhooks\ReceiptResult as R;
use Bakata\Core\Webhooks\WpReceiptLedger;
use Bakata\Core\Webhooks\WebhookInbox;

if (!defined('WP_CLI') || !WP_CLI || getenv('BAKATA_CI_FIXTURES') !== '1'
    || !in_array(wp_parse_url(home_url(),PHP_URL_HOST),['localhost','127.0.0.1'],true)
    || !class_exists(WpReceiptLedger::class)) {
    throw new RuntimeException('Refusing ledger fixtures outside isolated CI.');
}
$GLOBALS['bakata_receipt_checks']=0;
function receipt_check(bool $condition,string $label): void {
    if (!$condition) { throw new RuntimeException('Failed: '.$label); }
    $GLOBALS['bakata_receipt_checks']++;
}
function receipt_reject(callable $fn,string $message): void {
    try { $fn(); } catch (RuntimeException $e) {
        receipt_check(str_contains($e->getMessage(),$message),$message); return;
    }
    throw new RuntimeException('Expected rejection: '.$message);
}
global $wpdb;
$admins=get_users(['role'=>'administrator','number'=>1,'fields'=>'ID']);
if (!$admins) { throw new RuntimeException('CI administrator missing.'); }
$previous=get_current_user_id();
$now=new DateTimeImmutable('now');
$key=hash('sha256','ci-receipt');
$fp=hash('sha256','original');
try {
    $ledger=new WpReceiptLedger($wpdb);
    wp_set_current_user(0);
    receipt_reject(fn()=>$ledger->install(),'administrator capability');
    wp_set_current_user((int)$admins[0]);
    $ledger->install();
    $ledger->install();
    receipt_check(!$ledger->matches($key,$fp),'new receipt absent');
    receipt_check($ledger->claim($key,$fp,$now)===R::Recorded,'first receipt recorded');
    $second=new WpReceiptLedger($wpdb);
    receipt_check($second->claim($key,$fp,$now)===R::Duplicate,'durable duplicate across instances');
    receipt_reject(fn()=>$second->claim($key,hash('sha256','changed'),$now),'identity conflict');
    receipt_check($second->matches($key,$fp),'original fingerprint retained');
    receipt_check(!$second->matches($key,hash('sha256','changed')),'conflict not stored');
    $scope=new EventScope('ci-store','ci-supplier','ci-account');
    $group=['supplierId'=>'ci-supplier','operationReference'=>hash('sha256','operation'),'contentFingerprint'=>hash('sha256','content')];
    $inbox=new WebhookInbox($ledger);
    receipt_check($inbox->registerPreview($scope,$group,$now)===R::Recorded,'binding recorded');
    $body=json_encode([
        'operationReference'=>$group['operationReference'],'contentFingerprint'=>$group['contentFingerprint'],
        'eventId'=>'ci-event','state'=>'shipped','occurredAt'=>gmdate('Y-m-d\TH:i:s\Z',$now->getTimestamp()),
        'carrier'=>'ci-carrier','trackingNumber'=>'CI-SYNTHETIC-TRACKING',
    ],JSON_THROW_ON_ERROR);
    $secret=random_bytes(32);
    $ts=(string)$now->getTimestamp();
    $sig='v1='.hash_hmac('sha256',json_encode(['bakata-webhook-v1',...$scope->values(),'ci-key',$ts,hash('sha256',$body)],JSON_THROW_ON_ERROR),$secret);
    receipt_check($inbox->receive($scope,'ci-key',$secret,$ts,$sig,$body,$now,300)===R::Recorded,'signed receipt stored');
    receipt_check((new WebhookInbox($second))->receive($scope,'ci-key',$secret,$ts,$sig,$body,$now,300)===R::Duplicate,'signed replay persisted');
    $table=$wpdb->prefix.'bakata_receipts_v1';
    $rows=$wpdb->get_results("SELECT * FROM {$table}",ARRAY_A);
    receipt_check(count($rows)===3,'three unique records');
    receipt_check(!str_contains(json_encode($rows,JSON_THROW_ON_ERROR),'CI-SYNTHETIC-TRACKING'),'no raw guide or payload');
} finally { wp_set_current_user($previous); }
$checks=$GLOBALS['bakata_receipt_checks'];
if ($checks!==12) { throw new RuntimeException('Unexpected ledger check count: '.$checks); }
echo "Webhook durable receipts: {$checks} checks passed.\n";
