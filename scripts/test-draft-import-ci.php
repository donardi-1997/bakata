<?php
declare(strict_types=1);

use Bakata\Core\Catalog\DraftPlanner;
use Bakata\Core\Catalog\WooDraftImporter;
use Bakata\Core\Inventory\InventoryPolicy;
use Bakata\Core\Inventory\WooInventoryPreview;
use Bakata\Core\Pricing\PricingPolicy;
use Bakata\Core\Pricing\UnitCosts;
use Bakata\Core\Suppliers\SupplierProduct;

if (!defined('WP_CLI') || !WP_CLI || getenv('BAKATA_CI_FIXTURES') !== '1'
    || !in_array(wp_parse_url(home_url(), PHP_URL_HOST), ['localhost', '127.0.0.1'], true)
    || !class_exists(WooDraftImporter::class)) {
    throw new RuntimeException('Refusing test outside isolated CI.');
}
$GLOBALS['bakata_draft_ci_checks'] = 0;
function draft_check(bool $condition, string $label): void {
    if (!$condition) { throw new RuntimeException('Failed: ' . $label); }
    $GLOBALS['bakata_draft_ci_checks']++;
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
    draft_check($stored->get_meta('_bakata_observed_at')===$now->setTimezone(new DateTimeZone('UTC'))->format('Y-m-d\TH:i:s.uP'), 'fractional observation stored');
    draft_check($stored->get_meta('_bakata_candidate_price_minor')===(string)(57000*$scale), 'candidate price private metadata');
    $inventory = new WooInventoryPreview();
    $stockPolicy = new InventoryPolicy(3600,1,10);
    $later = $now->modify('+10 seconds');
    $next = $source(at:$later,stock:8);
    $result = $inventory->inspect($id,$next,$stockPolicy,2,$later);
    draft_check($result->status==='changed' && $result->candidateQuantity===5 && $result->previousQuantity===5, 'inventory mapped draft preview');
    draft_check($inventory->inspect($id,null,$stockPolicy,0,$later)->candidateQuantity===null, 'unknown stock blocks candidate');
    draft_check($inventory->inspect($id,$source(at:$now,stock:0),$stockPolicy,0,$later)->status==='conflict', 'same observation time conflict');
    draft_rejects(fn()=>$inventory->inspect($id,$source(id:'wrong'),$stockPolicy,0,$later),RuntimeException::class,'does not match');
    wp_set_current_user(0);
    draft_rejects(fn()=>$inventory->inspect($id,$next,$stockPolicy,0,$later),RuntimeException::class,'capability');
    wp_set_current_user((int)$admins[0]);
    $afterPreview = wc_get_product($id);
    draft_check($afterPreview->get_stock_quantity()===0 && $afterPreview->get_meta('_bakata_source_stock')==='5'
        && $afterPreview->get_meta('_bakata_observed_at')===$now->setTimezone(new DateTimeZone('UTC'))->format('Y-m-d\TH:i:s.uP')
        && $afterPreview->get_price()==='' && $afterPreview->get_status()==='draft', 'preview does not mutate stored stock, observation, price or status');
    $stored->update_meta_data('_bakata_observed_at', $now->format(DATE_ATOM));
    $stored->save();
    draft_rejects(fn()=>$inventory->inspect($id,$next,$stockPolicy,0,$later),RuntimeException::class,'manual review');
    draft_rejects(fn()=>$inventory->inspect($id,null,$stockPolicy,0,$later),RuntimeException::class,'manual review');
    $stored->update_meta_data('_bakata_observed_at', $now->setTimezone(new DateTimeZone('UTC'))->format('Y-m-d\TH:i:s.uP'));
    $stored->save();

    draft_check($importer->create($source(),$cost,$policy,3600)===$id, 'sequential replay returns same ID');
    draft_rejects(fn()=>$importer->create($source(at:$now->modify('-1 minute')),$cost,$policy,3600),RuntimeException::class,'manual review');
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
$checks = $GLOBALS['bakata_draft_ci_checks'];
if ($checks !== 36) { throw new RuntimeException('Unexpected draft/inventory check count: ' . $checks); }
echo "Draft import and mapped inventory: {$checks} checks passed.\n";
