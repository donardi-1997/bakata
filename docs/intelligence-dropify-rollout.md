# INT-15G — Preparación de sustitución y rollback

## Evidencia confirmada

- PR #58 fusionado; ejecución Dropify catalog validation 45922046745 y Foundation checks 45922046691 exitosas. El log confirma instalación WordPress/WooCommerce, nonce inválido/ausente/no escalar, HTTP administrativo, reserva MariaDB y archivo offline.
- Artefacto de referencia del PR #58: 15165255683 (SHA-256 del artefacto externo f65c7ac02e4348509a943b7fe453ad616c9502fa052572977d8ab10bae16c535). No confundir esa huella con la del ZIP interno.
- Respaldo dev 2026-11-27 01:12:40 UTC: 53 tablas SQL recuperadas en MariaDB aislada, incluyendo configuración Dropify; no se usaron volúmenes activos.
- En este frente se recuperaron los 53 archivos del plugin desde wordpress.tar.gz, en directorio temporal privado del host, 850219 bytes, digest agregado original 900f3149c2e512ac52836f37bc369c8a2f424784c0faf4d7c404a818d4ba9f6e. El primer intento fue bloqueado por el nombre legítimo js/sweetalert2@11.js; la segunda extracción pasó, con limpieza comprobada. No se extrajeron wp-config.php ni otros plugins. No constituye una restauración integral de WordPress.

## Ensayo de reemplazo

El workflow existente construye el paquete desde el ZIP auditado, genera SHA256SUMS con ruta relativa y ensaya sustitución/recuperación en un directorio temporal privado, antes de publicar el artefacto. Rechaza rutas de escape, enlaces, archivos extra, árbol original no exacto y candidato distinto del builder catalog-only de la revisión. Prueba recuperación tras la primera operación rename y reversión posterior a un cambio completo. No hay escritor de producción ni conexión externa. La evidencia rollback-rehearsal.json contiene las huellas de ZIP y árbol, número de archivos cambiados y resultados; no tiene secretos. El digest esperado debe obtenerse del artefacto CI verificado, no de un ZIP de procedencia desconocida.

    python3 scripts/dropify-rollout-rehearsal.py /ruta/original.zip /ruta/dropify-catalog-validation.zip --candidate-sha256 SHA256_VALIDADO

La prueba usa una copia de archivos, no el contenedor activo. No prueba atomicidad de dos renames frente a tráfico concurrente, durabilidad ante corte eléctrico, permisos/propietario reales, opciones WordPress, OPcache ni recuperación de una tienda completa. Se exige detener el proceso PHP y bloquear tráfico y tareas antes de un eventual cambio.

## Checklist para intervención real (todavía no autorizada ni ejecutada)

1. Confirmar con operador la pérdida temporal de importación y despacho y la ventana de mantenimiento; identificar pedidos/sincronizaciones pendientes sin exponer datos. Confirmar que no existen consumidores concurrentes de los tokens. No desinstalar plugin.
2. Verificar commit desplegado, estado de salud, backup nuevo y privado, cobertura de archivos y tabla Dropify, restauración SQL y recuperación de archivos. Conservar punto de recuperación fuera del volumen activo, comprobar copia externa por procedimiento autorizado. Revisar evidencia y condiciones de cuenta con proveedor; no exponer token.
3. Obtener paquete del workflow verde correspondiente al commit revisado, validar artefacto y SHA256SUMS, ensayar con original exacto. Comprobar el árbol instalado contra la referencia y detener ante cualquier diferencia. Preparar copia candidata fuera de wp-content/plugins, en el mismo filesystem, con permisos y propietario revisados.
4. Con ventana aprobada, mantener flag de lectura deshabilitado y bloquear tráfico saliente de proveedor (incluido código fuera de WP HTTP). Detener WordPress y cualquier CLI/cron activo, tomar bloqueo exclusivo de deploy/backup. No realizar intervención por CD. Conservar original fuera del directorio de plugins; no dejar dos copias cargables. Confirmar que solo la ruta estándar contiene el candidato verificado. No activar migraciones, borrar tablas, cambiar tokens ni limpiar recibos.
5. Reiniciar PHP/WordPress en cuarentena; comprobar salud, tema, WooCommerce, menús, plugin activo, flag apagado y ausencia de llamadas proveedor. No iniciar pedidos ni importaciones. Revisar registros sin datos crudos.
6. Ante error, mantener cuarentena y detener WordPress. Verificar copia original antes de revertir los renames; preservar candidato fallido fuera del directorio de plugins. Reiniciar con red restringida: el original tiene hallazgos de seguridad y restaurarlo no autoriza reactivar automatismos. Revisar tablas/recibos antes de cualquier restauración de base; no revertir toda la base por defecto.
7. Solo tras aceptación de operación y seguridad se podrá planificar una lectura real autorizada de una página. INT-15H conserva los controles previos de aprobación.

No se implementa un comando de sustitución automática: el paso real depende del mantenimiento, egress de dev, aprobación explícita, revisión de permisos y estado actual de pedidos. El ensayo no autoriza ningún acceso al proveedor.
