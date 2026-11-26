# Dropify 4.7.3: hardening de código fuente

El generador local acepta exclusivamente el ZIP auditado (SHA-256 fijado) y escribe una copia nueva sin instalarla. No se almacena el ZIP de terceros en Git.

## Uso en entorno aislado
    python3 scripts/harden-dropify.py /ruta/original.zip /ruta/dropify-patched.zip
    unzip /ruta/dropify-patched.zip -d /ruta/aislada
    find /ruta/aislada -name '*.php' -exec php -l {} \;
    php scripts/test-dropify-hardening.php /ruta/aislada/wc-dropi-integration

No instalar en producción; mantener aislamiento de red y no introducir token real.

## Alcance
- Siete solicitudes HTTP verifican TLS y no siguen redirecciones.
- Importación POST exige manage_options y nonce válido; rechaza ID inválido antes de consultar el proveedor.
- Consulta de productos exige manage_options y nonce; solo devuelve campos utilizados por el selector, no todos los metadatos.
- Despacho manual exige manage_woocommerce y nonce; se eliminan tres registros AJAX anónimos.
- Productos nuevos se crean como borradores; las variantes conservan su estado original. La vinculación a existentes no cambia por este parche.
- Se eliminan 27 llamadas de logging del modelo de pedidos y un echo de excepción; no implica eliminación de todos los datos sensibles en otros modelos, metadatos o logs históricos.

## Verificación local
Sobre la copia del ZIP suministrado, se modificaron cinco archivos, se validaron los 35 PHP con PHP 8.4.24 y pasaron ocho casos de rechazo con stubs PHP (no WordPress real). Se rechazó un archivo de hash incorrecto. El generador enviado a GitHub acumula las entradas antes de escribir la salida, a diferencia del prototipo local, para evitar escribir un ZIP parcial si falla una sustitución.

## Bloqueos restantes
No es una certificación de seguridad. Falta revisar otros endpoints (incluidos flujos GET y bulk), permisos por objeto, validación de datos, XSS en interfaz, almacenamiento y rotación de tokens, mensajes de error persistidos, metadatos de productos, logs de otros modelos, despacho automático y concurrente, HPOS y compatibilidad con las versiones reales de WordPress/WooCommerce/PHP 8.3. La instalación y las pruebas positivas requieren entorno descartable con egress bloqueado, y después un sandbox autorizado. El pipeline CD normal solo despliega las herramientas inertes, nunca el plugin externo.
