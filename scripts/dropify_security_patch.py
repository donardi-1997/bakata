"""Additional source transformations for the exact audited Dropify archive."""
import re


def one(source, old, new):
    if source.count(old) != 1:
        raise ValueError("Unexpected source: " + old[:70])
    return source.replace(old, new)


def patch_security(name, source):
    if name == 'clasess/models/TokenModel.php':
        for field, variable, fmt in [('token', 'token', '%s'), ('store', 'store', '%s'), ('id', 'id', '%d')]:
            pattern = r'\$wpdb->get_results\(\s*"SELECT \* FROM " \. \$this->table_name \. " WHERE ' + field + r""" = '" \. \$""" + variable + r""" \. "'" ?,\s*OBJECT\s*\)"""
            replacement = f'$wpdb->get_results($wpdb->prepare("SELECT * FROM " . $this->table_name . " WHERE {field} = {fmt}", ${variable}), OBJECT)'
            source, count = re.subn(pattern, lambda _: replacement, source)
            if count != 1:
                raise ValueError("Unexpected token lookup: " + field)
        source = one(source, '$wpdb->insert($this->table_name, array(', 'return $wpdb->insert($this->table_name, array(')
        source = one(source, '$listProducts[$i]->store = $store;', "$listProducts[$i]->store = (object) array('id' => $store->id, 'store' => $store->store);")
        source = one(source, '$token = $this->getTokenById($id)[0]->token;', '''$rows = $this->getTokenById($id);
        if (empty($rows)) {
            return false;
        }
        $token = $rows[0]->token;''')
        source = one(source, '''$wpdb->get_results("SELECT post_id FROM $wpdb->postmeta WHERE meta_value = '" . $token . "'", OBJECT)''', '''$wpdb->get_results($wpdb->prepare("SELECT post_id FROM $wpdb->postmeta WHERE meta_key = %s AND meta_value = %s", '_dropi_token', $token), OBJECT)''')
    if name == 'clasess/tables/TokenTable.php':
        start = source.index("        $last_token = isset($_GET['token'])")
        end = source.index("        $columns = $this->get_columns();", start)
        source = source[:start] + source[end:]
        source = one(source, 'return $item[$column_name];', "return $column_name === 'token' ? '••••••••' : esc_html((string) ($item[$column_name] ?? ''));")
        source = one(source, ''' data-item='" . json_encode($item) . "' ''', ' ')
        source = one(source, "if ('delete' === $this->current_action()) {", """if ('delete' === $this->current_action()) {
            if (!current_user_can('manage_options')) {
                wp_die('Forbidden', '', array('response' => 403));
            }""")
    if name == 'clasess/views/settings.php':
        source = one(source, '<form method="post" action="options.php">', '<form method="post" action="<?php echo esc_url(admin_url(\'admin.php?page=dropi-settings\')); ?>">')
        source = one(source, "<?php settings_fields('dropi-woocomerce-settings'); ?>", "<?php wp_nonce_field('bakata_dropi_add_token'); ?>\n                <input type=\"hidden\" name=\"bakata_dropi_add_token\" value=\"1\" />")
        source = one(source, "<?php do_settings_sections('dropi-woocomerce-settings'); ?>", '')
        source = one(source, 'type="text" name="dropi-woocomerce-token" id="token"', 'type="password" autocomplete="new-password" name="bakata_token" id="token"')
        source = one(source, '''<!-- value="<?php echo esc_attr(get_option('dropi-woocomerce-token')); ?>"-->''', '')
        source = one(source, 'name="dropi-woocomerce-token" id="token-name"', 'name="bakata_store" id="token-name"')
        source, count = re.subn(r'<a href="javascript:void\(0\)" class="button"\s+onclick="window\.location\.href=.*?\n\s+Guardar Token </a>', '<button type="submit" class="button">Guardar Token</button>', source)
        if count != 1:
            raise ValueError("Unexpected token form")
    if name == 'clasess/Settings.php':
        source = one(source, 'public function settings_screen_option(){', '''public function settings_screen_option(){
        if (isset($_POST['bakata_dropi_add_token'])) {
            if (!current_user_can('manage_options')) {
                wp_die('Forbidden', '', array('response' => 403));
            }
            check_admin_referer('bakata_dropi_add_token');
            $token = isset($_POST['bakata_token']) && is_string($_POST['bakata_token']) ? wp_unslash($_POST['bakata_token']) : '';
            $store = isset($_POST['bakata_store']) && is_string($_POST['bakata_store']) ? sanitize_text_field(wp_unslash($_POST['bakata_store'])) : '';
            if ($token === '' || strlen($token) > 1000 || preg_match('/[\\x00-\\x20\\x7f]/', $token)
                || $store === '' || strlen($store) > 190) {
                wp_die('Invalid token or store', '', array('response' => 400));
            }
            if (empty($this->SettingsInstance->does_token_exist($token))) {
                $constants = JPIODFW_Constants::GetInstance();
                if ($this->SettingsInstance->setNewToken($token, $store, $constants->SINC_MANUAL, 0) !== 1) {
                    wp_die('Token could not be stored', '', array('response' => 500));
                }
            }
            wp_safe_redirect(admin_url('admin.php?page=dropi-settings'));
            exit;
        }''')
    if name == 'clasess/models/OrdersModel.php':
        source = one(source, '''                $response = wp_remote_post(
                    $endpoint,
                    $args
                );''', '''                // Reserve once, durably, before the first outbound order request.
                // Never release automatically: a timeout may have created a remote order.
                if (!bakata_dropify_reserve_dispatch($order, $id_token)) {
                    return 'Dropi dispatch blocked; manual reconciliation required';
                }
                $response = wp_remote_post(
                    $endpoint,
                    $args
                );''')
        source = one(source, 'class JPIODFW_OrdersModel', '''function bakata_dropify_reserve_dispatch($order, $token)
{
    global $wpdb;
    if (!is_string($token) || trim($token) === '' || !($order instanceof WC_Order)) {
        return false;
    }
    $id = $order->get_id();
    $fresh = wc_get_order($id);
    if (!$fresh || $id <= 0) {
        return false;
    }
    $fresh->read_meta_data(true);
    if ($fresh->get_meta('_dropi_order_id') !== '' || $fresh->get_meta('_is_dropi_order') !== '') {
        return false;
    }
    // wp_options has a unique option_name index. INSERT (not add_option/upsert)
    // ensures exactly one successful claimant under concurrent requests.
    $previous = $wpdb->suppress_errors(true);
    try {
        return $wpdb->insert($wpdb->options, array(
            'option_name' => 'bakata_dropify_dispatch_' . $id,
            'option_value' => 'attempted',
            'autoload' => 'no',
        ), array('%s', '%s', '%s')) === 1;
    } finally {
        $wpdb->suppress_errors($previous);
    }
}

class JPIODFW_OrdersModel''')
        source = one(source, "'timeout' => '100000',", "'timeout' => 30,")
        source = one(source, " __('Dropi sync error: ' . $error_message, 'wc-dropi-integration')", " __('Dropi sync error; reconcile manually', 'wc-dropi-integration')")
        source = one(source, " __('Dropi sync error: ' . $response_body['message'], 'dropi')", " __('Dropi sync error; reconcile manually', 'wc-dropi-integration')")
        source = one(source, "$result = __('Error creating order, ' . $message);", "$result = __('Dropi dispatch result uncertain; reconcile manually', 'wc-dropi-integration');")
    return source
