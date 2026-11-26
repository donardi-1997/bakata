# Bakatá — instrucciones para contribuir

- WordPress y WooCommerce son el motor; no editar su núcleo ni versionar dependencias instaladas.
- Mantener presentación en el tema y reglas comerciales en Bakatá Core.
- Usar APIs CRUD de WooCommerce para pedidos, compatibles con HPOS; evitar SQL directo sobre pedidos.
- Validar y sanear entradas; escapar salidas según contexto. Usar capabilities, nonces cuando apliquen y permisos REST explícitos.
- Nunca almacenar secretos, datos de clientes ni dumps reales en Git. No registrar información personal innecesaria.
- Para integraciones: adaptadores por proveedor, idempotencia, reintentos limitados, firma de webhooks y trazabilidad sin datos sensibles.
- No publicar productos ni enviar pedidos a proveedores sin autorización explícita y pruebas en sandbox.
- Antes de integrar cambios: PHP lint, validación JSON, Compose y prueba de arranque cuando corresponda.
- Mantener documentación y decisiones de arquitectura actualizadas.
