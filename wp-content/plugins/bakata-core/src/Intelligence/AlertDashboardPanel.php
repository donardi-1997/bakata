<?php
declare(strict_types=1);
namespace Bakata\Core\Intelligence;

final class AlertDashboardPanel
{
    private const SLUG='bakata-alert-dashboard';
    private const LOAD='bakata_alert_dashboard_load';
    private const CLEAR='bakata_alert_dashboard_clear';

    public static function register(): void
    {
        add_action('admin_menu',[self::class,'menu'],25);
        add_action('admin_post_'.self::LOAD,[self::class,'upload']);
        add_action('admin_post_'.self::CLEAR,[self::class,'clear']);
    }
    public static function menu(): void
    {
        add_submenu_page(AdminPanel::SLUG,'Radar comercial','Radar comercial',AdminPanel::CAPABILITY,self::SLUG,[self::class,'render']);
    }
    private static function guard(): void
    {
        if (!current_user_can(AdminPanel::CAPABILITY)) { wp_die('Acceso no autorizado.','',['response'=>403]); }
    }
    private static function post(string $action): void
    {
        self::guard();
        if (($_SERVER['REQUEST_METHOD']??'')!=='POST') { wp_die('Método no permitido.','',['response'=>405]); }
        check_admin_referer($action,'bk_alert_nonce');
    }
    private static function key(): string { return 'bk_alert_view_'.get_current_user_id(); }
    private static function redirect(string $notice): void
    {
        wp_safe_redirect(add_query_arg(['page'=>self::SLUG,'bk_alert_notice'=>$notice],admin_url('admin.php')));
        exit;
    }
    private static function param(string $key): string
    {
        return isset($_GET[$key]) && is_string($_GET[$key])?sanitize_text_field(wp_unslash($_GET[$key])):'';
    }
    public static function upload(): void
    {
        self::post(self::LOAD);
        try {
            $f=$_FILES['snapshot']??null;
            if (!is_array($f) || ($f['error']??null)!==UPLOAD_ERR_OK || !is_string($f['tmp_name']??null)
                || !is_uploaded_file($f['tmp_name']) || !is_int($f['size']??null) || $f['size']>AlertDashboardSnapshot::MAX_BYTES) {
                throw new \InvalidArgumentException('Invalid upload.');
            }
            $raw=file_get_contents($f['tmp_name'],false,null,0,AlertDashboardSnapshot::MAX_BYTES+1);
            if (!is_string($raw)) { throw new \InvalidArgumentException('Invalid upload.'); }
            AlertDashboardSnapshot::decode($raw,time());
            set_transient(self::key(),$raw,15*MINUTE_IN_SECONDS);
            if (get_transient(self::key())!==$raw) { throw new \RuntimeException('Cache unavailable.'); }
        } catch (\Throwable $e) { self::redirect('invalid'); }
        self::redirect('loaded');
    }
    public static function clear(): void
    {
        self::post(self::CLEAR); delete_transient(self::key()); self::redirect('cleared');
    }
    private static function field(mixed $v): string { return $v===null?'Desconocido':(string)$v; }
    public static function render(): void
    {
        self::guard();
        $data=null; $raw=get_transient(self::key());
        if (is_string($raw)) {
            try { $data=AlertDashboardSnapshot::decode($raw,time()); } catch (\Throwable $e) { $data=null; }
        }
        echo '<div class="wrap"><h1>Radar comercial</h1><p>Bandeja histórica de alertas archivadas. Solo lectura; sin consultas a proveedor, notificaciones o cambios comerciales.</p>';
        $notices=['loaded'=>'Vista de alertas cargada.','invalid'=>'Archivo inválido o caché no disponible.','cleared'=>'Vista de alertas eliminada.'];
        $notice=self::param('bk_alert_notice');
        if (isset($notices[$notice])) { echo '<div class="notice notice-info" role="status"><p>'.esc_html($notices[$notice]).'</p></div>'; }
        echo '<form method="post" enctype="multipart/form-data" action="'.esc_url(admin_url('admin-post.php')).'"><input type="hidden" name="action" value="'.esc_attr(self::LOAD).'">';
        wp_nonce_field(self::LOAD,'bk_alert_nonce',false);
        echo '<label for="bk-alert-file">Exportación JSON (máximo 256 KiB)</label> <input id="bk-alert-file" name="snapshot" type="file" accept=".json,application/json" required> ';
        submit_button('Cargar alertas','primary','bk_alert_load',false);
        echo '</form><p>Vista individual temporal de 15 minutos. No se autentica el origen del archivo.</p>';
        if ($data===null) { echo '<h2>Sin alertas cargadas</h2></div>'; return; }
        echo '<form method="post" action="'.esc_url(admin_url('admin-post.php')).'"><input type="hidden" name="action" value="'.esc_attr(self::CLEAR).'">';
        wp_nonce_field(self::CLEAR,'bk_alert_nonce',false);
        submit_button('Eliminar vista','secondary','bk_alert_clear',false);
        echo '</form><h2>Resumen de esta página</h2><p>Archivo: '.esc_html($data['archive_ref']).' · Tienda: '.esc_html($data['store_id']).' · Exportado UTC: '.esc_html($data['exported_at']).' · Umbral: '.esc_html(number_format($data['price_threshold_bps']/100,2,',','.')).'%</p>';
        if (time()-strtotime($data['exported_at'])>86400) { echo '<p class="notice notice-warning">Exportación antigua: los estados pueden haber cambiado.</p>'; }
        echo '<p>Total de esta página: <strong>'.esc_html((string)count($data['rows'])).'</strong>';
        foreach (AlertDashboardSnapshot::STATES as $state=>$label) { echo ' · '.esc_html($label).': <strong>'.esc_html((string)$data['counts'][$state]).'</strong>'; }
        echo '</p>';
        if ($data['next_after']!==null) { echo '<p>Hay otra página de archivo. Cursor para exportación offline: <code>'.esc_html($data['next_after']).'</code></p>'; }
        $state=self::param('bk_state'); $priority=self::param('bk_priority'); $query=substr(self::param('bk_q'),0,120);
        if (!isset(AlertDashboardSnapshot::STATES[$state])) { $state=''; }
        if (!isset(AlertDashboardSnapshot::PRIORITIES[$priority])) { $priority=''; }
        echo '<form method="get" action="'.esc_url(admin_url('admin.php')).'"><input type="hidden" name="page" value="'.esc_attr(self::SLUG).'">';
        echo '<label for="bk-alert-query">Buscar producto o SKU</label> <input id="bk-alert-query" name="bk_q" maxlength="120" value="'.esc_attr($query).'"> ';
        foreach (['bk_state'=>['Estado',AlertDashboardSnapshot::STATES,$state],'bk_priority'=>['Prioridad',AlertDashboardSnapshot::PRIORITIES,$priority]] as $name=>$v) {
            echo '<label for="'.esc_attr($name).'">'.esc_html($v[0]).'</label> <select id="'.esc_attr($name).'" name="'.esc_attr($name).'"><option value="">Todas</option>';
            foreach ($v[1] as $k=>$label) { echo '<option value="'.esc_attr($k).'"'.selected($v[2],$k,false).'>'.esc_html($label).'</option>'; }
            echo '</select> ';
        }
        submit_button('Filtrar alertas','secondary','bk_alert_filter',false);
        echo '</form><h2>Alertas observadas</h2><div style="overflow-x:auto"><table class="widefat striped"><thead><tr><th scope="col">Producto</th><th scope="col">Señal</th><th scope="col">Prioridad</th><th scope="col">Estado archivado</th><th scope="col">Evidencia</th></tr></thead><tbody>';
        $rows=AlertDashboardSnapshot::filter($data['rows'],$state,$priority,$query);
        foreach ($rows as $r) {
            echo '<tr><td><strong>'.esc_html($r['title']).'</strong><br>ID: '.esc_html($r['external_id']).' · SKU: '.esc_html($r['sku']).'</td><td>'.esc_html(AlertDashboardSnapshot::CODES[$r['code']]);
            if ($r['field']!==null) {
                $labels=['sku'=>'SKU','type'=>'Tipo','warehouse'=>'Bodega','base_price'=>'Precio base reportado','suggested_price'=>'Precio sugerido reportado','simple_stock'=>'Stock simple reportado'];
                echo '<br>'.esc_html($labels[$r['field']]).': '.esc_html(self::field($r['previous'])).' → '.esc_html(self::field($r['current']));
            }
            if ($r['change_pct']!==null) { echo '<br>'.esc_html($r['change_pct']).'%'; }
            echo '</td><td>'.esc_html(AlertDashboardSnapshot::PRIORITIES[$r['priority']]).'</td><td>'.esc_html(AlertDashboardSnapshot::STATES[$r['state']]).'</td>';
            echo '<td><details><summary>Ver procedencia</summary><p>Captura UTC: '.esc_html($r['captured_at']).'<br>Anterior: '.esc_html(self::field($r['previous_at'])).'<br>Primera detección: '.esc_html($r['first_seen']).'</p><p>ID: <code>'.esc_html($r['signal_id']).'</code><br>Alerta SHA-256: <code>'.esc_html($r['alert_sha256']).'</code><br>Último evento: <code>'.esc_html($r['latest_event_sha256']).'</code></p>';
            foreach (['current_pages'=>'Páginas actuales','previous_pages'=>'Páginas anteriores'] as $k=>$label) {
                echo '<p>'.esc_html($label).'</p><ul>';
                foreach ($r[$k] as $sha) { echo '<li><code>'.esc_html($sha).'</code></li>'; }
                echo '</ul>';
            }
            echo '</details></td></tr>';
        }
        if (!$rows) { echo '<tr><td colspan="5">No hay alertas para estos filtros.</td></tr>'; }
        echo '</tbody></table></div><p>Los recuentos corresponden solo a la página cargada. Resolver una alerta no certifica disponibilidad ni rentabilidad. Los precios reportados no son costos verificados.</p></div>';
    }
}
