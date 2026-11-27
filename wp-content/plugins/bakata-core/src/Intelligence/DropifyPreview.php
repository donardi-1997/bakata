<?php
declare(strict_types=1);

namespace Bakata\Core\Intelligence;

use Bakata\Core\Pricing\PricingPolicy;
use Bakata\Core\Pricing\PricingPreview;
use Bakata\Core\Pricing\UnitCosts;
use Bakata\Core\Suppliers\SupplierProduct;
use DateTimeImmutable;
use InvalidArgumentException;
use RuntimeException;

/** Reviewed observation, not a response from Dropi or a local Woo stock reading. */
final readonly class ReviewedDropifyQuote
{
    public function __construct(
        public int $productId,
        public string $sku,
        public string $storeRef,
        public string $externalId,
        public ?int $costMinor,
        public ?int $availableQuantity,
        public DateTimeImmutable $observedAt,
        public string $evidenceRef,
        public string $mappingRef,
    ) {
        if ($productId < 1 || $sku === '' || strlen($sku) > 100
            || preg_match('/[\x00-\x1f\x7f]/', $sku) !== 0
            || !preg_match('/\A[1-9][0-9]{0,29}\z/D', $externalId)
            || !preg_match('/\A[A-Za-z0-9_-]{1,64}\z/D', $storeRef)
            || !preg_match('/\A[A-Za-z0-9._-]{1,128}\z/D', $evidenceRef)
            || !preg_match('/\A[A-Za-z0-9._-]{1,128}\z/D', $mappingRef)
            || ($costMinor !== null && ($costMinor < 0 || $costMinor > UnitCosts::MAX_MINOR))
            || ($availableQuantity !== null && ($availableQuantity < 0 || $availableQuantity > 1000000))) {
            throw new InvalidArgumentException('Invalid reviewed supplier quote.');
        }
    }
}

/**
 * INT-15: read-only reconciliation of an already mapped simple WooCommerce
 * product, in isolated CI only. No Dropify code, credentials, hooks or requests.
 */
final class DropifyPreview
{
    private static function guard(int $id): void
    {
        if (!defined('WP_CLI') || !WP_CLI || getenv('BAKATA_CI_FIXTURES') !== '1'
            || !in_array(wp_parse_url(home_url(), PHP_URL_HOST), ['localhost','127.0.0.1'], true)
            || !current_user_can('manage_options') || !current_user_can('edit_products')
            || !current_user_can('edit_post', $id)) {
            throw new RuntimeException('Dropify preview restricted to authorized isolated CI.');
        }
    }

    public function inspect(
        string $snapshotJson, string $source, string $candidateId,
        ReviewedDropifyQuote $review, ?UnitCosts $costs, PricingPolicy $policy,
        DateTimeImmutable $asOf, int $maxAgeSeconds
    ): array {
        self::guard($review->productId);
        if ($maxAgeSeconds < 1 || $maxAgeSeconds > 86400
            || $asOf > new DateTimeImmutable('now')
            || $review->observedAt > $asOf
            || $asOf->getTimestamp() - $review->observedAt->getTimestamp() > $maxAgeSeconds) {
            throw new InvalidArgumentException('Supplier observation or preview time is invalid or stale.');
        }
        if ($policy->currency !== 'COP' || $policy->minorUnit !== 2
            || get_woocommerce_currency() !== 'COP' || wc_get_price_decimals() !== 2) {
            throw new InvalidArgumentException('Only explicit COP minor-unit policy is supported.');
        }
        $snapshot = PreviewSnapshot::decode($snapshotJson);
        $rows = array_values(array_filter($snapshot['rows'], static fn(array $r): bool =>
            $r['source'] === $source && $r['external_id'] === $candidateId));
        if (count($rows) !== 1 || $rows[0]['status'] !== 'review-ready'
            || $rows[0]['coverage_pct'] !== 100 || $rows[0]['blockers'] !== []
            || $rows[0]['score_bp'] === null || $rows[0]['currency'] !== 'COP') {
            throw new InvalidArgumentException('Complete reviewed COP candidate required.');
        }
        $candidate = $rows[0];
        $product = wc_get_product($review->productId);
        if (!$product || !$product->is_type('simple') || $product->get_sku('edit') !== $review->sku
            || (int)wc_get_product_id_by_sku($review->sku) !== $review->productId) {
            throw new RuntimeException('WooCommerce product or SKU mapping changed.');
        }

        // Read only the observed identity fields. Never export the opaque
        // _dropi_product payload or the connector's token/credential fields.
        $ids = $product->get_meta('_dropi_product_id', false, 'edit');
        if (!is_array($ids) || count($ids) !== 1 || !$ids[0] instanceof \WC_Meta_Data) {
            throw new RuntimeException('Missing or ambiguous Dropi product identity.');
        }
        $id = $ids[0]->get_data()['value'] ?? null;
        if ((!is_string($id) && !is_int($id)) || (string)$id !== $review->externalId) {
            throw new RuntimeException('Dropi product identity differs from reviewed mapping.');
        }
        if ($product->get_meta('_dropi_variation', false, 'edit') !== []) {
            throw new RuntimeException('Variant mapping not supported; manual review required.');
        }

        $blockers = [];
        if ($review->costMinor === null) { $blockers[] = 'unknown-supplier-cost'; }
        if ($review->availableQuantity === null) { $blockers[] = 'unknown-supplier-stock'; }
        elseif ($review->availableQuantity === 0) { $blockers[] = 'supplier-out-of-stock'; }
        if ($costs === null) { $blockers[] = 'unknown-unit-costs'; }
        elseif ($review->costMinor === null || $costs->currency !== 'COP' || $costs->minorUnit !== 2
            || $costs->supplierMinor !== $review->costMinor) {
            throw new InvalidArgumentException('Scenario costs do not match reviewed supplier cost.');
        }

        $quote = null;
        if ($costs !== null && $review->costMinor !== null) {
            $quote = (new PricingPreview())->propose($costs, $policy);
            if (!$quote->meetsTarget || $quote->contributionMinor <= 0) {
                $blockers[] = 'nonpositive-contribution';
            }
        }
        $supplier = null;
        if ($review->costMinor !== null && $review->availableQuantity !== null) {
            $supplier = new SupplierProduct('dropify', $review->storeRef . ':' . $review->externalId,
                $candidate['title'], $review->costMinor, 'COP', 2, $review->availableQuantity, $review->observedAt);
        }
        return [
            'mode' => 'fixture-read-only',
            'status' => $blockers === [] ? 'review-ready' : 'blocked',
            'blockers' => $blockers,
            'candidate_key' => [$source,$candidateId,$candidate['observed_at']],
            'snapshot_sha256' => hash('sha256',$snapshotJson),
            'score_bp' => $candidate['score_bp'],
            'woo_product_id' => $review->productId,
            'woo_sku' => $review->sku,
            'supplier_identity' => $supplier?->identity(),
            'supplier_external_id' => $review->externalId,
            'store_ref' => $review->storeRef,
            'evidence_ref' => $review->evidenceRef,
            'mapping_ref' => $review->mappingRef,
            'observed_at' => $review->observedAt->format(DATE_ATOM),
            'supplier_cost_minor' => $review->costMinor,
            'supplier_stock' => $review->availableQuantity,
            'currency' => 'COP',
            'candidate_price_minor' => $quote?->priceMinor,
            'contribution_minor' => $quote?->contributionMinor,
            'contribution_bps' => $quote?->contributionBps,
        ];
    }
}
