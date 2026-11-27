<?php
// Standalone policy for the future live image. Not loaded by fixture or production.
// No transport: this predicate only validates the actual hardened connector request.
function bakata_research_catalog_request_allowed($url,$args,$scope,$token,$now)
{
    if ($url !== 'https://api.dropi.co/integrations/products/index'
        || !is_array($args) || !is_array($scope) || !is_int($now)
        || array_diff(array_keys($scope),['run','store','page','until','attempt'])
        || count($scope)!==5 || !is_string($scope['run']??null)
        || !preg_match('/\Apilot-[A-Za-z0-9_-]{1,58}\z/D',$scope['run'])
        || !is_string($scope['store']??null) || !preg_match('/\A[1-9][0-9]{0,9}\z/D',$scope['store'])
        || !is_int($scope['page']??null) || $scope['page']<1 || $scope['page']>3
        || !is_int($scope['until']??null) || $scope['until']<=$now || $scope['until']>$now+1800
        || !is_string($scope['attempt']??null) || !preg_match('/\A[0-9a-f]{32}\z/D',$scope['attempt'])
        || !is_string($token) || !preg_match('/\A[!-~]{1,1000}\z/D',$token)) {
        return false;
    }
    // WordPress may add defaults to the array. All security-relevant settings
    // must be explicit and exact; no cookies, redirects or alternate destination.
    if (($args['method']??null)!=='POST' || ($args['sslverify']??null)!==true
        || ($args['reject_unsafe_urls']??null)!==true || ($args['redirection']??null)!==0
        || ($args['timeout']??null)!==15 || ($args['blocking']??null)!==true
        || ($args['limit_response_size']??null)!==524288 || ($args['cookies']??null)!==[]
        || !is_array($args['headers']??null) || count($args['headers'])!==2
        || ($args['headers']['Content-Type']??null)!=='application/json;charset=UTF-8'
        || !is_string($args['headers']['dropi-integration-key']??null)
        || !hash_equals($token,$args['headers']['dropi-integration-key'])
        || !is_string($args['body']??null) || strlen($args['body'])>1024) {
        return false;
    }
    $expected=['startData'=>($scope['page']-1)*10,'pageSize'=>10,'order_type'=>'asc','order_by'=>'id',
        'keywords'=>'','active'=>true,'no_count'=>true,'integration'=>true,'get_stock'=>false];
    // Match the exact original json_encode serialization. Reject duplicate keys,
    // extra filters, type coercion, or unexpected encoding, not merely parsed shape.
    return hash_equals(json_encode($expected),$args['body']);
}
