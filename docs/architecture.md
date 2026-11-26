# Arquitectura

Monolito modular: WordPress administra contenido y autenticación, WooCommerce administra catálogo, carrito, checkout, pedidos e inventario. El tema de bloques controla la presentación y Bakatá Core extiende el comportamiento comercial mediante hooks y APIs públicas.

## Componentes

- Tema Bakatá: theme.json, plantillas y patrones. No contiene lógica de proveedores ni pagos.
- Bakatá Core: plugin PHP con namespace Bakata. Futuras capacidades: Suppliers, Catalog, Pricing, Inventory, Orders, Fulfillment, Analytics.
- MariaDB: persistencia de WordPress y WooCommerce.
- Docker Compose: entorno local, ligado a loopback. La infraestructura de producción se decidirá aparte.
- WP-CLI: instalación y administración reproducible.

## Decisiones iniciales

1. No desarrollar checkout ni motor comercial propios.
2. No modificar WordPress o WooCommerce; usar APIs públicas y CRUD compatible con HPOS.
3. No implementar integración hasta confirmar proveedor, contrato API y entorno de pruebas.
4. Separar estados de pago y despacho, incluir idempotencia para pedidos y webhooks.
5. Colombia/COP y America/Bogota son valores iniciales de desarrollo, sujetos a confirmación comercial.
6. No asumir disponibilidad o tiempos de entrega; validar con proveedor antes de publicar.
7. Para producción, fijar versiones, configurar HTTPS, respaldos, actualizaciones, mínimos privilegios, privacidad y observabilidad.

## Fase de proveedores iniciada

Se implementan contratos PHP de catálogo y una previsualización acotada en memoria sin registrar proveedores ni modificar WooCommerce. La decisión 3 se mantiene: la conexión comercial requiere proveedor confirmado, contrato API y sandbox. Véase [base de proveedores](supplier-foundation.md).

## Simulación de precios

Bakatá Core incluye un módulo Pricing puro que recibe costos y política explícitos, calcula contribución y propone un precio de escenario sin escribir en WooCommerce. No reemplaza impuestos, pagos ni configuración comercial. Véase [previsualización de precios](pricing-preview.md).

## Preparación de importaciones

DraftPlanner une la fuente normalizada con una cotización explícita. WooDraftImporter es una API interna de creación de borradores inertes, sin invocador comercial ni sincronización. No hay actualización de productos existentes. Véase [importación a borrador](draft-import.md).

## Reconciliación de inventario en modo lectura

InventoryPreview distingue observaciones confirmadas, desconocidas, caducadas y conflictivas, y calcula una cantidad candidata bajo política explícita. WooInventoryPreview lee exclusivamente borradores mapeados mediante CRUD, sin escribir stock. Véase [previsualización de inventario](inventory-preview.md).

## Preparación de pedidos

OrderPreview agrupa líneas históricas con mapeos explícitos por proveedor y genera referencias estables y huellas separadas, sin escribir pedidos ni enviar órdenes. WooOrderPreview consulta mediante CRUD con permisos y reglas conservadoras de elegibilidad. Véase [preparación de pedidos](order-preview.md).

## Fulfillment y seguimiento logístico

FulfillmentPreview reproduce historias de eventos normalizados por grupo de OrderPreview y agrega estados logísticos sin modificar pago, stock ni estado de WooCommerce. No es un receptor de webhooks ni una operación persistente. Véase [previsualización de fulfillment](fulfillment-preview.md).

## Recibos de webhooks

SignedEvent define un protocolo HMAC interno de referencia, WebhookInbox valida vinculaciones de grupos y WpReceiptLedger deduplica recibos mediante una clave única en tabla propia. No se registra un endpoint ni se procesa el efecto comercial. Véase [recibos de webhooks](webhook-receipts.md).

## Evaluación de proveedor

El [ADR 001](provider-evaluation.md) registra Dropi Colombia como candidato prioritario confirmado por el usuario y mantiene CJdropshipping y Rocketfy como alternativas. El método de integración, la autorización operativa y el contrato API/sandbox siguen pendientes; no se implementa adapter real sin completar G0. No hay cambios de runtime en esta evaluación.
