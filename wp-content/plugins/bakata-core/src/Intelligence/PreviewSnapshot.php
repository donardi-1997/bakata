<?php
declare(strict_types=1);

namespace Bakata\Core\Intelligence;

use InvalidArgumentException;

final class PreviewSnapshot
{
    public const MAX_BYTES = 262144;
    public const WEIGHTS = [
        'profitability' => 25, 'demand' => 20, 'supplier_reliability' => 15,
        'logistics' => 15, 'advertising' => 10, 'differentiation' => 10, 'return_risk' => 5,
    ];

    private static function require(bool $ok): void
    {
        if (!$ok) {
            throw new InvalidArgumentException('Invalid intelligence preview snapshot.');
        }
    }

    private static function shape(array $row, array $keys): void
    {
        self::require(count($row) === count($keys) && array_diff($keys, array_keys($row)) === []);
    }

    private static function text(mixed $value, int $limit): bool
    {
        return is_string($value) && trim($value) !== '' && strlen($value) <= $limit
            && preg_match('/[\x00-\x1f\x7f]/', $value) === 0;
    }

    private static function timestamp(mixed $value): bool
    {
        if (!is_string($value) || !preg_match('/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$/D', $value)) {
            return false;
        }
        $date = \DateTimeImmutable::createFromFormat('!Y-m-d\TH:i:sP', $value);
        return $date !== false && $date->format('Y-m-d\TH:i:sP') === $value;
    }

    private static function number(mixed $v, int $max): bool
    {
        return is_int($v) && $v >= 0 && $v <= $max;
    }

    public static function decode(string $json): array
    {
        self::require(strlen($json) > 0 && strlen($json) <= self::MAX_BYTES);
        $data = json_decode($json, true, 12, JSON_THROW_ON_ERROR);
        self::require(is_array($data));
        self::shape($data, ['schema', 'mode', 'rubric', 'as_of', 'rows']);
        self::require($data['schema'] === 'bakata-intelligence-preview-v1' && $data['mode'] === 'fixture'
            && $data['rubric'] === 'int06-v1' && self::timestamp($data['as_of'])
            && is_array($data['rows']) && array_is_list($data['rows']) && count($data['rows']) <= 100);
        $identities = [];
        foreach ($data['rows'] as $row) {
            self::require(is_array($row));
            self::shape($row, ['source','external_id','title','url','observed_at','currency','price_minor',
                'status','coverage_pct','score_bp','blockers','components']);
            self::require(is_string($row['source']) && preg_match('/^fixture(?:-[a-z0-9_-]{1,55})?$/D', $row['source']) === 1
                && self::text($row['external_id'], 128) && self::text($row['title'], 1200)
                && self::text($row['url'], 2048) && self::timestamp($row['observed_at'])
                && $row['observed_at'] <= $data['as_of']
                && in_array($row['currency'], ['COP','USD','EUR'], true)
                && ($row['price_minor'] === null || self::number($row['price_minor'], 10**15)));
            $url = parse_url($row['url']);
            self::require(is_array($url) && ($url['scheme'] ?? '') === 'https'
                && is_string($url['host'] ?? null) && preg_match('/^[a-z0-9.-]+\.invalid$/D', $url['host']) === 1
                && !isset($url['user'], $url['pass']) && !isset($url['user']) && !isset($url['pass'])
                && !isset($url['query']) && !isset($url['fragment']) && !isset($url['port']));
            $key = $row['source'] . ':' . $row['external_id'];
            self::require(!isset($identities[$key]));
            $identities[$key] = true;
            self::require(in_array($row['status'], ['incomplete','blocked','review-ready'], true)
                && is_array($row['blockers']) && array_is_list($row['blockers']) && count($row['blockers']) <= 4
                && is_array($row['components']) && array_is_list($row['components'])
                && count($row['components']) === count(self::WEIGHTS));
            foreach ($row['blockers'] as $blocker) {
                self::require(in_array($blocker, ['stale-observation','nonpositive-contribution',
                    'critical-review:supplier_reliability','critical-review:return_risk'], true));
            }
            $coverage = $sum = 0;
            $seen = [];
            foreach ($row['components'] as $component) {
                self::require(is_array($component));
                self::shape($component, ['criterion','weight','score_bp','points_bp','evidence_ref','reason']);
                $criterion = $component['criterion'];
                self::require(is_string($criterion) && isset(self::WEIGHTS[$criterion]) && !isset($seen[$criterion])
                    && $component['weight'] === self::WEIGHTS[$criterion] && self::text($component['reason'], 2000)
                    && ($component['evidence_ref'] === null || (is_string($component['evidence_ref'])
                        && preg_match('/^[A-Za-z0-9._-]{1,128}$/D', $component['evidence_ref']) === 1)));
                $seen[$criterion] = true;
                $score = $component['score_bp'];
                $points = $component['points_bp'];
                if ($score === null) {
                    self::require($points === null);
                    continue;
                }
                self::require(self::number($score, 10000) && self::number($points, 100 * $component['weight'])
                    && $component['evidence_ref'] !== null
                    && abs($points * 100 - $score * $component['weight']) <= 100);
                if ($criterion !== 'profitability') {
                    self::require(in_array($score, [0,2500,5000,7500,10000], true));
                }
                $coverage += $component['weight'];
                $sum += $points;
            }
            self::require($row['coverage_pct'] === $coverage);
            $total = $row['score_bp'];
            $expectedStatus = $row['blockers'] !== [] ? 'blocked' : ($coverage === 100 ? 'review-ready' : 'incomplete');
            self::require($row['status'] === $expectedStatus);
            if ($coverage === 100 && !in_array('stale-observation', $row['blockers'], true)) {
                self::require(self::number($total, 10000) && abs($total - $sum) <= 4);
            } else {
                self::require($total === null);
            }
        }
        return $data;
    }

    public static function filter(array $rows, string $query, string $status): array
    {
        $rows = array_values(array_filter($rows, static function (array $row) use ($query, $status): bool {
            return ($status === '' || $row['status'] === $status)
                && ($query === '' || stripos($row['title'] . ' ' . $row['source'] . ' ' . $row['external_id'], $query) !== false);
        }));
        usort($rows, static function (array $a, array $b): int {
            $aRank = $a['status'] === 'review-ready' ? 0 : 1;
            $bRank = $b['status'] === 'review-ready' ? 0 : 1;
            return ($aRank <=> $bRank) ?: (($b['score_bp'] ?? -1) <=> ($a['score_bp'] ?? -1))
                ?: ([$a['source'],$a['external_id']] <=> [$b['source'],$b['external_id']]);
        });
        return $rows;
    }
}
