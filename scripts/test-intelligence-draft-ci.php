<?php
declare(strict_types=1);

use Bakata\Core\Intelligence\DraftBridge;
use Bakata\Core\Pricing\UnitCosts;
use Bakata\Core\Pricing\PricingPolicy;
use Bakata\Core\Suppliers\SupplierProduct;

if (!defined('WP_CLI') || !WP_CLI || getenv('BAKATA_CI_FIXTURES') !== '1'
    || !in_array(wp_parse_url(home_url(),PHP_URL_HOST),['localhost','127.0.0.1'],true)) {
    throw new RuntimeException('Refusing test outside isolated CI.');
}
function int_draft_check(bool $ok,string $message): void {
    if (!$ok) { throw new RuntimeException($message); }
}
function int_draft_reject(callable $fn,string $message): void {
    try { $fn(); } catch (Throwable $e) {
        int_draft_check(str_contains($e->getMessage(),$message),'Unexpected rejection: '.$e->getMessage());
        return;
    }
    throw new RuntimeException('Expected rejection: '.$message);
}
$json = getenv('BAKATA_CI_INTELLIGENCE_SNAPSHOT');
int_draft_check(is_string($json) && strlen($json)>0,'Missing fixture snapshot');
$admins = get_users(['role'=>'administrator','number'=>1,'fields'=>'ID']);
int_draft_check(count($admins)===1,'Missing administrator');
$previous = get_current_user_id();
$bridge = new DraftBridge();
$now = new DateTimeImmutable('now');
$costs = new UnitCosts('COP',2,2500000,1200000,100000,200000,0);
$policy = new PricingPolicy('COP',2,400,2500,100000,20000000);
$supplier = static fn(string $id='fixture-one',?DateTimeImmutable $at=null,int $cost=2500000)
    => new SupplierProduct('ci-intelligence-supplier',$id,'CI Intelligence Draft',$cost,'COP',2,0,$at??$now);
try {
    wp_set_current_user((int)$admins[0]);
    $term = wp_insert_term('CI Intelligence Category','product_cat',['slug'=>'ci-intelligence-category']);
    int_draft_check(!is_wp_error($term),'Fixture category');
    $category = (int)$term['term_id'];
    $args = static fn(SupplierProduct $s,string $id='demo-001',?int $cat=null,string $mapping='ci-map-1')
        => [$json,'fixture',$id,$s,$costs,$policy,$cat??$category,$mapping,3600];
    $a = $args($supplier());
    wp_set_current_user(0);
    int_draft_reject(fn()=>$bridge->preview(...$a),'restricted');
    wp_set_current_user((int)$admins[0]);
    int_draft_reject(fn()=>$bridge->preview(...$args($supplier(),'demo-002')),'not ready');
    int_draft_reject(fn()=>$bridge->preview(...$args($supplier(),cat:0)),'category');
    int_draft_reject(fn()=>$bridge->preview(...$args($supplier(at:$now->modify('-2 hours')))),'stale');
    int_draft_reject(fn()=>$bridge->preview(...$args($supplier(cost:1))),'do not match');
    $plan=$bridge->preview(...$a);
    int_draft_check($plan['candidate_price_minor']===5700000,'Pricing recalculated from separate cost');
    int_draft_check($plan['contribution_minor']===1472000,'Contribution');
    int_draft_check(wc_get_product_id_by_sku($plan['sku'])===0,'Preview has no product writes');
    int_draft_reject(fn()=>$bridge->create(...[...$a,str_repeat('0',64),'ci-approval']),'does not match');
    int_draft_reject(fn()=>$bridge->create(...[...$args($supplier(),mapping:'changed'),$plan['approval_digest'],'ci-approval']),'does not match');
    $id=$bridge->create(...[...$a,$plan['approval_digest'],'ci-approval']);
    $product=wc_get_product($id);
    int_draft_check($product instanceof WC_Product_Simple,'Native WooCommerce product');
    int_draft_check($product->get_status()==='draft' && $product->get_catalog_visibility()==='hidden' && !$product->is_purchasable(),'Inert draft');
    int_draft_check($product->get_price()==='' && $product->get_regular_price()==='' && $product->get_sale_price()==='','No sale price');
    int_draft_check($product->get_stock_quantity()===0 && !$product->is_in_stock() && !$product->backorders_allowed(),'No sellable stock');
    int_draft_check($product->get_category_ids()===[$category],'Explicit category mapping');
    int_draft_check($product->get_meta('_bakata_intelligence_snapshot_sha256')===hash('sha256',$json),'Snapshot provenance');
    $receipt=get_option('bk_int_draft_'.$supplier()->identity());
    int_draft_check($receipt['state']==='succeeded' && $receipt['product_id']===$id && $receipt['approval_ref']==='ci-approval','Durable receipt');
    int_draft_check($bridge->create(...[...$a,$plan['approval_digest'],'ci-approval'])===$id,'Replay same ID');
    int_draft_reject(fn()=>$bridge->create(...[...$a,$plan['approval_digest'],'changed-approval']),'receipt');
    $other=$supplier('fixture-two');
    $b=$args($other);
    $p2=$bridge->preview(...$b);
    $manual=new WC_Product_Simple();
    $manual->set_name('CI Existing Merchant Product');
    $manual->set_status('draft');
    $manual->set_sku($p2['sku']);
    $manualId=$manual->save();
    int_draft_reject(fn()=>$bridge->create(...[...$b,$p2['approval_digest'],'ci-approval-two']),'Existing SKU');
    int_draft_check(wc_get_product($manualId)->get_name()==='CI Existing Merchant Product','Existing product untouched');
    $third=$supplier('fixture-three');
    $c=$args($third);
    $p3=$bridge->preview(...$c);
    add_option('bk_int_draft_'.$third->identity(),['state'=>'pending'],'',false);
    int_draft_reject(fn()=>$bridge->create(...[...$c,$p3['approval_digest'],'ci-approval-three']),'receipt');
    int_draft_check(wc_get_product_id_by_sku($p3['sku'])===0,'Uncertain receipt prevents replay');
    $product->set_name('CI Editorial Change');
    $product->save();
    int_draft_reject(fn()=>$bridge->create(...[...$a,$plan['approval_digest'],'ci-approval']),'changed');
    int_draft_check(wc_get_product($id)->get_name()==='CI Editorial Change','Editorial edit preserved');
    int_draft_check(count(wc_get_products(['sku'=>$plan['sku'],'status'=>'publish','limit'=>-1,'return'=>'ids']))===0,'No publication');
} finally {
    wp_set_current_user($previous);
}
echo "Intelligence draft bridge checks passed.\n";
