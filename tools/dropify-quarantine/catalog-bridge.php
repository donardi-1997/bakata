<?php
// Injected only into the hash-pinned catalog validation build.
function bakata_catalog_offset($page, $size)
{
    if (!is_int($page) || $page < 1 || $page > 100 || !is_int($size) || $size < 1 || $size > 20) {
        throw new InvalidArgumentException('Invalid catalog page.');
    }
    return ($page - 1) * $size;
}

function bakata_catalog_text($value, $limit = 300)
{
    if (!is_string($value) && !is_int($value)) { return ''; }
    $value = trim((string) $value);
    if (strlen($value) > $limit || preg_match('/[\x00-\x1f\x7f]/', $value)
        || !preg_match('//u', $value)) { return ''; }
    return $value;
}

function bakata_catalog_decimal($value)
{
    // Preserve exact decimal strings; JSON floats are deliberately unknown.
    $value = is_int($value) ? (string) $value : $value;
    return is_string($value) && preg_match('/\A(?:0|[1-9][0-9]{0,9})(?:\.[0-9]{1,2})?\z/D', $value)
        ? $value : null;
}

function bakata_catalog_project($items, $storeId, $page, $size, $approvalRef, $query)
{
    $offset = bakata_catalog_offset($page, $size);
    if (!is_string($approvalRef) || !preg_match('/\\A[A-Za-z0-9._-]{1,128}\\z/D',$approvalRef)
        || !is_string($query) || strlen($query)>120) { throw new InvalidArgumentException('Invalid capture provenance.'); }
    if (!is_string($storeId) || !preg_match('/\A[1-9][0-9]{0,9}\z/D', $storeId)
        || !is_array($items) || count($items) > $size) {
        throw new InvalidArgumentException('Invalid catalog response.');
    }
    $rows = array();
    $seen = array();
    foreach ($items as $item) {
        if (!is_object($item)) { throw new InvalidArgumentException('Invalid catalog item.'); }
        $id = bakata_catalog_text($item->id ?? null, 30);
        $title = bakata_catalog_text($item->name ?? null);
        if (!preg_match('/\A[1-9][0-9]{0,29}\z/D', $id) || $title === '' || isset($seen[$id])
            || !isset($item->store->id) || (string)$item->store->id !== $storeId) {
            throw new InvalidArgumentException('Missing or duplicate catalog identity.');
        }
        $seen[$id] = true;
        $type = ($item->type ?? '') === 'SIMPLE' ? 'simple' : 'unresolved';
        $stock = null;
        if ($type === 'simple' && !isset($item->warehouse_product)) {
            $raw = $item->stock ?? null;
            if (is_int($raw) || (is_string($raw) && preg_match('/\A(?:0|[1-9][0-9]{0,6})\z/D', $raw))) {
                if ((int)$raw >= 0 && (int)$raw <= 1000000) { $stock = (int)$raw; }
            }
        }
        $categories = array();
        if (isset($item->categories) && is_array($item->categories)) {
            foreach (array_slice($item->categories, 0, 20) as $category) {
                $label = bakata_catalog_text($category->name ?? null, 100);
                if ($label !== '') { $categories[] = $label; }
            }
        }
        $rows[] = array('external_id'=>$id, 'sku'=>bakata_catalog_text($item->sku ?? null,128),
            'title'=>$title, 'type'=>$type, 'base_price'=>bakata_catalog_decimal($item->sale_price ?? null),
            'suggested_price'=>bakata_catalog_decimal($item->suggested_price ?? null),
            'simple_stock'=>$stock, 'categories'=>array_values(array_unique($categories)),
            'warehouse'=>bakata_catalog_text($item->user->name ?? null,150));
    }
    return array('schema'=>'bakata-dropify-bridge-v1', 'captured_at'=>gmdate('Y-m-d\TH:i:s\Z'),
        'store_id'=>$storeId, 'page'=>$page, 'page_size'=>$size, 'offset'=>$offset,
        'approval_ref'=>$approvalRef, 'query_sha256'=>hash('sha256',$query),
        'possible_next'=>count($rows)===$size, 'rows'=>$rows);
}

function bakata_catalog_read_enabled()
{
    return defined('BAKATA_DROPIFY_CATALOG_READ') && BAKATA_DROPIFY_CATALOG_READ === true
        && in_array(wp_get_environment_type(), array('development','staging'), true);
}

function bakata_catalog_render($list)
{
    if (!current_user_can('manage_options')) { wp_die('Forbidden', '', array('response'=>403)); }
    if (!bakata_catalog_read_enabled()) {
        echo '<div class="wrap"><h1>Dropify — Catálogo de investigación</h1><p>Consulta deshabilitada. Requiere autorización y configuración explícita del entorno de pruebas.</p></div>';
        return;
    }
    $store = '';
    $page = 1;
    $query = '';
    $result = null;
    $error = false;
    // A visit, refresh of a GET page or rendering the form never fetches the catalog.
    if (($_SERVER['REQUEST_METHOD'] ?? '') === 'POST' && isset($_POST['bk_catalog_read'])) {
        check_admin_referer('bk_catalog_read');
        $store = isset($_POST['bk_store']) && is_string($_POST['bk_store']) ? wp_unslash($_POST['bk_store']) : '';
        $rawPage = isset($_POST['bk_page']) && is_string($_POST['bk_page']) ? wp_unslash($_POST['bk_page']) : '';
        $query = isset($_POST['bk_query']) && is_string($_POST['bk_query']) ? sanitize_text_field(wp_unslash($_POST['bk_query'])) : '';
        try {
            if (!preg_match('/\A[1-9][0-9]{0,9}\z/D', $store)
                || !preg_match('/\A[1-9][0-9]{0,2}\z/D', $rawPage) || strlen($query)>120) {
                throw new InvalidArgumentException('Invalid catalog filters.');
            }
            $page=(int)$rawPage;
            $size=10;
            $offset=bakata_catalog_offset($page,$size);
            $known=array_filter(is_array($list->tokens) ? $list->tokens : array(), static function ($entry) use ($store) {
                return isset($entry->id) && (string)$entry->id===$store;
            });
            if (count($known)!==1) { throw new InvalidArgumentException('Choose one configured store.'); }
            $response=$list->ProducstInstance->getProducts($size,$offset,$query,'id','asc',
                null,null,null,null,null,$store,$list->tokens);
            if (!is_array($response) || !isset($response['objects'])) {
                throw new RuntimeException('Catalog unavailable.');
            }
            $result=bakata_catalog_project($response['objects'],$store,$page,$size,BAKATA_DROPIFY_CATALOG_APPROVAL_REF,$query);
        } catch (Throwable $e) {
            $error=true;
            $result=null;
        }
    }
    echo '<div class="wrap"><h1>Dropify — Catálogo de investigación</h1>';
    echo '<p>Versión de validación: solo lectura. Sin total confirmado, importación ni despacho.</p>';
    echo '<form method="post" action="' . esc_url(admin_url('admin.php?page=dropi-products')) . '">';
    wp_nonce_field('bk_catalog_read');
    echo '<input type="hidden" name="bk_catalog_read" value="1"><label for="bk-store">Tienda</label> <select name="bk_store" id="bk-store" required><option value="">Seleccionar</option>';
    foreach (is_array($list->tokens) ? $list->tokens : array() as $entry) {
        $id=bakata_catalog_text($entry->id ?? null,10);
        if (!preg_match('/\A[1-9][0-9]{0,9}\z/D',$id)) { continue; }
        echo '<option value="'.esc_attr($id).'"'.selected($store,$id,false).'>'.esc_html(bakata_catalog_text($entry->store ?? null,190)).'</option>';
    }
    echo '</select> <label for="bk-query">Buscar</label> <input id="bk-query" name="bk_query" maxlength="120" value="'.esc_attr($query).'">';
    echo ' <label for="bk-page">Página</label> <input type="number" id="bk-page" name="bk_page" min="1" max="100" value="'.esc_attr((string)$page).'" required>';
    submit_button('Consultar una página autorizada','primary','bk_submit',false);
    echo '</form>';
    if ($error) { echo '<p role="alert">Consulta bloqueada o fallida. Revisar manualmente; no reintentar automáticamente.</p>'; }
    if ($result !== null) {
        echo '<p>'.esc_html((string)count($result['rows'])).' filas. '.($result['possible_next'] ? 'Puede existir otra página; no se confirma el total.' : 'Página parcial o vacía; no certifica cobertura.').'</p>';
        echo '<table class="widefat striped"><thead><tr><th>ID</th><th>SKU</th><th>Nombre</th><th>Precio base</th><th>Precio sugerido</th><th>Stock simple</th></tr></thead><tbody>';
        foreach ($result['rows'] as $row) {
            echo '<tr>';
            foreach (array('external_id','sku','title','base_price','suggested_price','simple_stock') as $field) {
                echo '<td>'.esc_html($row[$field]===null?'Desconocido':(string)$row[$field]).'</td>';
            }
            echo '</tr>';
        }
        echo '</tbody></table><p>Valores sin certificar moneda, costo final ni disponibilidad vendible.</p>';
        $json=wp_json_encode($result,JSON_UNESCAPED_UNICODE);
        if (is_string($json) && strlen($json)<=262144) {
            echo '<label for="bk-catalog-json">Snapshot para archivo offline (copiar y guardar como JSON)</label>';
            echo '<textarea id="bk-catalog-json" readonly rows="8" class="large-text code">'.esc_textarea($json).'</textarea>';
        }
    }
    echo '</div>';
}
