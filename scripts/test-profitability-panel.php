<?php
declare(strict_types=1);
require __DIR__.'/../wp-content/plugins/bakata-core/src/Intelligence/PreviewSnapshot.php';
require __DIR__.'/../wp-content/plugins/bakata-core/src/Intelligence/CatalogReviewSnapshot.php';
require __DIR__.'/../wp-content/plugins/bakata-core/src/Intelligence/ProfitabilitySnapshot.php';
use Bakata\Core\Intelligence\ProfitabilitySnapshot as Profit;
use Bakata\Core\Intelligence\CatalogReviewSnapshot as Catalog;
function ck(bool $ok): void { if (!$ok) throw new RuntimeException('Profitability assertion failed.'); }
function reject(array $d): void {
    try { Profit::decode(json_encode($d,JSON_THROW_ON_ERROR|JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_LINE_TERMINATORS),time()); }
    catch (InvalidArgumentException|JsonException $e) { return; }
    throw new RuntimeException('Invalid dossier accepted.');
}
$raw=stream_get_contents(STDIN,Profit::MAX_BYTES+1);
$d=Profit::decode($raw,time());
$p=Catalog::decode(file_get_contents('/tmp/bakata-catalog-review.json'),time());
$row=$p['snapshot']['rows'][0];
ck(Profit::matches($d,$p,$row));
ck(!Profit::matches($d,$p,array_replace($row,['sku'=>'other'])));
ck(!Profit::matches($d,$p,array_replace($row,['simple_stock'=>0])));
ck($d['evaluation']['contribution_minor']===1472000);
foreach (['contribution_minor'=>1,'margin_pct'=>'99.99','score'=>'100.00','coverage_pct'=>99,'currency'=>'USD'] as $key=>$value) {
    $bad=$d; $bad['evaluation'][$key]=$value; reject($bad);
}
$bad=$d; $bad['approval_granted']=true; reject($bad);
$bad=$d; $bad['valid_until']=$d['as_of']; reject($bad);
$bad=$d; $bad['evaluation']['economics']['supplier_cost_minor']=700025; reject($bad);
$bad=$d; $bad['evaluation']['components'][0]['weight']=99; reject($bad);
$bad=$d; $bad['catalog']['token']='canary'; reject($bad);
echo "Profitability contract and capture identity passed.\n";
