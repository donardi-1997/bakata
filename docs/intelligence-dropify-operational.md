# INT-15E — Validación operativa

## Estado de partida

PR #56 integrado en main (f110fef958cb7e87bfbdfe25ef3648ca28c05d80), CI y deploy_dev 45919326230 exitosos. El despliegue conserva los volúmenes de WordPress y solo actualiza el código de Bakatá; no implica sustitución del Dropify activo ni prueba de conexión con proveedor. El ZIP 4.7.3 aportado coincide con la huella auditada.

## 1. Preflight local, sin mutación

En el servidor de desarrollo, seleccionar explícitamente un respaldo existente (no se crea ni borra ningún backup) y el ZIP original ubicado privadamente. Desde /home/ubuntu/bakata:

    sudo python3 scripts/dropify-dev-preflight.py --backup /var/backups/bakata/backup-FECHA_UTC --original /ruta/privada/wc-dropi-integration.4.7.3.zip

El comando exige root, directorio de respaldo privado, archivos regulares sin enlaces, manifiesto exacto de cinco archivos, fecha en las últimas 48h, SHA-256, compresión válida y commit. Ejecuta PHP CLI en el contenedor solo para inventario de huellas del plugin instalado, sin arrancar WordPress ni cargar sus credenciales. Compara todos los archivos del ZIP auditado con el árbol local y devuelve recuentos, no cuerpos, secretos, rutas de archivos individuales o datos comerciales. No verifica si el plugin está activo (comprobar por interfaz de Plugins), ni toda la seguridad del host, ni la copia S3. Ejecutarlo en ventana sin escrituras/actualizaciones concurrentes; las sumas verifican integridad, no consistencia transaccional o recuperación. El resultado live_query_ready=false es intencionado. Si el backup falla, revisar el servicio de respaldo existente, generar una copia mediante procedimiento autorizado y repetir. Antes de reemplazo, simular restauración en clon aislado según docs/infrastructure.md, con volúmenes nuevos y sin datos de cliente o credenciales reales en CI. No restaurar sobre dev activo. No afirmar restaurabilidad hasta completar el simulacro.

## 2. Paquete y control de solicitudes

Workflow Dropify catalog validation construye el ZIP a partir del original hash-pinned. Además de las suites anteriores, ejecuta 18 procesos PHP herméticos que invocan el método getProducts parcheado con transporte y base simulados: casos correctos (dos offsets), producción, GET, permiso, nonce, vencimiento, alcance, destino incorrecto, token ausente, fallo de reserva, transporte fallido, HTTP 403/429/302, JSON inválido, tamaño y cardinalidad. Verifica que se reserva antes de llamar y no repite, TLS y sin redirecciones, proyección sin canarios de token. No hay conexión real a Dropi. Se cambia add_option por INSERT en el índice único option_name de WordPress, sin upsert/caché; el stub prueba el contrato, no la carrera real con MariaDB. Se restringe este piloto a la URL colombiana ya definida por el conector y reject_unsafe_urls. No autoriza otras regiones ni añade un segundo cliente. Egress de infraestructura sigue siendo requisito separado.

## 3. Validación operativa autorizada

Solo después de CI verde, preflight, recuperación comprobada, clon aislado, aprobación del operador/proveedor y revisión de seguridad del token, seguir el procedimiento de docs/intelligence-dropify-catalog-bridge.md. No desactivar el bloqueo de cuarentena ni habilitar consultas hasta que exista una política egress específica revisada. No pasar credenciales por chat o GitHub. No instalar el ZIP en el sitio activo sin coordinación explícita. La primera consulta autorizada queda limitada a una página de diez filas, sin reenvíos; tras revisión se puede aprobar otra página si las condiciones y frecuencia lo permiten.

## 4. Comparación offline de paginación

Desde services/intelligence, con dos o tres snapshots autorizados y privados:

    python3 -m intelligence.dropify_pagination /ruta/privada/pagina1.json /ruta/privada/pagina2.json

Comprueba schema, tienda, tamaño y digest de búsqueda iguales, páginas consecutivas, referencias de aprobación distintas y capturas secuenciales recientes. La ventana de 30 min es un límite analítico, no una instrucción de frecuencia; si las condiciones autorizadas requieren más separación, no forzar la comparación. Detecta IDs solapados, orden no ascendente y página parcial antes de la siguiente. Devuelve hashes, recuentos y anomalías, sin IDs individuales. Incluso sin anomalías no certifica cobertura ni semántica remota de offset; validar con proveedor. No consultar más páginas para intentar evadir errores.

## 5–6. Persistencia y evaluación

Usar BridgeArchive ingest y candidates (ver INT-15D) para conservar snapshots aprobados. Reportar filas recibidas, observaciones nuevas y desconocidos, no extrapolar catálogo total. Revisar moneda COP, costo final independiente, identidad de cuenta/producto y disponibilidad vendible; solo después usar link-score con evaluación de CommercialStore vigente y mapeo explícito. No crear productos ni iniciar despacho.

## Límites de la entrega

Preflight y comparador implementados y pruebas sintéticas añadidas. No hay acceso directo confirmado al servidor o administración autenticada en esta sesión. No se ha verificado backup real, restaurado clon, sustituido plugin, consultado Dropi ni almacenado productos reales. La revisión de paginación es offline. La vinculación de scoring requiere observaciones reales y evaluaciones revisadas. El estado de CI debe comprobarse antes de fusionar.
