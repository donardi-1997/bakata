<?php
declare(strict_types=1);
use Bakata\Core\Intelligence\ApprovedDraftSandbox;
function approved_ck(bool $ok): void { if (!$ok) throw new RuntimeException('Approved draft assertion failed.'); }
function approved_reject(callable $fn): void {
    try { $fn(); } catch (Throwable $e) { return; }
    throw new RuntimeException('Unexpected draft creation.');
}
if (!defined('WP_CLI') || !WP_CLI || getenv('BAKATA_CI_FIXTURES')!=='1'
    || !in_array(wp_parse_url(home_url(),PHP_URL_HOST),['localhost','127.0.0.1'],true)) {
    throw new RuntimeException('Isolated fixture required.');
}
require_once WP_PLUGIN_DIR.'/bakata-core/src/Intelligence/ApprovedDraftSandbox.php';
$raw=getenv('BAKATA_CI_APPROVED_DRAFT');
approved_ck(is_string($raw) && strlen($raw)>0);
$d=json_decode($raw,true,12,JSON_THROW_ON_ERROR);
$p=$d['plan']; $digest=$d['plan_sha256'];
$service=new ApprovedDraftSandbox();
$previous=get_current_user_id();
try {
    wp_set_current_user(0);
    approved_reject(fn()=>$service->create($raw,$digest));
    wp_set_current_user($p['reviewer_id']);
    approved_reject(fn()=>$service->create($raw,str_repeat('0',64)));
    $id=$service->create($raw,$digest);
    $product=wc_get_product($id);
    approved_ck($product instanceof WC_Product_Simple && $product->get_status()==='draft'
        && $product->get_catalog_visibility()==='hidden' && !$product->is_purchasable()
        && $product->get_price()==='' && $product->get_stock_quantity()===0 && !$product->is_in_stock()
        && !$product->backorders_allowed() && $product->get_category_ids()===[$p['category_id']]
        && $product->get_meta('_bakata_commercial_decision_sha256')===$p['decision_sha256']);
    approved_reject(fn()=>$service->create($raw,$digest));
    approved_ck((int)wc_get_product_id_by_sku($product->get_sku())===$id);
} finally { wp_set_current_user($previous); }
echo "Ledger-derived approved draft remains inert in isolated WooCommerce.\n";
