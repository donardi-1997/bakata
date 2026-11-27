<?php
declare(strict_types=1);
namespace Bakata\Core\Intelligence;

final class CatalogReviewSnapshot
{
    public const MAX_BYTES = 262144;

    private static function check(bool $ok): void
    {
        if (!$ok) { throw new \InvalidArgumentException('Invalid catalog review export.'); }
    }

    private static function shape(mixed $data, array $keys): void
    {
        self::check(is_array($data) && count($data)===count($keys) && array_diff($keys,array_keys($data))===[]);
    }

    private static function text(mixed $value, int $limit, bool $required=false): bool
    {
        return is_string($value) && strlen($value)<=$limit
            && preg_match('/[\x00-\x1f\x7f]/',$value)===0 && (!$required || trim($value)!=='');
    }

    private static function pattern(mixed $v, string $pattern): bool
    {
        return is_string($v) && preg_match($pattern,$v)===1;
    }

    public static function decode(string $raw, int $now): array
    {
        self::check(strlen($raw)>0 && strlen($raw)<=self::MAX_BYTES);
        // Accept compact exporter output with at most one trailing LF.
        $json=str_ends_with($raw,"\n")?substr($raw,0,-1):$raw;
        $data=json_decode($json,true,12,JSON_THROW_ON_ERROR);
        self::check(json_encode($data,JSON_THROW_ON_ERROR|JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_LINE_TERMINATORS)===$json);
        self::shape($data,['schema','source','source_page_sha256','operator_ref','snapshot']);
        self::check($data['schema']==='bakata-catalog-review-v1' && $data['source']==='dropify-bridge-archive'
            && self::pattern($data['source_page_sha256'],'/\A[0-9a-f]{64}\z/D')
            && self::pattern($data['operator_ref'],'/\A[A-Za-z0-9._-]{1,128}\z/D'));
        $s=$data['snapshot'];
        self::shape($s,['schema','captured_at','store_id','page','page_size','offset','possible_next','rows','approval_ref','query_sha256']);
        self::check($s['schema']==='bakata-dropify-bridge-v1'
            && self::pattern($s['store_id'],'/\A[1-9][0-9]{0,9}\z/D')
            && self::pattern($s['approval_ref'],'/\A[A-Za-z0-9._-]{1,128}\z/D')
            && self::pattern($s['query_sha256'],'/\A[0-9a-f]{64}\z/D')
            && self::pattern($s['captured_at'],'/\A[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\z/D'));
        $at=\DateTimeImmutable::createFromFormat('!Y-m-d\TH:i:s\Z',$s['captured_at'],new \DateTimeZone('UTC'));
        self::check($at!==false && $at->format('Y-m-d\TH:i:s\Z')===$s['captured_at'] && $at->getTimestamp()<=$now+300);
        self::check(is_int($s['page']) && $s['page']>=1 && $s['page']<=100
            && is_int($s['page_size']) && $s['page_size']>=1 && $s['page_size']<=20
            && $s['offset']===($s['page']-1)*$s['page_size']
            && is_array($s['rows']) && array_is_list($s['rows']) && count($s['rows'])<=$s['page_size']
            && $s['possible_next']===(count($s['rows'])===$s['page_size']));
        $seen=[];
        foreach ($s['rows'] as $row) {
            self::shape($row,['external_id','sku','title','type','base_price','suggested_price','simple_stock','categories','warehouse']);
            self::check(self::pattern($row['external_id'],'/\A[1-9][0-9]{0,29}\z/D') && !isset($seen[$row['external_id']])
                && self::text($row['sku'],128) && self::text($row['title'],300,true) && self::text($row['warehouse'],150)
                && in_array($row['type'],['simple','unresolved'],true));
            $seen[$row['external_id']]=true;
            foreach (['base_price','suggested_price'] as $field) {
                self::check($row[$field]===null || self::pattern($row[$field],'/\A(?:0|[1-9][0-9]{0,9})(?:\.[0-9]{1,2})?\z/D'));
            }
            $stock=$row['simple_stock'];
            self::check($stock===null || ($row['type']==='simple' && is_int($stock) && $stock>=0 && $stock<=1000000));
            self::check(is_array($row['categories']) && array_is_list($row['categories']) && count($row['categories'])<=20);
            foreach ($row['categories'] as $label) { self::check(self::text($label,100,true)); }
        }
        return $data;
    }

    public static function stockState(array $row): string
    {
        return $row['simple_stock']===null?'unknown':($row['simple_stock']===0?'zero':'positive');
    }

    public static function filter(array $rows, string $query, string $stock): array
    {
        return array_values(array_filter($rows,static function(array $row) use ($query,$stock): bool {
            return ($stock==='' || self::stockState($row)===$stock)
                && ($query==='' || stripos($row['title'].' '.$row['sku'].' '.$row['external_id'].' '.implode(' ',$row['categories']),$query)!==false);
        }));
    }
}
