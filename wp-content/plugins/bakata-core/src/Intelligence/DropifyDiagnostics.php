<?php
declare(strict_types=1);

namespace Bakata\Core\Intelligence;

/** No database queries for credentials, plugin code execution or remote calls. */
final class DropifyDiagnostics
{
    private const FILES = [
        'wc-dropi-integration.php' => 'db77532b98de56f7e59970475ad672fd10224503cf684f83537bb04a91557386',
        'clasess/tables/Product_List.php' => '868a51be34ec383be9655d2f8c63ea7902bef3ca4c7c7e293b4fb44911945c1e',
        'clasess/models/ProductsModel.php' => 'd104104d6278dddbad338aab4c48c0aab4c8a76673f6a6a54d8588410e748a5c',
        'clasess/models/TokenModel.php' => 'a4eff99ee32ac1c21e62a434856450d22bace93afc2dcab9f3673eceb167262c',
        'clasess/views/Products.php' => '4f7e7fc0656291650ad46fbeec5afde164b9501c1bf0421714b7bb0c7dff174b',
    ];

    public static function inspect(): array
    {
        if (!current_user_can('manage_options')) {
            throw new \RuntimeException('Administrator required.');
        }
        require_once ABSPATH . 'wp-admin/includes/plugin.php';
        $entry = 'wc-dropi-integration/wc-dropi-integration.php';
        $plugins = get_plugins();
        if (!isset($plugins[$entry])) {
            return ['status'=>'not-detected','version'=>null,'active'=>false,'files'=>[]];
        }
        $root = realpath(WP_PLUGIN_DIR . '/wc-dropi-integration');
        $files = [];
        foreach (self::FILES as $relative => $expected) {
            $path = $root === false ? false : realpath($root . '/' . $relative);
            $digest = false;
            if ($path !== false && str_starts_with($path,$root . DIRECTORY_SEPARATOR)
                && is_file($path) && is_readable($path) && filesize($path) <= 2*1024*1024) {
                $digest = hash_file('sha256',$path);
            }
            $files[$relative] = $digest === false ? 'unavailable'
                : (hash_equals($expected,$digest) ? 'matches-original' : 'different');
        }
        $version = (string)($plugins[$entry]['Version'] ?? '');
        return ['status'=>$version === '4.7.3' && count(array_filter($files,static fn($v)=>$v==='matches-original')) === count(self::FILES)
            ? 'original-files-match' : 'requires-review',
            'version'=>$version,'active'=>is_plugin_active($entry),'files'=>$files];
    }

    public static function render(): void
    {
        $report = self::inspect();
        echo '<h2>Diagnóstico local de Dropify</h2>';
        if ($report['status'] === 'not-detected') {
            echo '<p>No se detectó el conector en la ruta estándar.</p>';
            return;
        }
        echo '<p>Versión declarada: <strong>' . esc_html($report['version']) . '</strong> · '
            . ($report['active'] ? 'Activo' : 'Inactivo') . '</p>';
        echo '<p>' . esc_html($report['status'] === 'original-files-match'
            ? 'Los cinco archivos examinados coinciden con el ZIP original 4.7.3; esta versión presenta hallazgos de seguridad.'
            : 'Los archivos o la versión difieren de la referencia original; se requiere revisión.') . '</p>';
        echo '<details><summary>Comparación de archivos</summary><ul>';
        foreach ($report['files'] as $file=>$status) {
            echo '<li>' . esc_html($file . ': ' . $status) . '</li>';
        }
        echo '</ul></details><p>No verifica la seguridad del plugin completo ni consulta el token o Dropi.</p>';
    }
}
