<?php
declare(strict_types=1);
namespace Bakata\Core\Intelligence;

use Bakata\Core\Catalog\DraftPlanner;
use Bakata\Core\Catalog\WooDraftImporter;
use Bakata\Core\Pricing\UnitCosts;
use Bakata\Core\Pricing\PricingPolicy;
use Bakata\Core\Suppliers\SupplierProduct;
use DateTimeImmutable;
use RuntimeException;

/** CI-only integration: an unsigned offline plan never authorizes a live import. */
final class ApprovedDraftSandbox
{
    private static function guard(): void
    {
        if (!defined('WP_CLI') || !WP_CLI || getenv('BAKATA_CI_FIXTURES')!=='1'
            || !in_array(wp_parse_url(home_url(),PHP_URL_HOST),['localhost','127.0.0.1'],true)
            || !current_user_can('manage_options') || !current_user_can('edit_products')) {
            throw new RuntimeException('Approved draft restricted to isolated CI.');
        }
    }

    private static function canonical(array $data): string
    {
        // Python encode sorts object keys; recursively canonicalize associative arrays.
        foreach ($data as &$value) { if (is_array($value)) { $value=json_decode(self::canonical($value),true,16,JSON_THROW_ON_ERROR); } }
        unset($value);
        if (!array_is_list($data)) { ksort($data,SORT_STRING); }
        return json_encode($data,JSON_THROW_ON_ERROR|JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_LINE_TERMINATORS);
    }

    private static function require(bool $ok): void
    {
        if (!$ok) { throw new RuntimeException('Invalid or changed approved draft plan.'); }
    }

    private static function shape(array $data,array $keys): void
    {
        self::require(count($data)===count($keys) && array_diff($keys,array_keys($data))===[]);
    }

    private static function ref(mixed $v): bool
    {
        return is_string($v) && preg_match('/\A[A-Za-z0-9._-]{1,128}\z/D',$v)===1;
    }

    private static function parse(string $raw,string $expected): array
    {
        self::guard();
        self::require(strlen($raw)>0 && strlen($raw)<=32768);
        $raw=str_ends_with($raw,"\n")?substr($raw,0,-1):$raw;
        $d=json_decode($raw,true,12,JSON_THROW_ON_ERROR);
        self::shape($d,['plan','plan_sha256']);
        $p=$d['plan'];
        self::require(self::canonical($d)===$raw && is_string($d['plan_sha256'])
            && preg_match('/\A[0-9a-f]{64}\z/D',$expected)===1
            && hash_equals($expected,$d['plan_sha256'])
            && hash_equals($expected,hash('sha256',self::canonical($p))));
        self::shape($p,['schema','mode','archive_ref','decision_sha256','decision_id','dossier_sha256','evaluation_sha256',
            'mapping_ref','reviewer_id','category_id','supplier_id','store_id','external_id','title','captured_at','valid_until',
            'currency','minor_unit','economics','contribution_minor','policy','status','visibility','sellable_stock','sale_price_active',
            'publication_authorized','woo_mutation']);
        foreach (['decision_sha256','dossier_sha256','evaluation_sha256'] as $k) {
            self::require(is_string($p[$k]) && preg_match('/\A[0-9a-f]{64}\z/D',$p[$k])===1);
        }
        foreach (['decision_id','mapping_ref','archive_ref'] as $k) { self::require(self::ref($p[$k])); }
        self::require($p['schema']==='bakata-approved-draft-plan-v1' && $p['mode']==='offline-preview-only'
            && str_starts_with($p['archive_ref'],'fixture-') && is_string($p['store_id']) && preg_match('/\A[1-9][0-9]{0,9}\z/D',$p['store_id'])===1
            && is_string($p['external_id']) && preg_match('/\A[1-9][0-9]{0,29}\z/D',$p['external_id'])===1
            && $p['supplier_id']==='ci-intelligence-approved-'.substr(hash('sha256',self::canonical([$p['archive_ref'],$p['store_id']])),0,32)
            && $p['reviewer_id']===get_current_user_id() && is_int($p['category_id']) && $p['category_id']>0
            && get_term($p['category_id'],'product_cat') instanceof \WP_Term
            && $p['currency']==='COP' && $p['minor_unit']===2 && get_woocommerce_currency()==='COP' && wc_get_price_decimals()===2
            && $p['status']==='draft' && $p['visibility']==='hidden' && $p['sellable_stock']===0 && $p['sale_price_active']===false
            && $p['publication_authorized']===false && $p['woo_mutation']===false);
        foreach (['captured_at','valid_until'] as $k) {
            self::require(is_string($p[$k]) && preg_match('/\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{6})?\+00:00\z/D',$p[$k])===1);
        }
        $captured=new DateTimeImmutable($p['captured_at']);
        $until=new DateTimeImmutable($p['valid_until']);
        self::require($captured->getTimestamp()<=time() && $until->getTimestamp()>time()
            && $until<=$captured->modify('+24 hours'));
        $m=$p['economics']; $policy=$p['policy'];
        self::shape($m,['sale_price_minor','supplier_cost_minor','shipping_minor','fixed_fee_minor','return_reserve_minor','other_cost_minor','variable_deduction_bps']);
        self::shape($policy,['target_bps','step_minor','ceiling_minor']);
        foreach ($m as $v) { self::require(is_int($v) && $v>=0 && $v<=1000000000000); }
        foreach ($policy as $v) { self::require(is_int($v) && $v>0); }
        self::require(is_string($p['title']) && strlen($p['title'])<=300 && sanitize_text_field($p['title'])===$p['title'] && trim($p['title'])!=='');
        $source=new SupplierProduct($p['supplier_id'],$p['external_id'],$p['title'],$m['supplier_cost_minor'],'COP',2,0,$captured);
        $costs=new UnitCosts('COP',2,$m['supplier_cost_minor'],$m['shipping_minor'],$m['fixed_fee_minor'],$m['return_reserve_minor'],$m['other_cost_minor']);
        $rules=new PricingPolicy('COP',2,$m['variable_deduction_bps'],$policy['target_bps'],$policy['step_minor'],$policy['ceiling_minor']);
        $plan=(new DraftPlanner())->plan($source,$costs,$rules,new DateTimeImmutable('now'),86400);
        self::require($plan->quote->priceMinor===$m['sale_price_minor'] && $plan->quote->contributionMinor===$p['contribution_minor']
            && $plan->quote->contributionMinor>0 && $plan->quote->meetsTarget);
        return [$p,$source,$costs,$rules,$plan->fingerprint];
    }

    public function create(string $raw,string $expected): int
    {
        [$p,$source,$costs,$rules,$fingerprint]=self::parse($raw,$expected);
        global $wpdb;
        $receipt='bk_approved_draft_'.$source->identity();
        $lock='bk_ap_'.substr(hash('sha256',DB_NAME.':'.$wpdb->prefix.':'.$receipt),0,56);
        if ((string)$wpdb->get_var($wpdb->prepare('SELECT GET_LOCK(%s, 0)',$lock))!=='1') { throw new RuntimeException('Draft lock unavailable.'); }
        try {
            // Revalidate expiry and actor after acquiring the import lock.
            self::parse($raw,$expected);
            if (get_option($receipt,null)!==null) { throw new RuntimeException('Existing receipt; manual reconciliation required.'); }
            if (wc_get_product_id_by_sku($source->proposedSku())) { throw new RuntimeException('Existing SKU; manual review required.'); }
            $pending=['state'=>'pending','plan_sha256'=>$expected,'decision_sha256'=>$p['decision_sha256'],'reviewer_id'=>$p['reviewer_id']];
            if (!add_option($receipt,$pending,'',false)) { throw new RuntimeException('Cannot reserve draft receipt.'); }
            self::assertLock($lock);
            $id=(new WooDraftImporter())->create($source,$costs,$rules,86400);
            self::assertLock($lock);
            $product=wc_get_product($id);
            self::require($product instanceof \WC_Product_Simple && current_user_can('edit_post',$id) && self::inert($product,$source,$fingerprint));
            $product->set_category_ids([$p['category_id']]);
            $product->update_meta_data('_bakata_approved_plan_sha256',$expected);
            $product->update_meta_data('_bakata_commercial_decision_sha256',$p['decision_sha256']);
            $product->save();
            self::assertLock($lock);
            $stored=wc_get_product($id);
            self::require($stored instanceof \WC_Product_Simple && self::inert($stored,$source,$fingerprint)
                && $stored->get_category_ids('edit')===[$p['category_id']]
                && $stored->get_meta('_bakata_approved_plan_sha256',true,'edit')===$expected
                && $stored->get_meta('_bakata_commercial_decision_sha256',true,'edit')===$p['decision_sha256']);
            $pending['state']='succeeded'; $pending['product_id']=$id;
            if (!update_option($receipt,$pending,false)) { throw new RuntimeException('Cannot confirm draft receipt.'); }
            return $id;
        } finally {
            // Uncertain writes retain the pending receipt. Never delete or retry blindly.
            $wpdb->get_var($wpdb->prepare('SELECT RELEASE_LOCK(%s)',$lock));
        }
    }

    private static function assertLock(string $lock): void
    {
        global $wpdb;
        if ((string)$wpdb->get_var($wpdb->prepare('SELECT IS_USED_LOCK(%s) = CONNECTION_ID()',$lock))!=='1') {
            throw new RuntimeException('Draft lock lost; manual reconciliation required.');
        }
    }

    private static function inert(\WC_Product $p,SupplierProduct $source,string $fingerprint): bool
    {
        return $p->get_status('edit')==='draft' && $p->get_catalog_visibility('edit')==='hidden'
            && $p->get_name('edit')===$source->title && $p->get_sku('edit')===$source->proposedSku()
            && $p->get_price('edit')==='' && $p->get_regular_price('edit')==='' && $p->get_sale_price('edit')===''
            && $p->get_manage_stock('edit') && $p->get_stock_quantity('edit')===0
            && $p->get_stock_status('edit')==='outofstock' && $p->get_backorders('edit')==='no'
            && $p->get_meta('_bakata_source_identity',true,'edit')===$source->identity()
            && $p->get_meta('_bakata_import_fingerprint',true,'edit')===$fingerprint;
    }
}
