<?php
declare(strict_types=1);

use Bakata\Core\Intelligence\DropifyPreview;
use Bakata\Core\Intelligence\ReviewedDropifyQuote;
use Bakata\Core\Pricing\PricingPolicy;
use Bakata\Core\Pricing\UnitCosts;

if (!defined('WP_CLI') || !WP_CLI || getenv('BAKATA_CI_FIXTURES') !== '1'
    || !in_array(wp_parse_url(home_url(), PHP_URL_HOST), ['localhost','127.0.0.1'], true)) {
    throw new RuntimeException('Refusing test outside isolated CI.');
}
function dropify_int_check(bool $ok, string $message): void {
    if (!$ok) { throw new RuntimeException($message); }
}
function dropify_int_reject(callable $call, string $message): void {
    try { $call(); } catch (Throwable $e) {
        dropify_int_check(str_contains($e->getMessage(),$message),'Unexpected rejection: '.$e->getMessage());
        return;
    }
    throw new RuntimeException('Expected rejection: '.$message);
}
$json = getenv('BAKATA_CI_INTELLIGENCE_SNAPSHOT');
dropify_int_check(is_string($json) && $json !== '', 'Fixture missing');
$admins = get_users(['role'=>'administrator','number'=>1,'fields'=>'ID']);
dropify_int_check(count($admins)===1,'Administrator missing');
$previous = get_current_user_id();
wp_set_current_user((int)$admins[0]);
$now = new DateTimeImmutable('now');
$policy = new PricingPolicy('COP',2,400,2500,100000,20000000);
$costs = new UnitCosts('COP',2,2500000,1200000,100000,200000,0);
$product = new WC_Product_Simple();
$product->set_name('CI connector mapping');
$product->set_status('draft');
$product->set_catalog_visibility('hidden');
$product->set_sku('ci-dropify-int15');
$product->set_regular_price('99999');
$product->set_manage_stock(true);
$product->set_stock_quantity(42);
$product->add_meta_data('_dropi_product_id','12345',true);
$product->add_meta_data('_dropi_product',['opaque'=>'synthetic-opaque-canary'],true);
$product->add_meta_data('_dropi_token','synthetic-secret-canary',true);
$id=$product->save();
$preview=new DropifyPreview();
$review=static fn(?int $cost=2500000,?int $stock=5,string $external='12345',string $sku='ci-dropify-int15',?DateTimeImmutable $at=null)
    =>new ReviewedDropifyQuote($id,$sku,'ci-store',$external,$cost,$stock,$at??$now,'ci-quote','ci-map');
$inspect=static fn(ReviewedDropifyQuote $r,?UnitCosts $c=null,string $candidate='demo-001')
    =>$preview->inspect($json,'fixture',$candidate,$r,$c,$policy,$now,3600);
$before=wc_get_product($id);
$beforeData=$before->get_data();
$beforeMeta=array_map(static fn($m)=>$m->get_data(),$before->get_meta_data());
try {
    wp_set_current_user(0);
    dropify_int_reject(fn()=>$inspect($review(),$costs),'restricted');
    wp_set_current_user((int)$admins[0]);
    $result=$inspect($review(),$costs);
    dropify_int_check($result['status']==='review-ready' && $result['score_bp']===7777,'Candidate ready');
    dropify_int_check($result['supplier_cost_minor']===2500000 && $result['supplier_stock']===5,'Reviewed supplier values, not Woo stock/price');
    dropify_int_check($result['candidate_price_minor']===5700000 && $result['contribution_minor']===1472000,'Independent repricing');
    $encoded=json_encode($result,JSON_THROW_ON_ERROR);
    dropify_int_check(!str_contains($encoded,'synthetic-secret-canary') && !str_contains($encoded,'synthetic-opaque-canary'),'No opaque metadata in output');
    $missing=$inspect($review(cost:null,stock:null));
    dropify_int_check($missing['status']==='blocked' && $missing['supplier_cost_minor']===null && $missing['supplier_stock']===null && $missing['candidate_price_minor']===null,'Unknown values remain unknown');
    $empty=$inspect($review(stock:0),$costs);
    dropify_int_check(in_array('supplier-out-of-stock',$empty['blockers'],true),'Zero stock blocks');
    dropify_int_reject(fn()=>$inspect($review(external:'12346'),$costs),'identity differs');
    dropify_int_reject(fn()=>$inspect($review(sku:'another-sku'),$costs),'mapping changed');
    dropify_int_reject(fn()=>$inspect($review(at:$now->modify('-2 hours')),$costs),'stale');
    dropify_int_reject(fn()=>$inspect($review(at:$now->modify('+1 hour')),$costs),'stale');
    dropify_int_reject(fn()=>$inspect($review(cost:1),$costs),'do not match');
    dropify_int_reject(fn()=>$inspect($review(),$costs,'demo-002'),'Complete reviewed');
    $after=wc_get_product($id);
    dropify_int_check($beforeData==$after->get_data() && $beforeMeta===array_map(static fn($m)=>$m->get_data(),$after->get_meta_data()),'Preview leaves WooCommerce unchanged');
    $after->add_meta_data('_dropi_product_id','12345',false);
    $after->save();
    dropify_int_reject(fn()=>$inspect($review(),$costs),'ambiguous');
    $after->delete_meta_data('_dropi_product_id');
    $after->add_meta_data('_dropi_product_id','12345',true);
    $after->add_meta_data('_dropi_variation','synthetic-variant',true);
    $after->save();
    dropify_int_reject(fn()=>$inspect($review(),$costs),'Variant mapping');
} finally {
    wp_set_current_user($previous);
}
echo "Intelligence Dropify reconciliation checks passed.\n";
