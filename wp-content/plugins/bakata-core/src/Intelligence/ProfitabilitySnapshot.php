<?php
declare(strict_types=1);
namespace Bakata\Core\Intelligence;

final class ProfitabilitySnapshot
{
    public const MAX_BYTES=32768;
    private static function ck(bool $ok): void
    {
        if (!$ok) { throw new \InvalidArgumentException('Invalid profitability dossier.'); }
    }
    private static function shape(mixed $data,array $keys): void
    {
        self::ck(is_array($data) && count($data)===count($keys) && array_diff($keys,array_keys($data))===[]);
    }
    private static function match(mixed $v,string $p): bool
    {
        return is_string($v) && preg_match($p,$v)===1;
    }
    private static function ref(mixed $v): bool { return self::match($v,'/\A[A-Za-z0-9._-]{1,128}\z/D'); }
    private static function text(mixed $v,int $limit,bool $required=false): bool
    {
        return is_string($v) && strlen($v)<=$limit && preg_match('/[\x00-\x1f\x7f]/',$v)===0 && (!$required || trim($v)!=='');
    }
    private static function at(mixed $v): \DateTimeImmutable
    {
        self::ck(self::match($v,'/\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{6})?\+00:00\z/D'));
        $format=str_contains($v,'.')?'Y-m-d\TH:i:s.uP':'Y-m-d\TH:i:sP';
        $date=\DateTimeImmutable::createFromFormat('!'.$format,$v);
        self::ck($date!==false && $date->format($format)===$v);
        return $date;
    }
    private static function number(mixed $v,float $max): float
    {
        self::ck(self::match($v,'/\A(?:0|[1-9][0-9]{0,2})(?:\.[0-9]{1,30})?(?:E[+-][0-9]{1,2})?\z/D'));
        $n=(float)$v;
        self::ck(is_finite($n) && $n>=0 && $n<=$max);
        return $n;
    }
    public static function decode(string $raw,int $now): array
    {
        self::ck(strlen($raw)>0 && strlen($raw)<=self::MAX_BYTES);
        $json=str_ends_with($raw,"\n")?substr($raw,0,-1):$raw;
        $d=json_decode($json,true,12,JSON_THROW_ON_ERROR);
        self::ck(json_encode($d,JSON_THROW_ON_ERROR|JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_LINE_TERMINATORS)===$json);
        self::shape($d,['schema','mode','as_of','valid_until','catalog','link','evaluation','approval_granted','woo_mutation']);
        self::ck($d['schema']==='bakata-linked-profitability-v1' && $d['mode']==='review-reference-only'
            && $d['approval_granted']===false && $d['woo_mutation']===false);
        $asOf=self::at($d['as_of']); $until=self::at($d['valid_until']);
        self::ck($asOf->getTimestamp()<=$now && $until>$asOf && $until->getTimestamp()>$now);
        $c=$d['catalog'];
        self::shape($c,['store_id','external_id','captured_at','sku','title','simple_stock_reported','base_price_reported','suggested_price_reported']);
        $captured=self::at($c['captured_at']);
        self::ck($captured<=$asOf && $until<=$captured->modify('+24 hours')
            && self::match($c['store_id'],'/\A[1-9][0-9]{0,9}\z/D')
            && self::match($c['external_id'],'/\A[1-9][0-9]{0,29}\z/D')
            && self::text($c['sku'],128) && self::text($c['title'],300,true)
            && is_int($c['simple_stock_reported']) && $c['simple_stock_reported']>0 && $c['simple_stock_reported']<=1000000);
        foreach (['base_price_reported','suggested_price_reported'] as $key) {
            self::ck($c[$key]===null || self::match($c[$key],'/\A(?:0|[1-9][0-9]{0,9})(?:\.[0-9]{1,2})?\z/D'));
        }
        $link=$d['link'];
        self::shape($link,['id','mapping_ref','cost_ref','actor_ref','linked_at']);
        foreach (['id','mapping_ref','cost_ref','actor_ref'] as $key) { self::ck(self::ref($link[$key])); }
        $linked=self::at($link['linked_at']);
        self::ck($captured<=$linked && $linked<=$asOf);
        $e=$d['evaluation'];
        self::shape($e,['id','sha256','actor_ref','as_of','rubric','status','score','coverage_pct','commercial_observation','currency','economics','contribution_minor','margin_pct','components']);
        $evaluated=self::at($e['as_of']);
        self::ck(self::ref($e['id']) && self::ref($e['actor_ref']) && self::match($e['sha256'],'/\A[0-9a-f]{64}\z/D')
            && $e['rubric']==='int06-v1' && $e['status']==='review-ready' && $e['coverage_pct']===100
            && $e['currency']==='COP' && $evaluated<=$linked);
        $obs=$e['commercial_observation'];
        self::shape($obs,['source','external_id','observed_at']);
        self::ck(self::match($obs['source'],'/\A[a-z0-9][a-z0-9_-]{0,63}\z/D')
            && self::text($obs['external_id'],128,true) && self::at($obs['observed_at'])<=$evaluated);
        $m=$e['economics'];
        $amounts=['sale_price_minor','supplier_cost_minor','shipping_minor','fixed_fee_minor','return_reserve_minor','other_cost_minor'];
        self::shape($m,array_merge($amounts,['variable_deduction_bps']));
        foreach ($amounts as $key) { self::ck(is_int($m[$key]) && $m[$key]>=0 && $m[$key]<=1000000000000); }
        $sale=$m['sale_price_minor']; $bps=$m['variable_deduction_bps'];
        self::ck($sale>0 && is_int($bps) && $bps>=0 && $bps<=10000);
        $variable=intdiv($sale*$bps+9999,10000);
        $contribution=$sale-$m['supplier_cost_minor']-$m['shipping_minor']-$m['fixed_fee_minor']-$m['return_reserve_minor']-$m['other_cost_minor']-$variable;
        self::ck($contribution>0 && $e['contribution_minor']===$contribution
            && self::match($e['margin_pct'],'/\A(?:0|[1-9][0-9]{0,2})\.[0-9]{2}\z/D')
            && abs(self::number($e['margin_pct'],100)-$contribution*100/$sale)<=0.005000001);
        self::ck(self::match($e['score'],'/\A(?:0|[1-9][0-9]{0,2})\.[0-9]{2}\z/D'));
        $total=self::number($e['score'],100);
        $weights=PreviewSnapshot::WEIGHTS;
        self::ck(is_array($e['components']) && array_is_list($e['components']) && count($e['components'])===count($weights));
        $seen=[]; $sum=0.0;
        foreach ($e['components'] as $component) {
            self::shape($component,['criterion','weight','score','points','evidence_ref']);
            $key=$component['criterion'];
            self::ck(is_string($key) && isset($weights[$key]) && !isset($seen[$key]) && $component['weight']===$weights[$key] && self::ref($component['evidence_ref']));
            $seen[$key]=true;
            $score=self::number($component['score'],100); $points=self::number($component['points'],$weights[$key]);
            self::ck(abs($points-$score*$weights[$key]/100)<0.000001);
            if ($key==='profitability') {
                self::ck($component['evidence_ref']===$link['cost_ref'] && abs($score-min(100,$contribution*10000/($sale*30)))<0.000001);
            } else {
                self::ck(in_array($score,[0.0,25.0,50.0,75.0,100.0],true));
                if (in_array($key,['supplier_reliability','return_risk'],true)) { self::ck($score>0); }
            }
            $sum+=$points;
        }
        self::ck(abs($total-$sum)<=0.005000001);
        return $d;
    }
    public static function matches(array $d,array $page,array $row): bool
    {
        $c=$d['catalog']; $s=$page['snapshot'];
        return $c['store_id']===$s['store_id'] && $c['external_id']===$row['external_id']
            && $c['captured_at']===str_replace('Z','+00:00',$s['captured_at'])
            && $c['sku']===$row['sku'] && $c['title']===$row['title'] && $row['type']==='simple'
            && $c['simple_stock_reported']===$row['simple_stock']
            && $c['base_price_reported']===$row['base_price'] && $c['suggested_price_reported']===$row['suggested_price'];
    }
}
