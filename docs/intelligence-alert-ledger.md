# INT-17B — Centro persistente de alertas comerciales

Depende del motor de radar INT-17A (#65). Integrar #65 antes de este PR y volver a verificar contra main. No captura productos, no envía notificaciones y no modifica WooCommerce.

## Uso local

Usar una base privada separada para el historial, identificador de alcance estable y un umbral de precio fijo para esa base. No reutilizar el alcance para otro archivo de evidencia; es referencia declarada del operador, no identidad criptográfica. El umbral de 500 bps del ejemplo es ilustrativo.

    cd services/intelligence
    python3 -m intelligence.alert_ledger --ledger /privado/alerts.sqlite --archive-ref ARCHIVO --price-threshold-bps 500 collect --bridge /privado/bridge.sqlite --store 7

La colección abre BridgeArchive read-only y ejecuta el radar directamente, sin aceptar reportes JSON externos. Guarda la señal y la procedencia inicial. Una señal repetida no cambia estado ni crea otro registro. Si aparecen referencias adicionales de página, mantiene la evidencia original; si cambia el núcleo de la señal para el mismo ID, aborta la transacción. Se procesa un batch por operación; next_after permite recorrer más identidades. No es historial completo de todos los cambios entre escaneos.

Para leer la bandeja, sustituir collect y sus argumentos por list --store 7 [--state open|acknowledged|resolved]. El cursor es por ID de señal; el filtro de estado aplica sobre el lote recorrido, incluso si devuelve cero filas. El orden de prioridad es local al lote, no ranking global. Consultar history --alert-id SHA para obtener latest_event_sha256 (64 ceros antes del primer evento).

    python3 -m intelligence.alert_ledger --ledger /privado/alerts.sqlite --archive-ref ARCHIVO --price-threshold-bps 500 transition --alert-id SHA --event-id ID_UNICO --to acknowledged --actor-ref REVISOR --reason-ref TICKET --expected-previous-sha256 DIGEST

Estados: open, acknowledged (reconocida), resolved (atendida/cerrada). Se permite reapertura explícita, no automática. Resolver una alerta no certifica que el problema comercial haya desaparecido ni aprueba un candidato. Las referencias de actor y motivo son declaraciones del operador CLI de confianza, no autenticación.

## Integridad y límites

SQLite con alcance/umbral fijados, transacciones BEGIN IMMEDIATE, IDs únicos, digest de evidencia, cadena por alerta, comprobación de último evento para concurrencia y triggers contra UPDATE/DELETE ordinarios. 20.000 alertas, 100.000 eventos totales, 100 por alerta y presupuesto 192 MiB del archivo principal. No hay purga automática. Un nuevo par de observaciones puede emitir una nueva alerta aunque la anterior siga abierta; no se cierran alertas por desaparición del radar. El historial expresa hechos observados, no condiciones actuales del proveedor. No es un registro de entrega. Los hashes no son firmas ni detectan truncado sin anclaje externo; proteger acceso y respaldos. El CLI usa umask privado, no cambia permisos preexistentes. Las lecturas de evidencia y escritura de alertas no son globalmente atómicas entre bases.

Foundation checks incluye pruebas sintéticas de deduplicación, persistencia de resolución, transiciones, conflicto de revisión, ámbito, inmutabilidad ordinaria, filtros, procedencia adicional y cambios inconsistentes. Próximo: exportación de bandeja y dashboard administrativo de solo lectura; integrar identidad autenticada antes de permitir cambios desde WordPress. Sin proveedor, sin avisos externos, sin importación ni publicación.
