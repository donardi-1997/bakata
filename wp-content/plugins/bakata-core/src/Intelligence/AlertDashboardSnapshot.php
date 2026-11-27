<?php
declare(strict_types=1);
namespace Bakata\Core\Intelligence;

final class AlertDashboardSnapshot
{
    public const MAX_BYTES=262144;
    public const STATES=['open'=>'Abierta','acknowledged'=>'Reconocida','resolved'=>'Resuelta'];
    public const PRIORITIES=['review-first'=>'Revisar primero','review'=>'Revisar','informational'=>'Informativa'];
    public const CODES=[
        'capture-future'=>'Captura futura','capture-stale'=>'Captura antigua',
        'evaluation-observation-superseded'=>'Evaluación requiere actualización','first-observation'=>'Primera observación',
        'baseline-too-old'=>'Comparación demasiado antigua','comparison-scope-changed'=>'Cambió el alcance de comparación',
        'price-reported'=>'Precio informado','price-unknown'=>'Precio desconocido','price-from-zero'=>'Precio anterior en cero',
        'price-increased'=>'Aumento de precio reportado','price-decreased'=>'Disminución de precio reportado',
        'stock-unknown'=>'Stock desconocido','stock-reported'=>'Stock informado','stock-zero'=>'Stock reportado en cero',
        'stock-reappeared'=>'Stock nuevamente reportado','stock-changed'=>'Cambio de stock reportado'];
    private static function ck(bool $ok): void
    {
        if (!$ok) { throw new \InvalidArgumentException('Invalid alert dashboard export.'); }
    }
    private static function shape(mixed $v,array $keys): void
    {
        self::ck(is_array($v) && count($v)===count($keys) && array_diff($keys,array_keys($v))===[]);
    }
    private static function match(mixed $v,string $p): bool { return is_string($v) && preg_match($p,$v)===1; }
    private static function sha(mixed $v): bool { return self::match($v,'/\A[0-9a-f]{64}\z/D'); }
    private static function text(mixed $v,int $max): bool
    {
        return is_string($v) && strlen($v)<=$max && preg_match('/[\x00-\x1f\x7f]/',$v)===0;
    }
    private static function at(mixed $v): \DateTimeImmutable
    {
        self::ck(self::match($v,'/\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{6})?\+00:00\z/D'));
        $format=str_contains($v,'.')?'Y-m-d\TH:i:s.uP':'Y-m-d\TH:i:sP';
        $d=\DateTimeImmutable::createFromFormat('!'.$format,$v);
        self::ck($d!==false && $d->format($format)===$v);
        return $d;
    }
    private static function refs(mixed $v,bool $required): void
    {
        self::ck(is_array($v) && array_is_list($v) && count($v)<=20 && (!$required || count($v)>0));
        foreach ($v as $sha) { self::ck(self::sha($sha)); }
        self::ck(count(array_unique($v))===count($v));
    }
    public static function decode(string $raw,int $now): array
    {
        self::ck(strlen($raw)>0 && strlen($raw)<=self::MAX_BYTES);
        $json=str_ends_with($raw,"\n")?substr($raw,0,-1):$raw;
        $d=json_decode($json,true,12,JSON_THROW_ON_ERROR);
        self::ck(json_encode($d,JSON_THROW_ON_ERROR|JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_LINE_TERMINATORS)===$json);
        self::shape($d,['schema','mode','archive_ref','store_id','price_threshold_bps','exported_at','counts','rows','next_after','delivery_enabled','woo_mutation']);
        self::ck($d['schema']==='bakata-alert-dashboard-v1' && $d['mode']==='historical-read-only'
            && $d['delivery_enabled']===false && $d['woo_mutation']===false
            && self::match($d['archive_ref'],'/\A[A-Za-z0-9._-]{1,128}\z/D') && self::match($d['store_id'],'/\A[1-9][0-9]{0,9}\z/D')
            && is_int($d['price_threshold_bps']) && $d['price_threshold_bps']>=1 && $d['price_threshold_bps']<=10000);
        $export=self::at($d['exported_at']);
        self::ck($export->getTimestamp()<=$now+300 && is_array($d['rows']) && array_is_list($d['rows']) && count($d['rows'])<=20);
        self::shape($d['counts'],array_keys(self::STATES));
        $counts=array_fill_keys(array_keys(self::STATES),0); $seen=[];
        foreach ($d['rows'] as $r) {
            self::shape($r,['signal_id','external_id','sku','title','code','priority','field','previous','current','change_pct','captured_at','previous_at','first_seen','state','alert_sha256','latest_event_sha256','current_pages','previous_pages']);
            self::ck(self::sha($r['signal_id']) && !isset($seen[$r['signal_id']]) && self::sha($r['alert_sha256']) && self::sha($r['latest_event_sha256'])
                && self::match($r['external_id'],'/\A[1-9][0-9]{0,29}\z/D') && self::text($r['sku'],128) && self::text($r['title'],300) && trim($r['title'])!==''
                && is_string($r['state']) && isset(self::STATES[$r['state']]) && is_string($r['priority']) && isset(self::PRIORITIES[$r['priority']])
                && is_string($r['code']) && isset(self::CODES[$r['code']]));
            $seen[$r['signal_id']]=true; ++$counts[$r['state']];
            $captured=self::at($r['captured_at']); $first=self::at($r['first_seen']);
            self::ck($first<=$export && ($r['code']==='capture-future' || $captured<=$first));
            self::ck($r['previous_at']===null || self::at($r['previous_at'])<$captured);
            self::refs($r['current_pages'],true); self::refs($r['previous_pages'],$r['previous_at']!==null);
            self::ck($r['previous_at']!==null || $r['previous_pages']===[]);
            self::ck(in_array($r['field'],[null,'sku','type','warehouse','base_price','suggested_price','simple_stock'],true));
            foreach (['previous','current'] as $k) {
                $v=$r[$k];
                if ($r['field']===null) { self::ck($v===null); }
                elseif ($r['field']==='simple_stock') { self::ck($v===null || (is_int($v) && $v>=0 && $v<=1000000)); }
                elseif (in_array($r['field'],['base_price','suggested_price'],true)) { self::ck($v===null || self::match($v,'/\A(?:0|[1-9][0-9]{0,9})(?:\.[0-9]{1,2})?\z/D')); }
                else { self::ck(self::text($v,150)); }
            }
            self::ck($r['change_pct']===null || (in_array($r['field'],['base_price','suggested_price'],true)
                && self::match($r['change_pct'],'/\A-?(?:0|[1-9][0-9]{0,15})\.[0-9]{2}\z/D')));
            $key=['bakata-opportunity-radar-v1',$d['store_id'],$r['external_id'],$r['captured_at'],$r['previous_at'],$r['code'],$r['field']];
            self::ck(hash('sha256',json_encode($key,JSON_THROW_ON_ERROR|JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES))===$r['signal_id']);
        }
        foreach ($counts as $k=>$v) { self::ck($d['counts'][$k]===$v); }
        if ($d['next_after']!==null) {
            self::ck(self::sha($d['next_after']) && count($seen)>0 && $d['next_after']===max(array_keys($seen)));
        }
        return $d;
    }
    public static function filter(array $rows,string $state,string $priority,string $query): array
    {
        return array_values(array_filter($rows,static fn(array $r): bool =>
            ($state==='' || $r['state']===$state) && ($priority==='' || $r['priority']===$priority)
            && ($query==='' || stripos($r['title'].' '.$r['sku'].' '.$r['external_id'],$query)!==false)));
    }
}
