# INT-03 — Adaptadores comerciales

Tres adaptadores offline reciben capturas revisadas, nunca realizan solicitudes por sí mismos. El registro comienza vacío. No se activa ninguna plataforma real ni se altera la red deshabilitada del contenedor. Las autorizaciones deben verificarse externamente antes de registrar una fuente; una referencia de aprobación y su vencimiento no constituyen prueba jurídica ni permiso de red.

## Contratos

- WooCommerce Store API: colección JSON de productos públicos en /wp-json/wc/store/v1/products, con ID entero estable, permalink del host registrado y moneda/exponente explícitos. Se interpreta el precio en unidades menores, según la [documentación oficial](https://developer.woocommerce.com/docs/apis/store-api/resources-endpoints/products/). No se convierte dos veces. Productos variables y rangos se conservan sin precio comparable. Se admite una captura sin query; paginación y variantes quedan pendientes.
- JSON-LD: una página con un único candidato inequívoco y un identificador externo estable explícitamente revisado. No se supone que SKU sea global ni se inventa moneda.
- CSV autorizado: formato normalizado propio, no exportador nativo de ningún proveedor: external_id,title,url,currency,price_minor. Una celda de precio vacía es desconocida. Una fila inválida o identidad repetida rechaza todo el lote.

Los tres admiten COP/USD/EUR en centavos. El límite inicial es 512 KiB por captura y 100 observaciones. Solo URL HTTPS del host exacto, sin credenciales, parámetros o fragmento. No se extraen imágenes, reseñas, datos de clientes ni pedidos. Las entradas deben provenir de capturas sanitizadas.

Cada lote devuelve evidencia con fuente, URL, fecha UTC, SHA-256 del cuerpo, tipo de adaptador y referencia de aprobación. El hash permite comparar una captura conservada externamente; no certifica autenticidad ni autorización. La evidencia todavía no se almacena junto a ObservationStore; la prueba demuestra únicamente persistencia idempotente de observaciones en memoria. El reloj inyectable es para pruebas o un llamador confiable.

## Registro de fuentes candidatas (no habilitadas)

| Fuente | Método por evaluar | Requisito |
| --- | --- | --- |
| Tienda WooCommerce autorizada | Store API pública | Permiso de uso comercial y revisión de rutas |
| Tienda con datos estructurados | JSON-LD | Términos, robots y permiso de captura |
| Proveedor con exportación autorizada | CSV normalizado | Contrato y mapeo revisados |
| Mercado Libre, Amazon, AliExpress, Temu | API o mecanismo autorizado por plataforma | Revisar condiciones vigentes; sin adaptador específico todavía |
| Dropi | Integración WooCommerce existente o exportación expresamente autorizada | Validar contrato y origen del dato; no usar endpoints privados |

No se presume permiso por el hecho de que un dato sea público. No se realiza scraping real ni publicación de productos. Las pruebas utilizan exclusivamente dominios .invalid y fixtures.

## Validación

La suite unittest de INT-01 descubre test_commercial.py y prueba precios, procedencia, idempotencia, desconocidos, registros no aprobados, monedas, límites, rutas, duplicados y contratos. INT-02 conserva el transporte de referencia, pero esta etapa no lo conecta a fuentes vivas. Persistencia durable de evidencia, equivalencia entre fuentes, autorización operativa y seguridad de salida de red siguen pendientes.

Siguiente: INT-04, normalización y deduplicación conservadora con identidades por fuente y revisión humana para equivalencias entre proveedores.
