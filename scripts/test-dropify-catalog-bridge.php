<?php
declare(strict_types=1);
define('ABSPATH', __DIR__);
class WP_List_Table {}
$fullBuild = isset($argv[1]);
require $fullBuild ? $argv[1] . '/clasess/views/Products.php' : __DIR__ . '/../tools/dropify-quarantine/catalog-bridge.php';
function ck($ok) { if (!$ok) throw new RuntimeException('Catalog assertion failed'); }
function reject($fn) { try { $fn(); } catch (InvalidArgumentException $e) { return; } throw new RuntimeException('Expected rejection'); }
ck(bakata_catalog_offset(1,10)===0 && bakata_catalog_offset(2,10)===10 && bakata_catalog_offset(3,10)===20);
reject(fn()=>bakata_catalog_offset(101,10));
reject(fn()=>bakata_catalog_offset(1,21));
$item=(object)['id'=>96,'sku'=>'025216','name'=>'Prueba','type'=>'SIMPLE','sale_price'=>'7000.25',
    'suggested_price'=>17000,'stock'=>412,'store'=>(object)['id'=>7,'token'=>'secret-canary'],
    'user'=>(object)['name'=>'Bodega','email'=>'private-canary'],'categories'=>[(object)['name'=>'Cocina']],
    'description'=>'opaque-canary'];
$data=bakata_catalog_project([$item],'7',2,10,'fixture-approval','');
ck($data['offset']===10 && $data['possible_next']===false);
ck($data['rows'][0]['sku']==='025216' && $data['rows'][0]['base_price']==='7000.25'
    && $data['rows'][0]['suggested_price']==='17000' && $data['rows'][0]['simple_stock']===412);
ck(!str_contains(json_encode($data),'canary'));
$variant=clone $item; $variant->type='VARIABLE'; $variant->id=97;
$variant->sale_price=1.25;
ck(bakata_catalog_project([$variant],'7',1,10,'fixture-approval','')['rows'][0]['simple_stock']===null);
ck(bakata_catalog_project([$variant],'7',1,10,'fixture-approval','')['rows'][0]['base_price']===null);
$multi=clone $item; $multi->warehouse_product=[];
ck(bakata_catalog_project([$multi],'7',1,10,'fixture-approval','')['rows'][0]['simple_stock']===null);
reject(fn()=>bakata_catalog_project([$item,$item],'7',1,10,'fixture-approval',''));
reject(fn()=>bakata_catalog_project([$item],'8',1,10,'fixture-approval',''));
ck(bakata_catalog_project([],'7',1,10,'fixture-approval','')['rows']===[]);
if ($fullBuild) {
    $reflection=new ReflectionClass(JPIODFW_ProductsModel::class);
    $model=$reflection->newInstanceWithoutConstructor();
    ck($model->getProducts(10,0,'','id','asc',null,null,null,null,null,'7',[])===null);
    ck($model->import_product(96)['success']===false);
}
if (getenv('BAKATA_BRIDGE_FIXTURE') === '1') {
    file_put_contents('/tmp/bakata-dropify-bridge-fixture.json',json_encode($data,JSON_THROW_ON_ERROR));
}
echo "Catalog bridge projection and disabled-by-default checks passed.\n";
