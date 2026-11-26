<?php
declare(strict_types=1);

namespace Bakata\Core\Pricing;

use InvalidArgumentException;
use RuntimeException;

/** All amounts are per sellable unit and in the explicitly named minor unit. */
final readonly class UnitCosts
{
    public const MAX_MINOR = 1_000_000_000_000;

    public function __construct(
        public string $currency,
        public int $minorUnit,
        public int $supplierMinor,
        public int $shippingMinor,
        public int $fixedPaymentMinor,
        public int $returnReserveMinor,
        public int $otherMinor,
    ) {
        if (PHP_INT_SIZE < 8 || !preg_match('/\A[A-Z]{3}\z/D', $currency) || $minorUnit < 0 || $minorUnit > 4) {
            throw new InvalidArgumentException('Invalid currency or integer platform.');
        }
        foreach ([$supplierMinor, $shippingMinor, $fixedPaymentMinor, $returnReserveMinor, $otherMinor] as $cost) {
            if ($cost < 0 || $cost > self::MAX_MINOR) {
                throw new InvalidArgumentException('Invalid fixed unit cost.');
            }
        }
        if ($this->total() > self::MAX_MINOR) {
            throw new InvalidArgumentException('Total cost exceeds supported bound.');
        }
    }

    public function total(): int
    {
        return $this->supplierMinor + $this->shippingMinor + $this->fixedPaymentMinor
            + $this->returnReserveMinor + $this->otherMinor;
    }
}

/**
 * Explicit scenario policy, no implicit taxes, exchange rates or fee assumptions.
 * Rates are basis points of gross customer price; 100 bps = 1%.
 * Combined variable deductions are rounded up once to the minor unit.
 */
final readonly class PricingPolicy
{
    public function __construct(
        public string $currency,
        public int $minorUnit,
        public int $variableDeductionBps,
        public int $targetContributionBps,
        public int $priceStepMinor,
        public int $maxPriceMinor,
    ) {
        if (!preg_match('/\A[A-Z]{3}\z/D', $currency) || $minorUnit < 0 || $minorUnit > 4
            || $variableDeductionBps < 0 || $variableDeductionBps >= 10000
            || $targetContributionBps < 0 || $targetContributionBps >= 10000
            || $variableDeductionBps + $targetContributionBps >= 10000
            || $priceStepMinor < 1 || $maxPriceMinor < $priceStepMinor
            || $maxPriceMinor > UnitCosts::MAX_MINOR) {
            throw new InvalidArgumentException('Invalid pricing policy or infeasible rate combination.');
        }
    }
}

final readonly class PricingQuote
{
    public function __construct(
        public string $currency,
        public int $minorUnit,
        public int $priceMinor,
        public int $fixedCostsMinor,
        public int $variableDeductionsMinor,
        public int $contributionMinor,
        public int $contributionBps,
        public int $targetContributionBps,
        public bool $meetsTarget,
    ) {}
}

/** Pure simulation. No WooCommerce writes, discounts, tax engine or publication. */
final class PricingPreview
{
    private const BPS = 10000;

    private static function ceilDiv(int $numerator, int $denominator): int
    {
        return intdiv($numerator, $denominator) + ($numerator % $denominator === 0 ? 0 : 1);
    }

    private function requireCurrency(UnitCosts $costs, PricingPolicy $policy): void
    {
        if ($costs->currency !== $policy->currency || $costs->minorUnit !== $policy->minorUnit) {
            throw new InvalidArgumentException('Currency or minor unit mismatch.');
        }
    }

    /** Evaluate a positive gross price (including an off-step manual scenario). */
    public function evaluate(UnitCosts $costs, PricingPolicy $policy, int $priceMinor): PricingQuote
    {
        $this->requireCurrency($costs, $policy);
        if ($priceMinor < 1 || $priceMinor > $policy->maxPriceMinor) {
            throw new InvalidArgumentException('Price outside scenario limits.');
        }
        $fixed = $costs->total();
        $variable = self::ceilDiv($priceMinor * $policy->variableDeductionBps, self::BPS);
        $contribution = $priceMinor - $fixed - $variable;
        $scaled = $contribution * self::BPS;
        // Floor even for negative margins, rather than PHP's truncation toward zero.
        $bps = intdiv($scaled, $priceMinor);
        if ($scaled < 0 && $scaled % $priceMinor !== 0) { $bps--; }

        return new PricingQuote(
            $policy->currency, $policy->minorUnit, $priceMinor, $fixed, $variable,
            $contribution, $bps, $policy->targetContributionBps,
            $scaled >= $priceMinor * $policy->targetContributionBps,
        );
    }

    /** Smallest positive multiple of step meeting the target within the price ceiling. */
    public function propose(UnitCosts $costs, PricingPolicy $policy): PricingQuote
    {
        $this->requireCurrency($costs, $policy);
        $netBps = self::BPS - $policy->variableDeductionBps - $policy->targetContributionBps;
        // Unrounded deductions yield a necessary lower bound. Rounded deductions
        // can add less than one minor unit; at most 10,000 extra minor units
        // are needed because netBps >= 1. Test each aligned candidate, not a
        // binary search: rounding can make the predicate locally non-monotonic.
        $lower = max(1, self::ceilDiv($costs->total() * self::BPS, $netBps));
        $step = $policy->priceStepMinor;
        $candidate = self::ceilDiv($lower, $step) * $step;
        for ($attempt = 0; $attempt <= self::BPS && $candidate <= $policy->maxPriceMinor; $attempt++, $candidate += $step) {
            $quote = $this->evaluate($costs, $policy, $candidate);
            if ($quote->meetsTarget) { return $quote; }
        }
        throw new RuntimeException('No price meets the contribution target within the scenario ceiling.');
    }
}
