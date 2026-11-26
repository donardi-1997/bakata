# Auditoría estática Dropify 4.7.3

ZIP suministrado por el usuario, 65 entradas. SHA-256: bf23c6b1c5dd640aab3d38e3f370a41fbd60139ac60a1ce5f0347a059e9b6700. Versión declarada en wc-dropi-integration.php:6. Inspección estática sin ejecución ni autenticación; procedencia oficial no certificada independientemente. Rutas relativas al directorio del plugin.

| Hallazgo | Evidencia | Decisión |
|---|---|---|
| TLS sin verificación | clasess/models/OrdersModel.php:341; ProductsModel.php:62,168,777,905,954; clasess/Dropi.php:213 | Bloquear producción hasta corrección y prueba TLS |
| Importación AJAX continúa tras nonce inválido | clasess/Products.php:138–150, registro nopriv:298 | Exigir autorización y retorno inmediato ante fallo |
| Token en GET y metadatos | clasess/tables/TokenTable.php:50–68; clasess/models/ProductsModel.php:460–463 | Evitar token real hasta revisar gestión de secretos y registros |
| Registro de datos del pedido | clasess/models/OrdersModel.php:295–327,373–374 | Redactar datos personales y credenciales antes de habilitar |
| Importación publica productos | clasess/models/ProductsModel.php:294,595 | Exigir revisión editorial y aislamiento |
| Cron de inventario deshabilitado | clasess/Dropi.php:159–161 | No asumir stock fresco; validar alternativa autorizada |
| Despacho automático | clasess/Woocomerce.php:46–65,293 | Mantener opción dropi-woocomerce-autosync_orders desactivada durante pruebas; no asumir que bloquea envío manual |
| Contraentrega | clasess/models/OrdersModel.php:279–284 | Reconoce cod; verificar importes y comportamiento real |
| Referencia de pedido | clasess/models/OrdersModel.php:317,380–388 | Referencia local y remota no prueban idempotencia; exigir conciliación y prueba de concurrencia |
| Guía | clasess/Woocomerce.php:94–96 | Lee shipping_guide; origen y actualización no verificados |
| HPOS | clasess/Woocomerce.php:80–95,298–309 | Acceso legado a post meta y pantallas de pedidos; validar HPOS antes de uso |

## Contrato observado, no API propia
Productos: _dropi_product_id, _dropi_product, _dropi_variation, _dropi_token_store, _dropi_token. Pedidos: _is_dropi_order, _dropi_order_id, shipping_guide (lectura). Usar CRUD WooCommerce en Bakatá; no copiar credenciales, objetos serializados completos ni asumir semántica de stock/costo. El conector debe conservar responsabilidad exclusiva de la transmisión.

## Puerta de seguridad
No activar el ZIP sin corregir y verificar los hallazgos de seguridad. Solicitar versión corregida o evaluar parche mantenible y autorizado, sin modificar WordPress/WooCommerce. Pruebas en entorno descartable, con salida de red comercial bloqueada y datos sintéticos. No se han instalado plugins, realizado solicitudes de red del conector, conectado tokens ni creado pedidos. La inspección no es una auditoría exhaustiva ni prueba de explotación. La ruta WooCommerce sigue seleccionada.
