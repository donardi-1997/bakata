<?php
declare(strict_types=1);
namespace Bakata\Core\Intelligence;

final class CatalogReviewPanel
{
    private const SLUG='bakata-catalog-review';
    public static function register(): void
    {
        add_action('admin_menu',[self::class,'menu'],20);
        add_action('admin_post_bakata_catalog_review_load',[self::class,'upload']);
        add_action('admin_post_bakata_catalog_review_clear',[self::class,'clear']);
    }

    public static function menu(): void
    {
        add_submenu_page(AdminPanel::SLUG,'Revisión de catálogo','Revisión de catálogo',AdminPanel::CAPABILITY,self::SLUG,[self::class,'render']);
    }

    private static function guard(): void
    {
        if (!current_user_can(AdminPanel::CAPABILITY)) { wp_die('Acceso no autorizado.','',['response'=>403]); }
    }

    private static function key(): string { return 'bk_catalog_review_'.get_current_user_id(); }

    private static function redirect(string $notice): void
    {
        wp_safe_redirect(add_query_arg(['page'=>self::SLUG,'bk_catalog_notice'=>$notice],admin_url('admin.php')));
        exit;
    }

    private static function post(string $action): void
    {
        self::guard();
        if (($_SERVER['REQUEST_METHOD']??'')!=='POST') { wp_die('Método no permitido.','',['response'=>405]); }
        check_admin_referer($action,'bk_catalog_nonce');
    }

    public static function upload(): void
    {
        self::post('bakata_catalog_review_load');
        try {
            $file=$_FILES['snapshot']??null;
            if (!is_array($file) || ($file['error']??null)!==UPLOAD_ERR_OK || !is_string($file['tmp_name']??null)
                || !is_uploaded_file($file['tmp_name']) || !is_int($file['size']??null)
                || $file['size']>CatalogReviewSnapshot::MAX_BYTES) { throw new \InvalidArgumentException('Invalid upload.'); }
            $raw=file_get_contents($file['tmp_name'],false,null,0,CatalogReviewSnapshot::MAX_BYTES+1);
            if (!is_string($raw)) { throw new \InvalidArgumentException('Invalid upload.'); }
            CatalogReviewSnapshot::decode($raw,time());
            set_transient(self::key(),$raw,15*MINUTE_IN_SECONDS);
            if (get_transient(self::key())!==$raw) { throw new \RuntimeException('Cache unavailable.'); }
        } catch (\Throwable $e) { self::redirect('invalid'); }
        self::redirect('loaded');
    }

    public static function clear(): void
    {
        self::post('bakata_catalog_review_clear');
        delete_transient(self::key());
        self::redirect('cleared');
    }

    private static function param(string $key): string
    {
        return isset($_GET[$key]) && is_string($_GET[$key])?sanitize_text_field(wp_unslash($_GET[$key])):'';
    }

    public static function render(): void
    {
        self::guard();
        $data=null;
        $raw=get_transient(self::key());
        if (is_string($raw)) {
            try { $data=CatalogReviewSnapshot::decode($raw,time()); } catch (\Throwable $e) { $data=null; }
        }
        $labels=['positive'=>'Stock reportado positivo','zero'=>'Cero reportado','unknown'=>'Desconocido'];
        $notices=['loaded'=>'Vista de catálogo cargada.','invalid'=>'Archivo inválido o caché no disponible.','cleared'=>'Vista de catálogo eliminada.'];
        echo '<div class="wrap"><h1>Revisión de catálogo</h1><p>Exploración offline de una página archivada. Sin consulta al proveedor, aprobación, importación ni publicación.</p>';
        $notice=self::param('bk_catalog_notice');
        if (isset($notices[$notice])) { echo '<div class="notice notice-info" role="status"><p>'.esc_html($notices[$notice]).'</p></div>'; }
        echo '<form method="post" enctype="multipart/form-data" action="'.esc_url(admin_url('admin-post.php')).'">';
        echo '<input type="hidden" name="action" value="bakata_catalog_review_load">';
        wp_nonce_field('bakata_catalog_review_load','bk_catalog_nonce',false);
        echo '<label for="bk-catalog-file">Exportación archivada JSON (máximo 256 KiB)</label> <input id="bk-catalog-file" name="snapshot" type="file" accept=".json,application/json" required> ';
        submit_button('Cargar catálogo','primary','bk_catalog_load',false);
        echo '</form><p>Vista individual durante 15 minutos. El archivo no se publica ni se incorpora a la biblioteca multimedia.</p>';
        if ($data===null) { echo '<h2>Sin catálogo cargado</h2><p>Usa la exportación offline del archivo BridgeArchive.</p></div>'; return; }
        $s=$data['snapshot'];
        $at=strtotime($s['captured_at']);
        $age=time()-$at;
        $fresh=$age>=0 && $age<=86400;
        echo '<form method="post" action="'.esc_url(admin_url('admin-post.php')).'"><input type="hidden" name="action" value="bakata_catalog_review_clear">';
        wp_nonce_field('bakata_catalog_review_clear','bk_catalog_nonce',false);
        submit_button('Eliminar vista de catálogo','secondary','bk_catalog_clear',false);
        echo '</form><h2>Captura archivada</h2><p>Tienda local: <strong>'.esc_html($s['store_id']).'</strong> · Página '.esc_html((string)$s['page']).' · Offset '.esc_html((string)$s['offset']).' · UTC: '.esc_html($s['captured_at']).'</p>';
        echo '<p role="status">'.esc_html($fresh?'Captura dentro de 24 horas; no certifica disponibilidad actual.':'Captura antigua o con reloj adelantado; requiere revisión antes de uso comercial.').'</p>';
        echo '<details><summary>Procedencia declarada</summary><p>SHA-256 original archivado: <code>'.esc_html($data['source_page_sha256']).'</code><br>Operador: '.esc_html($data['operator_ref']).'<br>Referencia de aprobación: '.esc_html($s['approval_ref']).'<br>Digest de búsqueda: <code>'.esc_html($s['query_sha256']).'</code></p><p>La carga valida formato y coherencia, no autentica el archivo ni certifica permiso o evidencia.</p></details>';
        $counts=array_fill_keys(array_keys($labels),0);
        foreach ($s['rows'] as $row) { ++$counts[CatalogReviewSnapshot::stockState($row)]; }
        echo '<p>Total de esta página: <strong>'.esc_html((string)count($s['rows'])).'</strong>';
        foreach ($labels as $state=>$label) { echo ' · '.esc_html($label).': <strong>'.esc_html((string)$counts[$state]).'</strong>'; }
        echo '</p><p>'.esc_html($s['possible_next']?'Página llena; podría existir otra.':'Página parcial o vacía. No certifica cobertura.').'</p>';
        $query=substr(self::param('bk_q'),0,120);
        $stock=self::param('bk_stock');
        if (!isset($labels[$stock])) { $stock=''; }
        echo '<form method="get" action="'.esc_url(admin_url('admin.php')).'"><input type="hidden" name="page" value="'.esc_attr(self::SLUG).'">';
        echo '<label for="bk-catalog-query">Buscar ID, SKU, nombre o categoría</label> <input id="bk-catalog-query" name="bk_q" maxlength="120" value="'.esc_attr($query).'"> ';
        echo '<label for="bk-catalog-stock">Existencias reportadas</label> <select name="bk_stock" id="bk-catalog-stock"><option value="">Todas</option>';
        foreach ($labels as $state=>$label) { echo '<option value="'.esc_attr($state).'"'.selected($stock,$state,false).'>'.esc_html($label).'</option>'; }
        echo '</select> ';
        submit_button('Filtrar catálogo','secondary','bk_catalog_filter',false);
        echo '</form><h2>Candidatos observados</h2><div style="overflow-x:auto"><table class="widefat striped"><thead><tr><th scope="col">Producto / ID / SKU</th><th scope="col">Precio base reportado</th><th scope="col">Precio sugerido reportado</th><th scope="col">Stock simple reportado</th><th scope="col">Categorías / bodega</th><th scope="col">Revisión comercial</th></tr></thead><tbody>';
        $rows=CatalogReviewSnapshot::filter($s['rows'],$query,$stock);
        foreach ($rows as $row) {
            echo '<tr><td><strong>'.esc_html($row['title']).'</strong><br>ID: '.esc_html($row['external_id']).' · SKU: '.esc_html($row['sku']).'</td>';
            foreach (['base_price','suggested_price','simple_stock'] as $field) { echo '<td>'.esc_html($row[$field]===null?'Desconocido':(string)$row[$field]).'</td>'; }
            echo '<td>'.esc_html(implode(', ',$row['categories'])).'<br>'.esc_html($row['warehouse']).'</td><td>';
            echo esc_html($row['type']!=='simple'?'Tipo por resolver':'Costo final y disponibilidad por verificar');
            echo '<br>Sin evaluación vinculada</td></tr>';
        }
        if (!$rows) { echo '<tr><td colspan="6">No hay candidatos para estos filtros.</td></tr>'; }
        echo '</tbody></table></div><p>La moneda, costo de adquisición, margen, demanda y existencias vendibles no están certificados. No se calcula rentabilidad con estos precios.</p></div>';
    }
}
