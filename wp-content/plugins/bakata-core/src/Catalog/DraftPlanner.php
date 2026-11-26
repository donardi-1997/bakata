<?php
declare(strict_types=1);

namespace Bakata\Core\Catalog;

use Bakata\Core\Pricing\PricingPolicy;
use Bakata\Core\Pricing\PricingPreview;
use Bakata\Core\Pricing\PricingQuote;
use Bakata\Core\Pricing\UnitCosts;
use Bakata\Core\Suppliers\SupplierProduct;
use DateTimeImmutable;
use InvalidArgumentException;

final readonly class DraftPlan
{
    public function __construct(
        public SupplierProduct $source,
        public PricingQuote $quote,
        public string $fingerprint,
    ) {}
}

/** Pure planning. Source inventory and price are proposals, not sale terms. */
final class DraftPlanner
{
    public function plan(
        SupplierProduct $source,
        UnitCosts $costs,
        PricingPolicy $policy,
        DateTimeImmutable $asOf,
        int $maxAgeSeconds,
    ): DraftPlan {
        if ($maxAgeSeconds < 1 || $maxAgeSeconds > 30 * 86400) {
            throw new InvalidArgumentException('Invalid import freshness policy.');
        }
        $age = $asOf->getTimestamp() - $source->observedAt->getTimestamp();
        if ($age < 0 || $age > $maxAgeSeconds) {
            throw new InvalidArgumentException('Source observation is stale or from the future.');
        }
        if ($source->currency !== $costs->currency || $source->currencyMinorUnit !== $costs->minorUnit
            || $source->unitCostMinor !== $costs->supplierMinor) {
            throw new InvalidArgumentException('Source and pricing costs do not match.');
        }
        $quote = (new PricingPreview())->propose($costs, $policy);
        // Include all cost and policy inputs. A new observation of unchanged
        // commercial data has the same fingerprint, but must still be fresh.
        $fingerprint = hash('sha256', json_encode([
            'version' => 1,
            'source' => $source->fingerprint(),
            'costs' => [
                $costs->currency, $costs->minorUnit, $costs->supplierMinor,
                $costs->shippingMinor, $costs->fixedPaymentMinor,
                $costs->returnReserveMinor, $costs->otherMinor,
            ],
            'policy' => [
                $policy->currency, $policy->minorUnit, $policy->variableDeductionBps,
                $policy->targetContributionBps, $policy->priceStepMinor, $policy->maxPriceMinor,
            ],
            'proposedPriceMinor' => $quote->priceMinor,
        ], JSON_THROW_ON_ERROR));
        return new DraftPlan($source, $quote, $fingerprint);
    }
}
