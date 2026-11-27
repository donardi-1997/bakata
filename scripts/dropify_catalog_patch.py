"""Additional transformations for the hash-pinned, read-only catalog validation build."""
from pathlib import Path
from dropify_security_patch import one


def patch_catalog(name, source):
    if name == "wc-dropi-integration.php":
        source = one(source, "register_activation_hook(__FILE__, 'create_dropi_tokens_table');",
                     "// Catalog validation build requires existing token table; no activation migration.")
        source = one(source, """    $Dropi = JPIODFW_Dropi::GetInstance();
    $Dropi->InitPlugin();""", """    if (is_admin() && class_exists('WooCommerce')) {
        JPIODFW_Products::GetInstance()->init();
    }""")
    if name == "clasess/views/Products.php":
        start = source.index("    public function getProducts($product_list)")
        helper = (Path(__file__).resolve().parent.parent / "tools/dropify-quarantine/catalog-bridge.php").read_text().removeprefix("<?php\n")
        source = source[:start] + """    public function getProducts($product_list)
    {
        bakata_catalog_render($product_list);
    }
}
""" + helper
    if name == "clasess/Products.php":
        source = one(source, "        add_action('admin_enqueue_scripts', array(&$this, 'my_load_scripts'));",
                     "        // Catalog validation build: no import scripts or external CDN.")
        source = one(source, "        add_action('wp_ajax_import', array(&$this, 'my_import_product_event'));",
                     "        // Catalog validation build: no import endpoint.")
        source = one(source, "        add_action('wp_ajax_get-woo-products', array(&$this, 'my_get_woo_products_cb2'));",
                     "        // Catalog validation build: no WooCommerce product endpoint.")
        source = one(source, "        add_filter('manage_edit-product_columns', array($this, 'custom_shop_product_column'), 20);",
                     "        // Catalog validation build: no storefront product hooks.")
        source = one(source, "        add_action('manage_product_posts_custom_column', array($this, 'show_custom_product_column_values'), 20, 2);",
                     "        // Catalog validation build: no storefront product hooks.")
        source = one(source, "        $this->helper->checkRequirementes();", "        // No token-table migration or product metadata updates.")
        source = one(source, """        $hook = add_submenu_page(
            'dropi',
            'Productos',
            'Productos',""", """        $hook = add_menu_page(
            'Dropify — Catálogo de investigación',
            'Dropify',""")
    if name == "clasess/models/ProductsModel.php":
        start = source.index("    public function getProducts(")
        end = source.index("    /** get product by sku", start)
        method = source[start:end]
        method = one(method, "        $products = [];", """        if (!defined('BAKATA_DROPIFY_CATALOG_READ') || BAKATA_DROPIFY_CATALOG_READ !== true
            || !in_array(wp_get_environment_type(), array('development','staging'), true)
            || !current_user_can('manage_options')
            || ($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST'
            || !isset($_POST['bk_catalog_read']) || !isset($_POST['_wpnonce'])
            || !is_string($_POST['_wpnonce'])
            || !wp_verify_nonce(wp_unslash($_POST['_wpnonce']), 'bk_catalog_read')
            || !is_int($per_page) || $per_page < 1 || $per_page > 20
            || !is_int($current_page) || $current_page < 0 || $current_page > 1980
            || !is_string($search) || strlen($search) > 120
            || $orderby !== 'id' || $order !== 'asc'
            || !is_string($store_filter) || !preg_match('/^[1-9][0-9]{0,9}$/D',$store_filter)) {
            return null;
        }
        // One attempt per explicit operator approval, scoped to store, offset and query.
        // Never delete or retry an uncertain receipt.
        if (!defined('BAKATA_DROPIFY_CATALOG_APPROVAL_REF')
            || !is_string(BAKATA_DROPIFY_CATALOG_APPROVAL_REF)
            || !preg_match('/^[A-Za-z0-9._-]{1,128}$/D', BAKATA_DROPIFY_CATALOG_APPROVAL_REF)
            || !defined('BAKATA_DROPIFY_CATALOG_APPROVED_UNTIL')
            || !is_int(BAKATA_DROPIFY_CATALOG_APPROVED_UNTIL)
            || BAKATA_DROPIFY_CATALOG_APPROVED_UNTIL <= time()
            || BAKATA_DROPIFY_CATALOG_APPROVED_UNTIL > time()+86400
            || !defined('BAKATA_DROPIFY_CATALOG_APPROVED_STORE')
            || BAKATA_DROPIFY_CATALOG_APPROVED_STORE !== $store_filter
            || !defined('BAKATA_DROPIFY_CATALOG_APPROVED_OFFSET')
            || BAKATA_DROPIFY_CATALOG_APPROVED_OFFSET !== $current_page
            || !defined('BAKATA_DROPIFY_CATALOG_APPROVED_QUERY')
            || BAKATA_DROPIFY_CATALOG_APPROVED_QUERY !== $search
            || $per_page !== 10 || $onlyVerifiedUsers !== null || $filter_have_stock !== null
            || $filter_have_description !== null || $category_filter !== null || $warehouses_filter !== null) {
            return null;
        }
        $products = [];""")
        method = one(method, "            $token = $token[0];", """            if (!is_array($token) || count($token) !== 1) { return null; }
            $token = reset($token);""")
        method = one(method, "        $all_products = array();", """        if (!is_object($token) || !isset($token->id, $token->token)
            || (string)$token->id !== $store_filter || !is_string($token->token) || $token->token === '') {
            return null;
        }
        $all_products = array();""")
        method = one(method, "'timeout' => '100000',", "'timeout' => 15,\n            'limit_response_size' => 524288,")
        method = one(method, "        $response = wp_remote_post(", """        $receipt = 'bk_dropify_catalog_' . hash('sha256', BAKATA_DROPIFY_CATALOG_APPROVAL_REF);
        if (!add_option($receipt, array('store'=>$store_filter,'offset'=>$current_page,'at'=>gmdate(DATE_ATOM)), '', false)) {
            return null;
        }
        $response = wp_remote_post(""")
        # Reuse the original connector request; do not expose errors, bodies or token.
        cut = method.index("        if (is_wp_error($response))", method.index("$response = wp_remote_post("))
        method = method[:cut] + """        if (is_wp_error($response) || wp_remote_retrieve_response_code($response) !== 200) {
            return null;
        }
        $body = wp_remote_retrieve_body($response);
        if (!is_string($body) || strlen($body) > 524288) { return null; }
        $decoded = json_decode($body, false, 32, JSON_BIGINT_AS_STRING);
        if (!is_object($decoded) || ($decoded->isSuccess ?? false) !== true
            || !isset($decoded->objects) || !is_array($decoded->objects)
            || count($decoded->objects) > $per_page) {
            return null;
        }
        foreach ($decoded->objects as $item) {
            if (!is_object($item)) { return null; }
        }
        return array('objects'=>$this->TokenModel->assignStoreName($decoded->objects, $token));
    }

"""
        source = source[:start] + method + source[end:]
        start = source.index("    public function import_product(")
        brace = source.index("{", start)
        source = source[:brace+1] + "\n        // Catalog validation build: even direct callers cannot import.\n        return array('success'=>false,'message'=>'Import disabled in catalog validation build');\n" + source[brace+1:]
    return source
