<?php
declare(strict_types=1);
// Standalone PHP process: the HTTP function below is a stub, not WordPress.
define('ABSPATH', __DIR__);
define('OBJECT','OBJECT');
class WP_List_Table {}
class WP_Error {}
function ck($ok) { if (!$ok) throw new RuntimeException('Operational fixture assertion failed'); }
$scenario=$argv[2]??'ok';
$offset=$scenario==='page2'?10:0;
define('BAKATA_DROPIFY_CATALOG_READ', true);
define('BAKATA_DROPIFY_CATALOG_APPROVAL_REF','ci-approval');
define('BAKATA_DROPIFY_CATALOG_APPROVED_UNTIL',time()+($scenario==='expired'?-1:600));
define('BAKATA_DROPIFY_CATALOG_APPROVED_STORE','7');
define('BAKATA_DROPIFY_CATALOG_APPROVED_OFFSET',$offset);
define('BAKATA_DROPIFY_CATALOG_APPROVED_QUERY','fixture');
$_SERVER['REQUEST_METHOD']=$scenario==='get'?'GET':'POST';
$_POST=['bk_catalog_read'=>'1','_wpnonce'=>'fixture-nonce'];
function wp_get_environment_type() { return $GLOBALS['scenario']==='production'?'production':'staging'; }
function current_user_can($cap) { return $cap==='manage_options' && $GLOBALS['scenario']!=='denied'; }
function wp_unslash($value) {return $value;}
function wp_verify_nonce($value,$action) {return $GLOBALS['scenario']!=='nonce' && $value==='fixture-nonce' && $action==='bk_catalog_read';}
function wp_json_encode($value) {return json_encode($value,JSON_THROW_ON_ERROR);}
function is_wp_error($value) {return $value instanceof WP_Error;}
function wp_remote_retrieve_response_code($value) {return $value['response']['code'];}
function wp_remote_retrieve_body($value) {return $value['body'];}
class StubDb {
    public $prefix='wp_';
    public $options='wp_options';
    public $receipts=[];
    public $suppressed=false;
    public $lookups=0;
    function prepare($sql,...$args) {ck(count($args)===1 && $args[0]===7); return 'prepared';}
    function get_results($sql,$type) {
        ck($sql==='prepared' && $type===OBJECT);
        $this->lookups++;
        if ($GLOBALS['scenario']==='missing') return [];
        return [(object)['id'=>7,'store'=>'Fixture','token'=>'ci-secret-canary']];
    }
    function suppress_errors($value) { $old=$this->suppressed; $this->suppressed=$value; return $old; }
    function insert($table,$data,$formats) {
        ck($table===$this->options && $data['autoload']==='no' && $this->suppressed);
        ck($formats===['%s','%s','%s'] && !str_contains(json_encode($data),'canary'));
        if ($GLOBALS['scenario']==='db-failure' || isset($this->receipts[$data['option_name']])) return false;
        $this->receipts[$data['option_name']]=$data;
        return 1;
    }
}
$wpdb=new StubDb();
$calls=0;
function wp_remote_post($url,$args) {
    global $calls,$wpdb,$scenario,$offset;
    $calls++;
    ck(count($wpdb->receipts)===1 && !$wpdb->suppressed);
    ck($url==='https://api.dropi.co/integrations/products/index');
    ck($args['sslverify']===true && $args['redirection']===0 && $args['reject_unsafe_urls']===true);
    ck($args['timeout']===15 && $args['limit_response_size']===524288);
    ck($args['headers']['dropi-integration-key']==='ci-secret-canary');
    $data=json_decode($args['body'],true,32,JSON_THROW_ON_ERROR);
    ck($data['startData']===$offset && $data['pageSize']===10 && $data['keywords']==='fixture');
    if ($scenario==='transport') return new WP_Error();
    $code=in_array($scenario,['403','429','302'],true)?(int)$scenario:200;
    $item=['id'=>$offset+1,'name'=>'Fixture','sku'=>'0001','type'=>'SIMPLE','stock'=>5,'sale_price'=>'7000.25'];
    $body=wp_json_encode(['isSuccess'=>true,'objects'=>[$item]]);
    if ($scenario==='malformed') $body='{';
    if ($scenario==='oversized') $body=str_repeat('x',524289);
    if ($scenario==='cardinality') $body=wp_json_encode(['isSuccess'=>true,'objects'=>array_fill(0,11,$item)]);
    return ['response'=>['code'=>$code],'body'=>$body];
}
require $argv[1].'/clasess/views/Products.php';
$model=(new ReflectionClass(JPIODFW_ProductsModel::class))->newInstanceWithoutConstructor();
$prop=new ReflectionProperty(JPIODFW_ProductsModel::class,'constants');
$prop->setValue($model,(object)['API_URL'=>$scenario==='host'?'https://example.invalid/':'https://api.dropi.co/integrations/']);
$model->TokenModel=new JPIODFW_TokenModel();
$read=fn()=>$model->getProducts(10,$scenario==='scope'?20:$offset,'fixture','id','asc',null,null,null,null,null,'7',[]);
$result=$read();
$success=in_array($scenario,['ok','page2'],true);
$blocked=in_array($scenario,['production','get','denied','nonce','expired','scope','host','missing','db-failure'],true);
if ($success) {
    ck(is_array($result));
    $snapshot=bakata_catalog_project($result['objects'],'7',intdiv($offset,10)+1,10,'ci-approval','fixture');
    ck(count($snapshot['rows'])===1 && $snapshot['rows'][0]['base_price']==='7000.25');
    ck(!str_contains(json_encode($snapshot),'canary') && !str_contains(json_encode($result),'ci-secret-canary'));
} else {ck($result===null);}
ck($calls===($blocked?0:1));
ck($read()===null && $calls===($blocked?0:1));
echo "Operational fixture ".$scenario." passed\n";
