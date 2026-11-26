# ADR 002 — Dropify como puente WooCommerce

Decisión del usuario (2026-11-26): no depender de una API directa de Dropi. Se selecciona el conector Dropify para WooCommerce. Esta decisión sustituye el requisito de API propia de ADR 001, pero no sus controles de seguridad ni la necesidad de pruebas sin efecto comercial.

WooCommerce ya es el motor comercial de Bakatá. Bakatá Core utilizará CRUD nativo y Dropify será el único candidato a responsable del envío a Dropi. No crear un segundo pedido WooCommerce ni un segundo despachador. Los identificadores WooCommerce y de proveedor no son intercambiables.

## Preflight

1. Obtener ZIP oficial de la versión exacta de Dropify. No instalar todavía.
2. Ejecutar `python3 scripts/audit-dropify.py /ruta/dropify.zip`. Registrar SHA-256 y revisar manualmente las ubicaciones identificadas. El informe no certifica seguridad, compatibilidad o ausencia de otros hooks.
3. Revisar CVE, endpoints, capacidades, nonces, opciones de credenciales, cron, acciones de checkout, HPOS y automatización de órdenes. Confirmar cómo bloquear envíos; si no existe control verificable, detener la prueba.
4. Usar entorno descartable, datos sintéticos, sin credenciales ni salida de red comercial. Verificar compatibilidad con las versiones fijadas en el repositorio.
5. Solo con entorno de prueba autorizado, configurar el token generado por el usuario mediante mecanismo seguro del plugin. No registrar token en Git ni logs.

## Criterios de aceptación

- Importación: producto y variante identificables, sin publicación automática no autorizada, repetición sin duplicados.
- Inventario: observar semántica y frescura; no interpretar precio de venta como costo ni stock local como confirmación del proveedor.
- Pedido: comprobar un único envío por pedido y comportamiento ante timeout y reintento, sin despacho real.
- Estados: separar pago y logística; documentar metadatos reales de guía y tracking antes de construir adaptadores.
- Contraentrega: mantener restricciones actuales hasta validar configuración, costo y autorización.
- Activación: aprobación explícita y plan de reversión; no activar dos motores de despacho.

Estado: ruta seleccionada; código exacto del plugin y entorno de prueba todavía no verificados. Este cambio no registra hooks, instala plugins, conecta tokens ni modifica el runtime.
