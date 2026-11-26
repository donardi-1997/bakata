# Revisión estática Dropify 4.7.3

Fecha 2026-11-26. Decisión: NO instalar ni configurar token en esta versión sin remediación y pruebas aisladas. Usuario dispone de cuenta y token; no se ha recibido ni utilizado. Fuente: https://downloads.wordpress.org/plugin/wc-dropi-integration.4.7.3.zip ; SHA256 bf23c6b1c5dd640aab3d38e3f370a41fbd60139ac60a1ce5f0347a059e9b6700. 35 archivos PHP, 319482 bytes. Inspección estática mediante ZIP leído sin extraer ni ejecutar en directorio temporal de Lightsail; eliminado al finalizar. No constituye prueba de explotación ni auditoría exhaustiva.

## Hallazgos y puertas de aceptación

- Alta: clasess/Products.php:138–167 registra fallo de nonce pero continúa llamando a import_product; 298–299 registra AJAX autenticado y no autenticado. Exigir rechazo inmediato, capacidades de edición por objeto, validación de entradas y pruebas negativas.
- Alta: clasess/models/ProductsModel.php:293–313 usa publish para nuevos productos y permite sincronizar existentes; 426–463 actualiza precio, stock y metadatos con token. Exigir borradores inertes, revisión explícita y CRUD, sin tocar catálogo ajeno.
- Alta: clasess/Woocomerce.php:124–173 envío manual, comprobación current_user_can comentada en 150; 227–245 acción masiva; 293 hook de cambio de estado. Exigir permiso por pedido, método POST, nonce, liquidación, idempotencia duradera y bloqueo de envío automático. Condiciones completas del hook y modelo de órdenes aún por revisar.
- Alta: clasess/Dropi.php:199–219 desactiva sslverify en petición; exigir TLS verificado, timeouts acotados y control de redirecciones en todas las rutas.
- Alta: clasess/models/TokenModel.php:31–59,67–70 consultas SQL concatenadas; exigir consultas preparadas y revisión completa de flujos de datos. No se ha probado explotabilidad.
- Alta: wc-dropi-integration.php:28–36 y TokenModel.php:81–85 guardan token en texto claro; ProductsModel.php:463 replica por producto. Exigir almacenamiento y acceso restringido, no replicar secreto, rotación y control de backups/logs/exportaciones.
- Operativa: Dropi.php:159–162 retorna inmediatamente; 269–276 puede programar cron cada cuatro horas, pero no sincroniza con esa función.
- Compatibilidad pendiente: Woocomerce.php:80–103 usa metadatos directos de pedidos, y hooks de columnas/listas clásicos; revisar HPOS. StatesPlaces.php modifica campos de direcciones/ciudad; validar Checkout Blocks y DANE. No se ejecutó el plugin.
- Seguridad de dependencias, XSS, código JS, REST, serialización, logs y rutas de red: revisión exhaustiva pendiente. No extrapolar hallazgos a versiones futuras.

## Decisión

Solicitar a Dropi versión corregida y contrato de API autorizado para integración propia, con token de alcance mínimo y entorno sin efectos reales. No asumir que token de Dropify permite una API personalizada. No instalar la versión auditada en dev ni producción; no usar token real para pruebas. Si el proveedor propone versión nueva, fijar hash y repetir auditoría, pruebas aisladas sin egress, HPOS, Checkout Blocks, permisos, publicación, stock y pedidos. Evitar mantener un fork comercial sin confirmar licencia, soporte y contrato. Bakatá Core permanece como capa de control; la integración comercial continúa bloqueada. El token debe permanecer bajo custodia del usuario, no en Git, chat ni logs.
