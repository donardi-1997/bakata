<?php
declare(strict_types=1);
require __DIR__.'/../wp-content/plugins/bakata-core/src/Intelligence/AlertDashboardSnapshot.php';
use Bakata\Core\Intelligence\AlertDashboardSnapshot as S;
function ck(bool $ok): void { if (!$ok) throw new RuntimeException('Alert dashboard assertion failed.'); }
function reject(array $data): void {
    try { S::decode(json_encode($data,JSON_THROW_ON_ERROR|JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_LINE_TERMINATORS),time()); }
    catch (InvalidArgumentException|JsonException $e) { return; }
    throw new RuntimeException('Invalid alert dashboard accepted.');
}
$d=S::decode(stream_get_contents(STDIN,S::MAX_BYTES+1),time());
ck(count($d['rows'])===2 && $d['counts']['open']===1 && $d['counts']['resolved']===1);
ck(count(S::filter($d['rows'],'resolved','','025216'))===1);
ck(S::filter($d['rows'],'acknowledged','','')===[]);
$bad=$d; $bad['counts']['open']=0; reject($bad);
$bad=$d; $bad['rows'][0]['signal_id']=str_repeat('0',64); reject($bad);
$bad=$d; $bad['delivery_enabled']=true; reject($bad);
$bad=$d; $bad['rows'][0]['token']='canary'; reject($bad);
$bad=$d; $bad['rows'][0]['state']='approved'; reject($bad);
echo "Alert dashboard export contract passed.\n";
