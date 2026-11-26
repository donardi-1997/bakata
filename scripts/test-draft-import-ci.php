<?php
declare(strict_types=1);

use Bakata\Core\Catalog\DraftPlanner;
use Bakata\Core\Catalog\WooDraftImporter;
use Bakata\Core\Pricing\PricingPolicy;
use Bakata\Core\Pricing\UnitCosts;
use Bakata\Core\Suppliers\SupplierProduct;

if (!defined('WP_CLI') || !WP_CLI || getenv('BAKATA_CI_FIXTURES') !== '1'
    || !in_array(wp_parse_url(home_url(), PHP_URL_HOST), ['localhost', '127.0.0.1'], true)
    || !class_exists(WooDraftImporter::class)) {
    throw new RuntimeException('Refusing test outside isolated CI.');
}
$checks = 0;
function draft_check(bool $condition, string $label): void {
    global $checks;
    if (!$condition) { throw new RuntimeException('Failed: ' . $label); }
    $checks++;
}
function draft_rejects(callable $fn, string $class, string $message): void {
    try { $fn(); } catch (Throwable $error) {
        draft_check($error instanceof $class && str_contains($error->getMessage(), $message), $message);
        return;
    }
    throw new RuntimeException('Expected rejection: ' . $message);
}
$now = new DateTimeImmutable('now');
$minor = wc_get_price_decimals();
$scale = 10 ** $minor;
draft_check(get_woocommerce_currency() === 'COP', 'CI currency');
$cost = new UnitCosts('COP', $minor, 25000*$scale, 12000*$scale, 1000*$scale, 2000*$scale, 0);
$policy = new PricingPolicy('COP', $minor, 400, 2500, 1000*$scale, 200000*$scale);
$source = static fn(string $id='SKU-A', ?DateTimeImmutable $at=null, int $stock=5, string $title='CI Supplier Draft')
    => new SupplierProduct('ci-draft-supplier',$id,$title,25000*$scale,'COP',$minor,$stock,$at ?? $now);
$planner = new DraftPlanner();
$importer = new WooDraftImporter();
$p = $planner->plan($source(),$cost,$policy,$now,3600);
draft_check($p->quote->priceMinor===57000*$scale, 'candidate price');
draft_check($p->fingerprint===$planner->plan($source(at:$now->modify('-1 minute')),$cost,$policy,$now,3600)->fingerprint, 'same data new observation');
draft_check($p->fingerprint!==$planner->plan($source(stock:6),$cost,$policy,$now,3600)->fingerprint, 'stock change fingerprint');
draft_rejects(fn()=>$planner->plan($source(at:$now->modify('-2 hours')),$cost,$policy,$now,3600),InvalidArgumentException::class,'stale');
draft_rejects(fn()=>$planner->plan($source(at:$now->modify('+1 minute')),$cost,$policy,$now,3600),InvalidArgumentException::class,'future');
draft_rejects(fn()=>$planner->plan($source(),new UnitCosts('COP',$minor,1,0,0,0,0),$policy,$now,3600),InvalidArgumentException::class,'do not match');
$previous = get_current_user_id();
$admins = get_users(['role'=>'administrator','number'=>1,'fields'=>'ID']);
if (!$admins) { throw new RuntimeException('CI administrator missing.'); }
try {
    wp_set_current_user(0);
    draft_rejects(fn()=>$importer->create($source(),$cost,$policy,3600),RuntimeException::class,'capability');
    wp_set_current_user((int)$admins[0]);
    draft_check(wc_get_product_id_by_sku($source()->proposedSku())===0, 'initially no SKU');
    $id = $importer->create($source(),$cost,$policy,3600);
    $stored = wc_get_product($id);
    draft_check($stored instanceof WC_Product_Simple, 'native simple product');
    draft_check($stored->get_status()==='draft' && $stored->get_catalog_visibility()==='hidden', 'hidden draft');
    draft_check($stored->get_price()==='' && $stored->get_regular_price()==='' && $stored->get_sale_price()==='', 'no sale price');
    draft_check($stored->get_manage_stock() && $stored->get_stock_quantity()===0 && !$stored->is_in_stock() && !$stored->backorders_allowed(), 'zero sellable stock');
    draft_check(!$stored->is_purchasable(), 'non-purchasable');
    draft_check($stored->get_meta('_bakata_source_stock')==='5', 'supplier stock separate');
    draft_check($stored->get_meta('_bakata_candidate_price_minor')===(string)(57000*$scale), 'candidate price private metadata');
    draft_check($importer->create($source(at:$now->modify('-1 minute')),$cost,$policy,3600)===$id, 'sequential replay returns same ID');
    draft_check(count(wc_get_products(['sku'=>$source()->proposedSku(),'status'=>'draft','limit'=>-1,'return'=>'ids']))===1, 'one draft');
    draft_check(count(wc_get_products(['sku'=>$source()->proposedSku(),'status'=>'publish','limit'=>-1,'return'=>'ids']))===0, 'not published');
    draft_rejects(fn()=>$importer->create($source(stock:7),$cost,$policy,3600),RuntimeException::class,'conflicts');
    draft_rejects(fn()=>$importer->create($source(at:$now->modify('-2 hours')),$cost,$policy,3600),InvalidArgumentException::class,'stale');
    $manual = new WC_Product_Simple();
    $manual->set_name('CI Unmanaged Product');
    $manual->set_sku($source(id:'SKU-B')->proposedSku());
    $manual->set_status('draft');
    $manualId = $manual->save();
    draft_rejects(fn()=>$importer->create($source(id:'SKU-B'),$cost,$policy,3600),RuntimeException::class,'conflicts');
    draft_check(wc_get_product($manualId)->get_name()==='CI Unmanaged Product','unmanaged product unchanged');
    $stored = wc_get_product($id);
    $stored->set_name('CI Editorial Change');
    $stored->save();
    draft_rejects(fn()=>$importer->create($source(),$cost,$policy,3600),RuntimeException::class,'conflicts');
    draft_check(wc_get_product($id)->get_name()==='CI Editorial Change','edited draft unchanged');
    draft_rejects(fn()=>$importer->create($source(id:'SKU-C',title:'<b>HTML</b>'),$cost,$policy,3600),RuntimeException::class,'normalization');
} finally {
    wp_set_current_user($previous);
}
echo "Draft import: {$checks} checks passed.\n";
