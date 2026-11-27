# INT-15 — Conciliación comercial Dropi / WooCommerce

Se respeta ADR 002: Dropify es la vía prevista de integración con Dropi y el único candidato a despacho. Bakatá Intelligence no llama endpoints privados, no crea un segundo conector de pedidos y no utiliza tokens. El ZIP 4.7.3 auditado previamente no se incluye ni instala en esta fase. El contrato observado de metadata se toma de docs/dropify-4.7.3-audit.md; no se acredita aquí compatibilidad con otra versión ni se prueba el conector activo.

## Alcance

DropifyPreview es una API PHP interna de solo lectura que se carga con Bakatá Core pero no registra hooks, REST, acciones de admin ni cron. Solo WP-CLI, BAKATA_CI_FIXTURES=1, sitio localhost/127.0.0.1, manage_options, edit_products y edit_post sobre el producto. No se invoca en producción. El objeto ReviewedDropifyQuote representa una anotación de proveedor revisada, no una llamada ni una respuesta autenticada de Dropi.

Se exige snapshot sintético INT-07/08 válido, candidato review-ready COP sin bloqueos, ID WooCommerce, SKU exacto, producto simple existente, referencia no secreta de tienda, ID numérico exacto de Dropi, referencia de mapeo y evidencia, fecha de observación de proveedor y política de vigencia (hasta 24h). Se verifica la coincidencia de SKU mediante CRUD WooCommerce y la presencia de una sola entrada _dropi_product_id. Si hay metadata _dropi_variation, se rechaza para revisión manual. No se interpretan _dropi_product, _dropi_token_store ni _dropi_token ni se incluyen en salida. WooCommerce puede cargar metadata del producto internamente; no se afirma que el proceso no pueda acceder a ella. No se verifica todavía la asociación entre la cuenta de Dropi y storeRef: es una anotación del operador, no autenticación. No garantiza unicidad de mapeo Dropi en todo el catálogo.

Identidad propuesta mediante SupplierProduct('dropify', storeRef + ':' + externalId). No cambia SKU existente, no registra asociación persistente ni crea producto. Identidad de variante pendiente; el título del candidato solo se usa en el DTO en memoria. El score previo es información de investigación, no aprobación de proveedor.

## Economía y disponibilidad

El precio de venta WooCommerce no es costo de adquisición; su stock tampoco es inventario confirmado del proveedor. El llamador debe aportar de manera explícita costo COP en centavos, disponibilidad entera y evidencia de observación del proveedor. Desconocidos quedan null, stock cero bloquea. UnitCosts debe coincidir exactamente con costo revisado, moneda y exponente; demás costos y PricingPolicy son explícitos. Se recalcula precio candidato con PricingPreview, no se altera precio activo. Una política inviable devuelve error para revisión. Se muestra contribución y bloqueos. Los valores del fixture (costo 25.000 COP, transporte 12.000, comisión fija 1.000, reserva 2.000, deducción variable 4%, precio candidato 57.000 y contribución 14.720 COP) son exclusivamente sintéticos. No se puede inferir disponibilidad futura.

## Prueba y límites

CI usa WordPress/WooCommerce desechable y crea un producto de prueba con metadatos sintéticos que imitan el contrato auditado. Comprueba permisos, identidad, SKU, vigencia, unknown vs zero, costo incompatible, candidato incompleto, precio recalculado, metadata duplicada y variantes no soportadas. Comprueba que la vista no cambia datos ni metadata del producto y no devuelve los canarios sintéticos de credenciales o payload opaco. No instala ni ejecuta Dropify. No se modifica WooCommerce real, no se consultan proveedores ni se crean pedidos.

Antes de operación comercial: confirmar ZIP/version exacta y autorización de sandbox; verificar hardening acumulado, cifrado y rotación de token integrados (aún no conectados), captura autorizada de costo y stock con contrato probado, cuenta/tienda y variantes verificadas, detección global de duplicados, persistencia de mapeos con revocación, permisos granulares, revisión de hooks/dispatch y pruebas egress bloqueado con conector real. INT-16 debe introducir flujo administrativo de aprobación autenticado y persistente sin publicar automáticamente. No habilitar despacho ni sincronización automática en esta etapa.
