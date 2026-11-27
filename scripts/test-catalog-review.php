<?php
declare(strict_types=1);
require __DIR__.'/../wp-content/plugins/bakata-core/src/Intelligence/CatalogReviewSnapshot.php';
use Bakata\Core\Intelligence\CatalogReviewSnapshot as Snapshot;
function ck(bool $ok): void { if (!$ok) throw new RuntimeException('Catalog review assertion failed.'); }
function reject(string $raw): void {
    try { Snapshot::decode($raw,time()); } catch (InvalidArgumentException|JsonException $e) { return; }
    throw new RuntimeException('Invalid catalog export accepted.');
}
function encode(array $data): string { return json_encode($data,JSON_THROW_ON_ERROR|JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_LINE_TERMINATORS); }
$raw=stream_get_contents(STDIN,Snapshot::MAX_BYTES+1);
$data=Snapshot::decode($raw,time());
$row=$data['snapshot']['rows'][0];
ck($row['sku']==='025216' && $row['base_price']==='7000.25' && $row['simple_stock']===412);
ck(count(Snapshot::filter([$row],'025216','positive'))===1);
ck(Snapshot::filter([$row],'','zero')===[]);
ck(Snapshot::stockState(array_replace($row,['simple_stock'=>0]))==='zero');
ck(Snapshot::stockState(array_replace($row,['simple_stock'=>null]))==='unknown');
foreach (['token'=>'canary','score'=>100,'base_price'=>7000.25,'simple_stock'=>-1,'type'=>'unresolved'] as $key=>$value) {
    $bad=$data; $bad['snapshot']['rows'][0][$key]=$value; reject(encode($bad));
}
$bad=$data; $bad['snapshot']['rows'][]=$row; reject(encode($bad));
$bad=$data; $bad['snapshot']['offset']=999; reject(encode($bad));
$bad=$data; $bad['snapshot']['captured_at']='2099-01-01T00:00:00Z'; reject(encode($bad));
reject('{"schema":"fake",'.substr(trim($raw),1));
echo "Catalog review Python/PHP contract passed.\n";
