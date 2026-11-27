<?php
declare(strict_types=1);
require __DIR__.'/../infra/research-worker/catalog-egress-policy.php';
function check($condition) {
    if (!$condition) { fwrite(STDERR,"Research egress contract failed\n"); exit(1); }
}
$now=1795748400;
$url='https://api.dropi.co/integrations/products/index';
$token='fixture-token-canary';
$scope=['run'=>'pilot-fixture','store'=>'7','page'=>2,'until'=>$now+60,'attempt'=>str_repeat('a',32)];
$body=['startData'=>10,'pageSize'=>10,'order_type'=>'asc','order_by'=>'id','keywords'=>'','active'=>true,'no_count'=>true,'integration'=>true,'get_stock'=>false];
$args=['body'=>json_encode($body),'timeout'=>15,'redirection'=>0,'httpversion'=>'1.0','blocking'=>true,
    'method'=>'POST','headers'=>['Content-Type'=>'application/json;charset=UTF-8','dropi-integration-key'=>$token],
    'cookies'=>[],'sslverify'=>true,'reject_unsafe_urls'=>true,'limit_response_size'=>524288];
check(bakata_research_catalog_request_allowed($url,$args,$scope,$token,$now));
foreach (['http://api.dropi.co/integrations/products/index',$url.'?x=1',$url.'/','https://api.dropi.co.evil.invalid/integrations/products/index','https://api.dropi.co/integrations/orders'] as $bad) {
    check(!bakata_research_catalog_request_allowed($bad,$args,$scope,$token,$now));
}
foreach (['method'=>'GET','sslverify'=>false,'redirection'=>1,'timeout'=>16,'reject_unsafe_urls'=>false,'blocking'=>false,'limit_response_size'=>524289,'cookies'=>['a'=>'b'],
    'headers'=>['Content-Type'=>'application/json;charset=UTF-8','dropi-integration-key'=>'wrong']] as $key=>$value) {
    check(!bakata_research_catalog_request_allowed($url,array_replace($args,[$key=>$value]),$scope,$token,$now));
}
foreach (['startData'=>0,'pageSize'=>20,'keywords'=>'search','active'=>false,'warehouse_id'=>9] as $key=>$value) {
    check(!bakata_research_catalog_request_allowed($url,array_replace($args,['body'=>json_encode(array_replace($body,[$key=>$value]))]),$scope,$token,$now));
}
check(!bakata_research_catalog_request_allowed($url,array_replace($args,['body'=>'{"startData":10,'.substr($args['body'],1)]),$scope,$token,$now));
foreach (['run'=>'fixture-run','page'=>4,'store'=>'0','until'=>$now,'attempt'=>'invalid'] as $key=>$value) {
    check(!bakata_research_catalog_request_allowed($url,$args,array_replace($scope,[$key=>$value]),$token,$now));
}
check(!bakata_research_catalog_request_allowed($url,$args,$scope,"different",$now));
echo "Research egress: accepted exact synthetic connector request; rejected alternate URL, unsafe TLS, credentials, payload and scope.\n";
