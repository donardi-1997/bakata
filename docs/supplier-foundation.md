# Bakatá Core — base de proveedores (fase 1)

Alcance: contratos y previsualización pura, sin proveedor seleccionado. Respeta docs/architecture.md: ninguna integración comercial antes de confirmar proveedor, contrato API y sandbox. No se registra adaptador real, endpoint REST, job programado, credencial, tabla, webhook ni acción comercial. El plugin carga clases PHP, sin ejecutar sincronización. El adaptador falso existe exclusivamente en la prueba CLI independiente.

## Contrato

CatalogAdapter: supplierId y fetchPage(cursor, limit), paginación opaca. SupplierProduct representa una unidad vendible/variante con identificador externo estable, nombre, costo unitario en unidades monetarias menores enteras, código de moneda y exponente explícito, disponibilidad entera no negativa y fecha de observación. Cero inventario es válido; stock desconocido o costo desconocido no se deben sustituir por cero. El adaptador futuro deberá mapearlos como datos incompletos y rechazar/omitir de forma explícita con evidencia. La disponibilidad no garantiza inventario al momento del pedido.

Identidad SHA-256 de proveedor + ID externo; SKU propuesto bk- + hash completo, aún no reservado en WooCommerce. Huella de cambio de nombre, costo, moneda/exponente y stock (excluye fecha). No confundir huella con idempotencia transaccional persistente.

CatalogPreview exige moneda/exponente y edad máxima explícitos. No convierte divisas, calcula precio de venta ni decide publicación. Limita tamaño, páginas y productos; rechaza datos caducados/futuros, duplicados, cursores repetidos y moneda/proveedor incorrectos. Si falta una página o falla el adaptador, no entrega un resultado parcial. No ejecuta IO salvo la llamada a un adaptador suministrado por el llamante; no se invoca automáticamente. El adaptador concreto deberá limitar tiempo de red y reintentos.

## Prueba y siguientes decisiones

CI ejecuta scripts/test-supplier-foundation.php en PHP 8.3 aislado, sin WP ni llamadas externas. Incluye paginación, límites, stock cero, identidad, cambios, moneda, duplicados, antigüedad y entradas inválidas. No crea productos, pedidos ni credenciales.

Pendiente: seleccionar proveedor y revisar catálogo, variantes, costos en destino, stock real, imágenes/licencias, políticas de devoluciones, entregas a Colombia y sandbox. Después: adapter HTTP con validación de respuestas, almacenamiento seguro de secretos, persistencia del mapeo e idempotencia, simulación de margen, importación a borrador explícita, reconciliación de stock, trazabilidad, colas/reintentos y webhooks firmados. Envío de pedidos permanece deshabilitado hasta autorización y validación de sandbox. No usar la huella de catálogo como clave de idempotencia de despacho.
