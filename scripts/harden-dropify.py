#!/usr/bin/env python3
"""Build an inert, patched copy of the exact audited Dropify ZIP; never install it."""
import argparse
import hashlib
import re
import zipfile
from pathlib import Path
from dropify_security_patch import patch_security

SHA = 'bf23c6b1c5dd640aab3d38e3f370a41fbd60139ac60a1ce5f0347a059e9b6700'
ROOT = 'wc-dropi-integration/'


def replace(source, old, new, count=1):
    if source.count(old) != count:
        raise ValueError('Unexpected source pattern: ' + old[:60])
    return source.replace(old, new)


def patch(name, source):
    if name in ('clasess/Dropi.php', 'clasess/models/OrdersModel.php', 'clasess/models/ProductsModel.php'):
        count = 5 if name.endswith('ProductsModel.php') else 1
        source = replace(source, "'sslverify' => false", "'sslverify' => true", count)
        source = replace(source, "'redirection' => '5'", "'redirection' => 0", count)
    if name == 'clasess/Products.php':
        source = replace(source, 'function my_import_product_event()\n    {', '''function my_import_product_event()
    {
        if (!current_user_can('manage_options') || ($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST'
            || !check_ajax_referer('sp_import_product', '_wpnonce', false)) {
            wp_send_json_error(array('message' => 'Forbidden'), 403);
            return;
        }
        if (!isset($_REQUEST['product']) || !is_scalar($_REQUEST['product'])
            || !preg_match('/^[1-9][0-9]*$/D', (string) $_REQUEST['product'])) {
            wp_send_json_error(array('message' => 'Invalid product'), 400);
            return;
        }''')
        source = replace(source, 'function my_get_woo_products_cb2()\n    {', '''function my_get_woo_products_cb2()
    {
        if (!current_user_can('manage_options') || !check_ajax_referer('my-ajax-nonce', 'nonce', false)) {
            wp_send_json_error(array('message' => 'Forbidden'), 403);
            return;
        }''')
        for action in ('get-woo-products', 'import'):
            source, count = re.subn(r"(?m)^ *add_action\('wp_ajax_nopriv_" + action + r"',[^\n]*\n", '', source)
            if count != 1:
                raise ValueError('Unexpected anonymous hook')
        source = replace(source, '$newprod = $product->get_data();', "$newprod = array('id' => $product->get_id(), 'name' => $product->get_name(), 'sku' => $product->get_sku());")
        source = replace(source, '$newprod[\'variations\'] = $variations;', """$newprod['variations'] = array_map(static function ($variation) {
                    return array('variation_id' => $variation['variation_id'], 'attributes' => $variation['attributes']);
                }, $variations);""")
    if name == 'clasess/Woocomerce.php':
        source = replace(source, 'function send_order_to_dropi()\n    {', '''function send_order_to_dropi()
    {
        if (!current_user_can('manage_woocommerce') || !check_ajax_referer('send-order-to-dropi', '_wpnonce', false)) {
            wp_send_json_error(array('message' => 'Forbidden'), 403);
            return;
        }''')
        source, count = re.subn(r"(?m)^ *add_action\('wp_ajax_nopriv_import',[^\n]*\n", '', source)
        if count != 1:
            raise ValueError('Unexpected anonymous dispatch hook')
    if name == 'clasess/models/ProductsModel.php':
        source = replace(source, "'post_status' => 'publish',\n                'post_type' => \"product\",", "'post_status' => 'draft',\n                'post_type' => \"product\",")
    if name == 'clasess/models/OrdersModel.php':
        # Remove dynamic log payloads rather than attempting to redact arbitrary customer/provider data.
        source, count = re.subn(r'(?m)^ *\$(?:this->)?logger->(?:info|error)\([^\n]*\n', '', source)
        if count != 27:
            raise ValueError(f'Unexpected order log count: {count}')
        source = replace(source, 'echo $e->getMessage();', '')
    return patch_security(name, source)


def build(original, output):
    if hashlib.sha256(original.read_bytes()).hexdigest() != SHA:
        raise ValueError('Only the audited Dropify 4.7.3 ZIP is supported')
    if original.resolve() == output.resolve():
        raise ValueError('Output must differ from input')
    with zipfile.ZipFile(original) as src:
        entries = []
        for item in src.infolist():
            data = src.read(item)
            if item.filename.startswith(ROOT) and item.filename.endswith('.php'):
                name = item.filename[len(ROOT):]
                text = data.decode('utf-8')
                if '\r\n' in text:
                    changed = patch(name, text.replace('\r\n', '\n')).replace('\n', '\r\n')
                else:
                    changed = patch(name, text)
                data = changed.encode('utf-8')
            entries.append((item, data))
        with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED) as dst:
            for item, data in entries:
                dst.writestr(item, data)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('original', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    build(args.original, args.output)
