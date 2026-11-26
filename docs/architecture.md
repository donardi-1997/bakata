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
