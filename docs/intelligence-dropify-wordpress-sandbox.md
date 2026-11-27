# INT-15F — Instalación aislada de WordPress

## Objetivo

Validar el ZIP endurecido exacto con WordPress, WooCommerce y MariaDB reales antes de considerar una sustitución en dev. El workflow de paquete existente incluye una prueba en runner hospedado desechable, no otro workflow por commit. Solo las descargas públicas del ZIP auditado, WooCommerce y las imágenes Docker ocurren antes de crear el entorno interno. WooCommerce se obtiene de la distribución estable pública (versión no fijada); se debe revisar cualquier incompatibilidad futura.

La instalación de prueba no usa backups, pedidos, clientes, token real ni volumen de dev. Red Docker --internal, ningún puerto publicado, volúmenes nuevos y retirada al terminar. MU plugin exclusivamente de fixture intercepta todo WP HTTP, devuelve una respuesta sintética solo para el destino esperado y comprueba que la reserva existe antes de responder. No empaquetar ni instalar el MU plugin en dev. Los valores sintéticos y las credenciales de prueba no son datos comerciales. No hay conexión con Dropi.

## Pruebas

- Activar WooCommerce y el ZIP construido; comprobar que no se crea ni migra tabla de tokens en activación.
- Crear una tabla de tienda sintética y una cuenta administrador y otra suscriptor.
- Login HTTP local y menú real: lectura deshabilitada de forma predeterminada, suscriptor rechazado, nonce inválido, una consulta autorizada y reenvío bloqueado.
- Comprobar TLS, sin redirecciones, límite y cuerpo en la llamada interceptada; bloquear otras solicitudes, detectar hooks comerciales registrados y no exponer canarios en HTML/snapshot.
- Verificar reserva única en MariaDB, ausencia de productos publicados/borradores u órdenes en proceso y persistencia del snapshot en BridgeArchive. La prueba no certifica todas las posibles mutaciones ni carrera concurrente; solo un reenvío secuencial. No mide TLS real ni egress de dev.
- Publicar artefacto de paquete solo si todas las pruebas acumulativas y esta instalación pasan.

## Evidencia operativa previa

El PR #57 se fusionó. Se comprobó el servidor dev por SSM: los 53 archivos Dropify coincidían con el ZIP original. El respaldo de la madrugada no contenía Dropify. Se generó un nuevo punto 2026-11-27 01:12:40 UTC (26 nov 20:12 Colombia), verificando cinco checksums, permisos privados, 53 archivos y presencia de tabla de configuración. La primera prueba SQL aislada falló; la segunda restauró 53 tablas en MariaDB temporal sin red ni volúmenes activos y eliminó el contenedor. No se probó recuperación integral de archivos ni arranque de un clon real con ese backup. No se alteró el conector activo ni se consultó al proveedor.

## Siguiente gate

CI verde y revisión de resultados; prueba de rollback/restauración de archivos, revisión de egress y rotación coordinada de credenciales si corresponde. La sustitución del plugin operativo requiere decisión expresa, porque catalog-only deshabilita despacho/importación y no es una actualización normal de tienda. La primera consulta real requiere permiso de proveedor y operador para el alcance; no automatizar ni usar endpoints privados aparte del propio conector autorizado.

## Corrección de regresión HTTP

La primera ejecución real instaló y activó ambos plugins, pero falló la aserción HTTP de nonce inválido. Se añade una puerta de autorización en admin_init antes de renderizar el administrador, preservando las verificaciones existentes de vista y modelo. Las pruebas de nonce inválido, ausente y no escalar no siguen redirecciones de administración y verifican que no se consume la autorización ni se produce una solicitud simulada. La causa exacta del primer código HTTP no quedó registrada; la nueva prueba imprime solamente el código de estado si falla.
