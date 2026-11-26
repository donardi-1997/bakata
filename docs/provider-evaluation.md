# Evaluación de proveedor para Bakatá — ADR 001

Fecha de revisión: 2026-11-26. Estado: Dropi Colombia confirmado por el usuario como proveedor prioritario para evaluación; no constituye autorización de instalación, despacho ni contrato comercial. Objetivo: Colombia, COP, WooCommerce, operación con control de catálogo, precios y despacho en Bakatá Core. No se han creado cuentas, instalado plugins externos, probado APIs autenticadas ni adquirido productos.

## Evidencia pública y decisión provisional

| Criterio | Dropi | CJdropshipping | Rocketfy |
|---|---|---|---|
| Alineación con Colombia | Plataforma y operador local documentados | Cotizar cada SKU, origen y destino colombiano; no comprobado | Oferta de dropshipping en Colombia |
| WooCommerce | Integración Dropify y token descritos por Dropi | Integración directa y API documentadas | Oferta pública revisada enfatiza Shopify; conector WC y alcance por confirmar |
| Catálogo/stock/pedidos | Funciones comerciales anunciadas; contrato API propio no confirmado | API documentada de productos, variantes, stock, órdenes, logística y webhooks | API pública para integraciones comerciales; alcance de dropshipping por confirmar |
| Sandbox | No verificado | Creación explícita de pedido isSandbox=1 documentada; valor por defecto es operación normal | No verificado |
| Costos, devoluciones, SLA | Cotización y contrato pendientes por cuenta/SKU | Cotización total, aduanas y devolución pendientes | Cotización y negociación pendientes |

Recomendación provisional: evaluar primero Dropi Colombia. Su integración WooCommerce y orientación local encajan con el lanzamiento nacional. CJ es alternativa técnica con documentación pública más extensa y sandbox explícito; eso no prueba conveniencia logística en Colombia. Rocketfy queda como alternativa local condicionada a negociación y confirmación de capacidades. No se asignan puntuaciones artificiales ni se declara ganador por costo sin cotizaciones. No sustituir la API autorizada con endpoints encontrados en repositorios no oficiales, tokens de sesiones web o scraping.

Dropi anuncia inicio gratuito y tiempos orientativos, pero sus términos prevén cargos por funcionalidades y mantienen obligaciones de atención, garantías y devoluciones en el dropshipper. No prometer envíos ni incorporar tarifas al motor de precios sin cotización de la cuenta. El plugin Dropify tiene automatización de pedidos; no instalarlo o habilitarlo en paralelo con Bakatá Core hasta revisar su código, permisos, compatibilidad HPOS, efectos de stock, publicación, checkout, creación de órdenes y posibilidad de desactivar automatización. Un token de integración de WooCommerce no implica permiso para una API personalizada.

## Evidencia a solicitar a Dropi

1. Contrato API oficial vigente, versión, base URL y autorización de integración propia desde Bakatá Core; mecanismo de autenticación, scopes, rotación y revocación, límites y formato de errores.
2. Sandbox o cuenta de prueba aislada que no cobre ni despache, con datos sintéticos y permiso explícito para operaciones de prueba. Identificar diferencias con producción.
3. Catálogo: IDs de producto/variante estables, paginación, moneda y escala, costos de compra, imágenes/licencias, impuestos incluidos/excluidos, stock disponible y timestamp/semántica de disponibilidad.
4. Envíos: cotización por SKU/cantidad/municipio, cobertura, transporte, tiempos y costos de preparación/entrega, devoluciones, garantías, incidencias, cancelación y cargo por entrega fallida.
5. Pedidos prepagados: fondeo, conciliación, moneda, límites, cargos, identidad de pedido, idempotencia o referencia externa consultable, resultado ambiguo de timeout, búsqueda, cancelación y reintentos. COD requiere decisión independiente: el motor actual lo bloquea.
6. Tracking: referencias de envío, múltiples paquetes, estados, webhook firmado (algoritmo, cuerpo exacto, timestamp, ID, reintentos, duplicados, rotación) o consulta autenticada de estado. Tratamiento de datos y responsabilidades, retención, subencargados y transferencia.
7. Tarifario y SLA escritos; contacto técnico y procedimiento de escalamiento.

## Prueba de aceptación propuesta (aún no ejecutada)

| Puerta | Evidencia exigida | Efecto permitido |
|---|---|---|
| G0 decisión comercial | Usuario aprueba proveedor y contrato/API/sandbox recibidos | Diseñar adapter, sin credenciales en Git |
| G1 lectura | Catálogo y variantes de sandbox, moneda/escala, paginación, stock/frescura, 401/403/429/5xx y timeout, fixtures anonimizados | Solo lectura, sin creación de producto |
| G2 importación | IDs y cotización verificados, repetición y colisión, revisión editorial/licencias | Borradores ocultos en entorno aislado con autorización explícita |
| G3 logística y precios | Cotizaciones verificadas para Bogotá y otros destinos de prueba (Medellín, Cali, municipio remoto por seleccionar), devoluciones y cargos | Simulaciones, nunca activar stock/precio |
| G4 pedido sandbox | Liquidación simulada, reserva, idempotencia persistente, timeout ambiguo, consulta de referencia, cancelación, nunca saldo/orden real | Despacho únicamente de sandbox explícito |
| G5 eventos | Firma del proveedor, dedupe concurrente, replay, cola/persistencia de trabajo, fallos y reconciliación, varios paquetes | Procesamiento sandbox con auditoría |
| G6 lanzamiento | Aprobación comercial explícita, políticas y privacidad, pagos/impuestos, monitoreo, revisión de seguridad, operación manual de emergencia | Catálogo piloto y despliegue autorizado |

No conectar producción hasta completar G0–G6. Para CJ, isSandbox debe fijarse explícitamente a 1 y verificarse en respuesta/consulta; jamás confiar en valor predeterminado. No crear órdenes en esta fase. El recibo persistente de Bakatá no equivale a efecto procesado: antes de G4/G5 se requiere almacenamiento transaccional del trabajo, reconciliación de resultado incierto y prueba de concurrencia.

## Fuentes públicas consultadas (2026-11-26)

- Dropi Colombia, [integraciones](https://dropi.co/integraciones), [dropshippers](https://dropi.co/soluciones-para-dropshippers), [servicio logístico](https://www.dropi.co/servicio-logistico), [inicio](https://dropi.co/), [términos](https://dropi.co/terminos-y-condiciones), [contacto](https://dropi.co/contactanos/).
- CJ, [documentación de desarrollo](https://developers.cjdropshipping.com/en/api/start/development.html), [sandbox](https://developers.cjdropshipping.com/en/api/start/sandbox.html), [documentación API](https://developers.cjdropshipping.com/), [FAQ integraciones](https://www.cjdropshipping.com/help-center?faqType=5&navType=faq&pageNum=9&scrollToNum=400).
- Rocketfy, [dropshippers](https://www.rocketfy.com/dropshippers/), [API pública](https://rocketfy-1.gitbook.io/api-publica): exige negociación activa y credenciales entregadas por Rocketfy.

## Acción siguiente

Con Dropi confirmado como primer candidato, solicitar documentación/condiciones al canal comercial oficial comercial@dropi.co (contacto@dropi.co, WhatsApp +57 310 675 6608). No contactar ni contratar automáticamente. Si no ofrece API autorizada o pruebas sin efecto real, reevaluar CJ o Rocketfy. Compartir documentación no confidencial o ejemplos anonimizados; nunca pegar claves/tokens en issues, PR o Git. Mientras no se cumpla G0, mantener integración comercial deshabilitada.

## Confirmación del candidato y ruta Dropify (2026-11-26)

El usuario confirma Dropi Colombia como candidato prioritario. [Integraciones de Dropi](https://dropi.co/integraciones) confirma generación de token al crear la tienda y configuración en Dropify para WooCommerce. El [directorio WordPress](https://wordpress.org/plugins/wc-dropi-integration/) identifica el slug wc-dropi-integration, versión 4.7.3, probado hasta WP 6.8.13, y describe importación de catálogo y generación automática de órdenes. No equivale a acceso autorizado a una API propia. El directorio advierte falta de pruebas con las tres versiones principales recientes de WordPress. Bakatá usa WordPress 7.1.5, WooCommerce 11.3.1 y PHP 8.3; validar compatibilidad real (HPOS y Checkout Blocks incluidos). Existe antecedente CVE-2025-53286 (XSS reflejado, [Tenable](https://www.tenable.com/cve/CVE-2025-53286) indica versiones hasta 4.7.2), y un [reporte de soporte no resuelto](https://wordpress.org/support/topic/security-vulnerability-in-dropify-4-7-3-request-for-a-fix/) para 4.7.3; no confirma vulnerabilidad en 4.7.3. Revisar código de la versión exacta y confirmar corrección con proveedor antes de uso.

Ruta propuesta: revisar conector sin ejecución; levantar entorno descartable sin token ni acceso a producción, bloquear egress comercial, inspeccionar hooks, capacidades, almacenamiento de credenciales, cron, REST, HPOS, Checkout Blocks, importación a borrador y opción de desactivar envío automático. Después solicitar cuenta/token de prueba específico del entorno y autorización de pruebas sin efecto real. No activar ambos motores de despacho: un solo responsable por operación, con conciliación. Si Dropify no permite control suficiente, solicitar API autorizada o reevaluar. No almacenar tokens en Git, chats, logs ni comandos visibles. No se ha instalado el plugin ni conectado cuenta. Mantener G0 pendiente hasta contrato técnico y entorno de pruebas.
