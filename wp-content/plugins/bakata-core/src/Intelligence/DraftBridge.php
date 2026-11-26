<?php
declare(strict_types=1);

namespace Bakata\Core\Intelligence;

use Bakata\Core\Catalog\DraftPlanner;
use Bakata\Core\Catalog\WooDraftImporter;
use Bakata\Core\Pricing\PricingPolicy;
use Bakata\Core\Pricing\UnitCosts;
use Bakata\Core\Suppliers\SupplierProduct;
use DateTimeImmutable;
use InvalidArgumentException;
use RuntimeException;

/**
 * INT-09 sandbox bridge. No hook, endpoint, admin action or production caller.
 * The synthetic snapshot is research evidence, never supplier cost or authorization.
 */
final class DraftBridge
{
    private static function guard(): void
    {
        if (!defined('WP_CLI') || !WP_CLI || getenv('BAKATA_CI_FIXTURES') !== '1'
            || !in_array(wp_parse_url(home_url(), PHP_URL_HOST), ['localhost', '127.0.0.1'], true)
            || !current_user_can('manage_options') || !current_user_can('edit_products')) {
            throw new RuntimeException('Intelligence import restricted to authorized isolated CI.');
        }
    }

    private static function reference(string $value): void
    {
        if (!preg_match('/\A[A-Za-z0-9._-]{1,128}\z/D', $value)) {
            throw new InvalidArgumentException('Invalid reviewed evidence reference.');
        }
    }

    /**
     * All supplier details, category and costs come from a separate reviewed
     * fixture mapping. The discovered retail price is not a supplier quote.
     * Return an exact approval digest; no writes in preview.
     */
    public function preview(
        string $snapshotJson, string $candidateSource, string $candidateId,
        SupplierProduct $supplier, UnitCosts $costs, PricingPolicy $policy,
        int $categoryId, string $mappingRef, int $maxAgeSeconds
    ): array {
        self::guard();
        self::reference($mappingRef);
        if (!str_starts_with($supplier->supplierId, 'ci-intelligence-')
            || $supplier->availableQuantity !== 0) {
            throw new InvalidArgumentException('Use synthetic supplier mapping with zero stock.');
        }
        $snapshot = PreviewSnapshot::decode($snapshotJson);
        $matches = array_values(array_filter($snapshot['rows'], static fn(array $row): bool =>
            $row['source'] === $candidateSource && $row['external_id'] === $candidateId));
        if (count($matches) !== 1 || $matches[0]['status'] !== 'review-ready'
            || $matches[0]['coverage_pct'] !== 100 || $matches[0]['blockers'] !== []
            || $matches[0]['score_bp'] === null) {
            throw new InvalidArgumentException('Candidate is not ready for review.');
        }
        $candidate = $matches[0];
        if ($candidate['currency'] !== $supplier->currency || $supplier->currencyMinorUnit !== 2
            || $supplier->currency !== get_woocommerce_currency() || wc_get_price_decimals() !== 2) {
            throw new InvalidArgumentException('Currency or minor unit mismatch.');
        }
        if ($categoryId < 1 || !($term = get_term($categoryId, 'product_cat')) instanceof \WP_Term) {
            throw new InvalidArgumentException('Select an existing WooCommerce product category.');
        }
        $now = new DateTimeImmutable('now');
        $plan = (new DraftPlanner())->plan($supplier, $costs, $policy, $now, $maxAgeSeconds);
        if (!$plan->quote->meetsTarget || $plan->quote->contributionMinor <= 0) {
            throw new InvalidArgumentException('Positive contribution required.');
        }
        $digest = hash('sha256', json_encode([
            'v' => 1, 'snapshot' => hash('sha256', $snapshotJson),
            'candidate' => [$candidateSource, $candidateId, $candidate['observed_at']],
            'supplier' => $supplier->identity(), 'supplier_at' => $supplier->observedAt->format(DATE_ATOM),
            'plan' => $plan->fingerprint, 'category' => $categoryId, 'mapping' => $mappingRef,
            'reviewer' => get_current_user_id(), 'max_age' => $maxAgeSeconds,
        ], JSON_THROW_ON_ERROR));
        return ['approval_digest'=>$digest, 'candidate_key'=>[$candidateSource,$candidateId,$candidate['observed_at']],
            'snapshot_sha256'=>hash('sha256',$snapshotJson), 'sku'=>$supplier->proposedSku(),
            'category_id'=>$categoryId, 'candidate_price_minor'=>$plan->quote->priceMinor,
            'contribution_minor'=>$plan->quote->contributionMinor, 'currency'=>$supplier->currency,
            'mapping_ref'=>$mappingRef, 'reviewer'=>get_current_user_id()];
    }

    /**
     * Explicit confirmation of exact preview. Serialized per supplier identity.
     * A pending/failed receipt is never automatically replayed after uncertainty.
     */
    public function create(
        string $snapshotJson, string $candidateSource, string $candidateId,
        SupplierProduct $supplier, UnitCosts $costs, PricingPolicy $policy,
        int $categoryId, string $mappingRef, int $maxAgeSeconds,
        string $approvalDigest, string $approvalRef
    ): int {
        self::guard();
        self::reference($approvalRef);
        $preview = $this->preview($snapshotJson,$candidateSource,$candidateId,$supplier,$costs,$policy,
            $categoryId,$mappingRef,$maxAgeSeconds);
        if (!hash_equals($preview['approval_digest'], $approvalDigest)) {
            throw new InvalidArgumentException('Explicit approval does not match current preview.');
        }
        global $wpdb;
        $receiptKey = 'bk_int_draft_' . $supplier->identity();
        $lock = 'bk_int_' . substr(hash('sha256', DB_NAME . ':' . $wpdb->prefix . ':' . $receiptKey), 0, 56);
        if ((string)$wpdb->get_var($wpdb->prepare('SELECT GET_LOCK(%s, 0)', $lock)) !== '1') {
            throw new RuntimeException('Import lock unavailable.');
        }
        try {
            // A lock protects this bridge, not third-party product writers.
            $receipt = get_option($receiptKey, null);
            if ($receipt !== null) {
                if (!is_array($receipt) || ($receipt['state'] ?? '') !== 'succeeded'
                    || ($receipt['approval_digest'] ?? '') !== $approvalDigest
                    || ($receipt['approval_ref'] ?? '') !== $approvalRef) {
                    throw new RuntimeException('Existing import receipt requires manual review.');
                }
                $id = (int)($receipt['product_id'] ?? 0);
                $product = $id > 0 ? wc_get_product($id) : false;
                if (!$product || !$this->matches($product,$preview,$supplier)
                    || !current_user_can('edit_post',$id)) {
                    throw new RuntimeException('Previously imported draft changed; manual review required.');
                }
                // Reuse existing importer to verify its original commercial invariants, without creating.
                if ((int)wc_get_product_id_by_sku($preview['sku']) !== $id) {
                    throw new RuntimeException('Previously imported SKU changed.');
                }
                return (new WooDraftImporter())->create($supplier,$costs,$policy,$maxAgeSeconds);
            }
            if ((int)wc_get_product_id_by_sku($preview['sku']) !== 0) {
                throw new RuntimeException('Existing SKU requires manual review.');
            }
            $receipt = $preview + ['state'=>'pending','approval_ref'=>$approvalRef,
                'created_at'=>gmdate(DATE_ATOM)];
            if (!add_option($receiptKey,$receipt,'',false)) {
                throw new RuntimeException('Cannot reserve import receipt.');
            }
            try {
                $this->assertLock($lock);
                $id = (new WooDraftImporter())->create($supplier,$costs,$policy,$maxAgeSeconds);
                $this->assertLock($lock);
                $product = wc_get_product($id);
                if (!$product || !$product->is_type('simple') || $product->get_status('edit') !== 'draft'
                    || !current_user_can('edit_post',$id)) {
                    throw new RuntimeException('Draft no longer eligible for mapping.');
                }
                $product->set_category_ids([$categoryId]);
                $product->update_meta_data('_bakata_intelligence_approval_digest',$approvalDigest);
                $product->update_meta_data('_bakata_intelligence_snapshot_sha256',$preview['snapshot_sha256']);
                $product->update_meta_data('_bakata_intelligence_mapping_ref',$mappingRef);
                $product->save();
                $this->assertLock($lock);
                $stored = wc_get_product($id);
                if (!$stored || !$this->matches($stored,$preview,$supplier)) {
                    throw new RuntimeException('Draft invariants or mapping changed.');
                }
                $receipt['state'] = 'succeeded';
                $receipt['product_id'] = $id;
                $receipt['completed_at'] = gmdate(DATE_ATOM);
                if (!update_option($receiptKey,$receipt,false)) {
                    throw new RuntimeException('Cannot confirm import receipt.');
                }
                return $id;
            } catch (\Throwable $e) {
                // Never retry an uncertain write or delete a product affected by third-party hooks.
                // Keep the pending receipt if the DB connection/lock is no longer trustworthy.
                $this->assertLock($lock);
                $receipt['state'] = 'failed-review';
                $receipt['failed_at'] = gmdate(DATE_ATOM);
                update_option($receiptKey,$receipt,false);
                throw $e;
            }
        } finally {
            $wpdb->get_var($wpdb->prepare('SELECT RELEASE_LOCK(%s)', $lock));
        }
    }

    private function assertLock(string $lock): void
    {
        global $wpdb;
        if ((string)$wpdb->get_var($wpdb->prepare('SELECT IS_USED_LOCK(%s) = CONNECTION_ID()', $lock)) !== '1') {
            throw new RuntimeException('Import lock lost; manual review required.');
        }
    }

    private function matches(\WC_Product $product,array $preview,SupplierProduct $supplier): bool
    {
        return $product->is_type('simple') && $product->get_status('edit') === 'draft'
            && $product->get_catalog_visibility('edit') === 'hidden'
            && $product->get_sku('edit') === $preview['sku']
            && $product->get_name('edit') === $supplier->title
            && $product->get_price('edit') === '' && $product->get_regular_price('edit') === ''
            && $product->get_sale_price('edit') === '' && $product->get_manage_stock('edit')
            && $product->get_stock_quantity('edit') === 0 && $product->get_stock_status('edit') === 'outofstock'
            && $product->get_backorders('edit') === 'no'
            && $product->get_category_ids('edit') === [$preview['category_id']]
            && $product->get_meta('_bakata_source_identity',true,'edit') === $supplier->identity()
            && $product->get_meta('_bakata_candidate_price_minor',true,'edit') === (string)$preview['candidate_price_minor']
            && $product->get_meta('_bakata_intelligence_approval_digest',true,'edit') === $preview['approval_digest']
            && $product->get_meta('_bakata_intelligence_snapshot_sha256',true,'edit') === $preview['snapshot_sha256']
            && $product->get_meta('_bakata_intelligence_mapping_ref',true,'edit') === $preview['mapping_ref'];
    }
}
