"""Read-only order list for both WooCommerce storage engines; no dispatch activation."""
from dropify_security_patch import one


def patch_hpos(name, source):
    if name == 'clasess/Woocomerce.php':
        start = source.index('    function show_custom_order_column_values(')
        end = source.index('    /**FUNCION QUE AGREGA', start)
        source = source[:start] + '''    function show_custom_order_column_values($column, $order_or_id)
    {
        $order = $order_or_id instanceof WC_Order ? $order_or_id : wc_get_order($order_or_id);
        if (!$order instanceof WC_Order || $order->get_type() !== 'shop_order') {
            return;
        }
        $keys = array('is_dropi_order' => '_is_dropi_order', 'dropi_order_id' => '_dropi_order_id', 'shipping_guide' => 'shipping_guide');
        if (!isset($keys[$column])) {
            return;
        }
        $value = $order->get_meta($keys[$column], true);
        if (!is_scalar($value)) {
            return;
        }
        if ($column === 'is_dropi_order' && $value === 'Yes') {
            echo '<span class="dashicons dashicons-yes"></span>' . esc_html__('Orden sincronizada con Dropi', 'wc-dropi-integration');
        } elseif ($column === 'is_dropi_order' && $value === '') {
            echo '<small><em>' . esc_html__('NO SYNC', 'wc-dropi-integration') . '</em></small>';
        } else {
            echo esc_html((string) $value);
        }
    }
''' + source[end:]
        source = one(source, "        add_filter('manage_edit-shop_order_columns', array($this, 'custom_shop_order_column'), 20);", """        add_filter('manage_edit-shop_order_columns', array($this, 'custom_shop_order_column'), 20);
        add_filter('manage_woocommerce_page_wc-orders_columns', array($this, 'custom_shop_order_column'), 20);
        add_action('manage_woocommerce_page_wc-orders_custom_column', array($this, 'show_custom_order_column_values'), 20, 2);""")
        # Do not expose dispatch UI or automatic hooks in the validation build.
        for line in (
            "        add_filter('woocommerce_admin_order_actions', array($this, 'add_custom_order_status_actions_button'), 100, 2);",
            "        add_action('wp_ajax_send_order_to_dropi', array($this, 'send_order_to_dropi'));",
            "        add_action('woocommerce_order_status_changed', array($this, 'woocommerce_order_status_changed'), 1);",
            "        add_filter('bulk_actions-edit-shop_order', array(&$this, 'downloads_bulk_actions_cyns_orders'), 20, 1);",
            "        add_filter('handle_bulk_actions-edit-shop_order', array($this, 'downloads_handle_bulk_action_sync_shop_order'), 10, 3);",
            "        add_action('admin_enqueue_scripts', array(&$this, 'my_load_scripts'));",
            "        add_action('admin_notices', array($this, 'downloads_bulk_action_admin_notice'));",
        ):
            source = one(source, line, '        // Disabled in read-only validation build.')
    if name == 'clasess/models/OrdersModel.php':
        source = one(source, '    public function save($order)\n    {', '''    public function save($order)
    {
        // No dispatch authorization in this build, even for direct callers.
        return 'Dropify dispatch disabled in read-only validation build';
    }

    private function save_unreleased($order)
    {''')
    return source
