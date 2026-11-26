<?php
function bakata_dropify_reserve_dispatch($order, $token)
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
