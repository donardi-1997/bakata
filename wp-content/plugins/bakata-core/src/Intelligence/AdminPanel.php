<?php
declare(strict_types=1);

namespace Bakata\Core\Intelligence;

final class AdminPanel
{
    public const CAPABILITY = 'manage_options';
    public const SLUG = 'bakata-intelligence';

    public static function register(): void
    {
        add_action('admin_menu', [self::class, 'menu']);
        add_action('admin_post_bakata_intelligence_preview', [self::class, 'upload']);
        add_action('admin_post_bakata_intelligence_clear', [self::class, 'clear']);
    }

    public static function menu(): void
    {
        add_menu_page('Bakatá Intelligence', 'Bakatá Intelligence', self::CAPABILITY, self::SLUG,
            [self::class, 'render'], 'dashicons-chart-area', 58);
    }

    private static function guard(): void
    {
        if (!current_user_can(self::CAPABILITY)) {
            wp_die('Acceso no autorizado.', '', ['response' => 403]);
        }
    }

    private static function key(): string
    {
        return 'bk_int_preview_' . get_current_user_id();
    }

    private static function redirect(string $notice): void
    {
        wp_safe_redirect(add_query_arg(['page' => self::SLUG, 'bk_notice' => $notice], admin_url('admin.php')));
        exit;
    }

    public static function upload(): void
    {
        self::guard();
        if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
            wp_die('Método no permitido.', '', ['response' => 405]);
        }
        check_admin_referer('bakata_intelligence_preview', 'bk_int_upload_nonce');
        try {
            $file = $_FILES['snapshot'] ?? null;
            if (!is_array($file) || ($file['error'] ?? null) !== UPLOAD_ERR_OK
                || !is_string($file['tmp_name'] ?? null) || !is_uploaded_file($file['tmp_name'])
                || !is_int($file['size'] ?? null) || $file['size'] > PreviewSnapshot::MAX_BYTES) {
                throw new \InvalidArgumentException('Invalid upload.');
            }
            $json = file_get_contents($file['tmp_name'], false, null, 0, PreviewSnapshot::MAX_BYTES + 1);
            if (!is_string($json)) {
                throw new \InvalidArgumentException('Invalid upload.');
            }
            PreviewSnapshot::decode($json);
            // No media library, attachment, product or file persistence. User-local short-lived cache.
            set_transient(self::key(), $json, 15 * MINUTE_IN_SECONDS);
            if (get_transient(self::key()) !== $json) {
                throw new \RuntimeException('Preview cache unavailable.');
            }
        } catch (\Throwable $e) {
            self::redirect('invalid');
        }
        self::redirect('loaded');
    }

    public static function clear(): void
    {
        self::guard();
        if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
            wp_die('Método no permitido.', '', ['response' => 405]);
        }
        check_admin_referer('bakata_intelligence_clear', 'bk_int_clear_nonce');
        delete_transient(self::key());
        self::redirect('cleared');
    }

    private static function parameter(string $name): string
    {
        return isset($_GET[$name]) && is_string($_GET[$name])
            ? sanitize_text_field(wp_unslash($_GET[$name])) : '';
    }

    private static function score(?int $value): string
    {
        return $value === null ? 'Sin datos' : number_format($value / 100, 2, ',', '.');
    }

    private static function money(?int $value, string $currency): string
    {
        return $value === null ? 'Desconocido' : $currency . ' ' . number_format($value / 100, 2, ',', '.');
    }

    public static function render(): void
    {
        self::guard();
        $labels = ['review-ready'=>'Listo para revisión','incomplete'=>'Incompleto','blocked'=>'Bloqueado'];
        $criteria = ['profitability'=>'Rentabilidad','demand'=>'Demanda','supplier_reliability'=>'Proveedor',
            'logistics'=>'Logística','advertising'=>'Publicidad','differentiation'=>'Diferenciación','return_risk'=>'Bajo riesgo de devolución'];
        $snapshot = null;
        $cached = get_transient(self::key());
        if (is_string($cached)) {
            try {
                $snapshot = PreviewSnapshot::decode($cached);
            } catch (\Throwable $e) {
                $snapshot = null;
            }
        }
        $notices = ['loaded'=>'Vista previa cargada.','invalid'=>'Archivo no válido o vista previa no disponible.',
            'cleared'=>'Vista previa eliminada.'];
        $notice = self::parameter('bk_notice');
        echo '<div class="wrap"><h1>Bakatá Intelligence</h1>';
        echo '<p>Panel experimental de inteligencia comercial. Solo admite snapshots sintéticos, sin datos reales ni acciones sobre el catálogo.</p>';
        if (isset($notices[$notice])) {
            echo '<div role="status" class="notice notice-info"><p>' . esc_html($notices[$notice]) . '</p></div>';
        }
        DropifyDiagnostics::render();
        echo '<h2>Cargar evaluación offline</h2><form method="post" enctype="multipart/form-data" action="' . esc_url(admin_url('admin-post.php')) . '">';
        echo '<input type="hidden" name="action" value="bakata_intelligence_preview">';
        wp_nonce_field('bakata_intelligence_preview', 'bk_int_upload_nonce', false);
        echo '<label for="bk-snapshot">Snapshot JSON (máximo 256 KiB)</label> ';
        echo '<input id="bk-snapshot" name="snapshot" type="file" accept=".json,application/json" required> ';
        submit_button('Cargar vista previa', 'primary', 'bk_upload', false);
        echo '</form><p>La vista previa es individual y caduca a los 15 minutos. No certifica la evidencia.</p>';
        if ($snapshot === null) {
            echo '<h2>Sin evaluaciones cargadas</h2><p>Genera un snapshot de prueba desde el servicio offline.</p></div>';
            return;
        }
        $rows = $snapshot['rows'];
        $counts = array_fill_keys(array_keys($labels), 0);
        foreach ($rows as $row) {
            ++$counts[$row['status']];
        }
        echo '<form method="post" action="' . esc_url(admin_url('admin-post.php')) . '">';
        echo '<input type="hidden" name="action" value="bakata_intelligence_clear">';
        wp_nonce_field('bakata_intelligence_clear', 'bk_int_clear_nonce', false);
        submit_button('Eliminar vista previa', 'secondary', 'bk_clear', false);
        echo '</form><h2>Resumen de datos simulados</h2><p>Evaluación: ' . esc_html($snapshot['as_of']) . ' · Rúbrica: ' . esc_html($snapshot['rubric']) . '</p>';
        echo '<p>Total: <strong>' . esc_html((string) count($rows)) . '</strong>';
        foreach ($labels as $key => $label) {
            echo ' · ' . esc_html($label) . ': <strong>' . esc_html((string) $counts[$key]) . '</strong>';
        }
        echo '</p>';
        $query = substr(self::parameter('s'), 0, 120);
        $status = self::parameter('status');
        $status = isset($labels[$status]) ? $status : '';
        echo '<form method="get" action="' . esc_url(admin_url('admin.php')) . '"><input type="hidden" name="page" value="' . esc_attr(self::SLUG) . '">';
        echo '<label for="bk-query">Buscar producto o fuente</label> <input id="bk-query" name="s" value="' . esc_attr($query) . '" maxlength="120"> ';
        echo '<label for="bk-status">Estado</label> <select id="bk-status" name="status"><option value="">Todos</option>';
        foreach ($labels as $key => $label) {
            echo '<option value="' . esc_attr($key) . '"' . selected($status, $key, false) . '>' . esc_html($label) . '</option>';
        }
        echo '</select> ';
        submit_button('Filtrar', 'secondary', 'bk_filter', false);
        echo '</form><h2>Candidatos</h2><div style="overflow-x:auto"><table class="widefat striped"><caption class="screen-reader-text">Evaluaciones sintéticas</caption>';
        echo '<thead><tr><th scope="col">Producto / fuente</th><th scope="col">Precio observado</th><th scope="col">Estado</th><th scope="col">Puntos / 100</th><th scope="col">Evidencia</th></tr></thead><tbody>';
        $filtered = PreviewSnapshot::filter($rows, $query, $status);
        foreach ($filtered as $row) {
            echo '<tr><td><strong>' . esc_html($row['title']) . '</strong><br>' . esc_html($row['source'] . ' / ' . $row['external_id']) . '</td>';
            echo '<td>' . esc_html(self::money($row['price_minor'], $row['currency'])) . '</td><td>' . esc_html($labels[$row['status']]) . '</td>';
            echo '<td>' . esc_html(self::score($row['score_bp'])) . '<br>Cobertura: ' . esc_html((string)$row['coverage_pct']) . '%</td>';
            echo '<td><details><summary>Ver evaluación</summary><p>Origen: ' . esc_html($row['url']) . '<br>Captura: ' . esc_html($row['observed_at']) . '</p>';
            if ($row['blockers'] !== []) {
                echo '<p>Bloqueos: ' . esc_html(implode(', ', $row['blockers'])) . '</p>';
            }
            echo '<ul>';
            foreach ($row['components'] as $component) {
                echo '<li><strong>' . esc_html($criteria[$component['criterion']]) . '</strong> (' . esc_html((string)$component['weight']) . '%): '
                    . esc_html(self::score($component['score_bp'])) . ' · ' . esc_html($component['reason'])
                    . ' · Ref: ' . esc_html($component['evidence_ref'] ?? 'Sin evidencia') . '</li>';
            }
            echo '</ul></details></td></tr>';
        }
        if ($filtered === []) {
            echo '<tr><td colspan="5">No hay candidatos para estos filtros.</td></tr>';
        }
        echo '</tbody></table></div><p>Listo para revisión no significa aprobado para publicar.</p></div>';
    }
}
