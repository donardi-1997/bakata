<?php
declare(strict_types=1);
namespace Bakata\Core\Intelligence;

final class ProfitabilityPanel
{
    private const ACTION='bakata_profitability_load';
    public static function register(): void
    {
        add_action('admin_post_'.self::ACTION,[self::class,'upload']);
        add_action('admin_post_bakata_profitability_clear',[self::class,'clear']);
    }
    private static function key(): string { return 'bk_profitability_'.get_current_user_id(); }
    public static function forget(): void { delete_transient(self::key()); }
    private static function post(string $action): void
    {
        if (!current_user_can(AdminPanel::CAPABILITY)) { wp_die('Acceso no autorizado.','',['response'=>403]); }
        if (($_SERVER['REQUEST_METHOD']??'')!=='POST') { wp_die('Método no permitido.','',['response'=>405]); }
        check_admin_referer($action,'bk_profitability_nonce');
    }
    private static function redirect(string $notice): void
    {
        wp_safe_redirect(add_query_arg(['page'=>'bakata-catalog-review','bk_profitability_notice'=>$notice],admin_url('admin.php')));
        exit;
    }
    private static function matchesPage(array $d,array $page): bool
    {
        foreach ($page['snapshot']['rows'] as $row) {
            if (ProfitabilitySnapshot::matches($d,$page,$row)) { return true; }
        }
        return false;
    }
    public static function upload(): void
    {
        self::post(self::ACTION);
        try {
            $page=CatalogReviewPanel::current();
            $file=$_FILES['dossier']??null;
            if ($page===null || !is_array($file) || ($file['error']??null)!==UPLOAD_ERR_OK
                || !is_string($file['tmp_name']??null) || !is_uploaded_file($file['tmp_name'])
                || !is_int($file['size']??null) || $file['size']>ProfitabilitySnapshot::MAX_BYTES) {
                throw new \InvalidArgumentException('Invalid upload.');
            }
            $raw=file_get_contents($file['tmp_name'],false,null,0,ProfitabilitySnapshot::MAX_BYTES+1);
            if (!is_string($raw)) { throw new \InvalidArgumentException('Invalid upload.'); }
            $d=ProfitabilitySnapshot::decode($raw,time());
            if (!self::matchesPage($d,$page)) { throw new \InvalidArgumentException('Mismatched capture.'); }
            $ttl=min(15*MINUTE_IN_SECONDS,strtotime($d['valid_until'])-time());
            if ($ttl<=0) { throw new \InvalidArgumentException('Expired dossier.'); }
            set_transient(self::key(),$raw,$ttl);
            if (get_transient(self::key())!==$raw) { throw new \RuntimeException('Cache unavailable.'); }
        } catch (\Throwable $e) { self::redirect('invalid'); }
        self::redirect('loaded');
    }
    public static function clear(): void
    {
        self::post('bakata_profitability_clear');
        self::forget(); self::redirect('cleared');
    }
    public static function current(array $page): ?array
    {
        $raw=get_transient(self::key());
        if (!is_string($raw)) { return null; }
        try {
            $d=ProfitabilitySnapshot::decode($raw,time());
            return self::matchesPage($d,$page)?$d:null;
        } catch (\Throwable $e) { return null; }
    }
    public static function form(?array $d): void
    {
        $notices=['loaded'=>'Expediente económico cargado.','invalid'=>'Expediente inválido, vencido o de otra captura.','cleared'=>'Expediente eliminado.'];
        $notice=isset($_GET['bk_profitability_notice']) && is_string($_GET['bk_profitability_notice'])?sanitize_text_field(wp_unslash($_GET['bk_profitability_notice'])):'';
        echo '<h2>Expediente de rentabilidad</h2><p>Adjunta un expediente de Intelligence para un candidato de esta captura. La vista verifica coherencia, no autentica el origen ni aprueba una venta.</p>';
        if (isset($notices[$notice])) { echo '<div role="status" class="notice notice-info"><p>'.esc_html($notices[$notice]).'</p></div>'; }
        echo '<form method="post" enctype="multipart/form-data" action="'.esc_url(admin_url('admin-post.php')).'"><input type="hidden" name="action" value="'.esc_attr(self::ACTION).'">';
        wp_nonce_field(self::ACTION,'bk_profitability_nonce',false);
        echo '<label for="bk-profitability-file">Expediente JSON (máximo 32 KiB)</label> <input id="bk-profitability-file" name="dossier" type="file" accept=".json,application/json" required> ';
        submit_button('Cargar expediente','secondary','bk_profitability_load',false);
        echo '</form>';
        if ($d!==null) {
            echo '<form method="post" action="'.esc_url(admin_url('admin-post.php')).'"><input type="hidden" name="action" value="bakata_profitability_clear">';
            wp_nonce_field('bakata_profitability_clear','bk_profitability_nonce',false);
            submit_button('Eliminar expediente','secondary','bk_profitability_clear',false);
            echo '</form>';
        }
    }
    private static function money(int $minor): string { return 'COP '.number_format($minor/100,2,',','.'); }
    public static function details(array $d): void
    {
        $e=$d['evaluation']; $m=$e['economics']; $link=$d['link'];
        echo '<strong>Escenario listo para revisión, no aprobado</strong><br>Contribución: '.esc_html(self::money($e['contribution_minor'])).'<br>Margen: '.esc_html(str_replace('.',',',$e['margin_pct'])).'% · Puntos: '.esc_html(str_replace('.',',',$e['score'])).'/100';
        echo '<details><summary>Ver costos y evidencia</summary><p>Validez máxima declarada: '.esc_html($d['valid_until']).' · Nueva evidencia puede invalidarlo antes.</p><ul>';
        $labels=['sale_price_minor'=>'Precio de venta del escenario','supplier_cost_minor'=>'Costo de adquisición revisado','shipping_minor'=>'Transporte','fixed_fee_minor'=>'Cargo fijo','return_reserve_minor'=>'Reserva de devoluciones','other_cost_minor'=>'Otros costos'];
        foreach ($labels as $key=>$label) { echo '<li>'.esc_html($label).': '.esc_html(self::money($m[$key])).'</li>'; }
        echo '<li>Deducciones variables: '.esc_html(number_format($m['variable_deduction_bps']/100,2,',','.')).'% ('.esc_html(self::money(intdiv($m['sale_price_minor']*$m['variable_deduction_bps']+9999,10000))).')</li></ul>';
        $criteria=['profitability'=>'Rentabilidad','demand'=>'Demanda','supplier_reliability'=>'Proveedor','logistics'=>'Logística','advertising'=>'Publicidad','differentiation'=>'Diferenciación','return_risk'=>'Bajo riesgo de devolución'];
        echo '<ul>';
        foreach ($e['components'] as $c) { echo '<li>'.esc_html($criteria[$c['criterion']]).' ('.esc_html((string)$c['weight']).'%): '.esc_html(number_format((float)$c['score'],2,',','.')).' · Ref: '.esc_html($c['evidence_ref']).'</li>'; }
        echo '</ul><p>Evaluación: '.esc_html($e['id']).' · Vínculo: '.esc_html($link['id']).'<br>Mapeo: '.esc_html($link['mapping_ref']).' · Costo: '.esc_html($link['cost_ref']).' · Operador: '.esc_html($link['actor_ref']).'<br>SHA-256: <code>'.esc_html($e['sha256']).'</code></p><p>Margen de contribución del escenario, no utilidad neta. No certifica costos, demanda ni disponibilidad vendible.</p></details>';
    }
}
