# Contrato de diseño: entrega mTLS fixture en Fargate — NO-GO

Este documento no implementa entrega, controlador, IAM ni despliegue. La definición
`infra/research-aws/proxy-task.json` es inerte a propósito: un contenedor, sin
task role, volumen ni secretos, y sin configuración mTLS completa. El execution
role solo cubre pull y logs. No se ha probado nada en AWS. El mTLS actual y sus
pruebas son locales; el servidor además exige SHA-256 exacto del certificado
cliente DER. No usar esta propuesta para datos o proveedores reales.

## Alternativa a evaluar, no receta operativa

Para cada ejecución, un emisor de confianza independiente podría generar una CA
exclusiva, una pareja servidor y otra cliente, con vigencia corta y usos
serverAuth/clientAuth respectivamente. Nunca distribuir la clave privada de CA.
El SAN del servidor debe coincidir con el nombre que verifica el cliente; el
pin es el hash DER del certificado cliente exacto, no de la clave ni del PEM.
Los nombres y el pin no sustituyen la verificación de CA y nombre. No reutilizar
identidad entre runs; negar cualquier arranque parcial, expirado o inconsistente.

Una posible frontera para Fargate es que un controlador autorizado cree dos
secretos separados por run en Secrets Manager y que ECS los inyecte al arrancar
dos contenedores inicializadores diferentes, mediante `secrets` y execution
roles separados por definición y privilegios mínimos. Cada inicializador
escribiría su propio paquete en un volumen efímero compartido **solo dentro
de su propia tarea**, con permisos que permitan leerlo al UID del proceso
correspondiente; el contenedor de aplicación lo montaría de solo lectura. El
proxy recibiría CA pública, certificado y clave de servidor y pin cliente;
el worker CA pública, certificado y clave de cliente y nombre esperado del
servidor. Nunca compartir paquetes, volúmenes ni variables entre tareas.
Las variables inyectadas al inicializador siguen siendo legibles para procesos
privilegiados o con acceso de depuración y no ofrecen borrado seguro; no se
deben volcar al log, comandos, overrides, tags ni resultados. Evaluar tamaños,
formato, límites, dependencias de arranque, propiedades de volúmenes Fargate,
filesystem de solo lectura y compatibilidad real del cliente antes de diseñar
los artefactos. Esto es una hipótesis, no una implementación validada.

## Fronteras obligatorias y bloqueos verificables

* **Emisor/controlador:** identidad separada de ejecución; emitir únicamente
  fixture, controlar unicidad, vencimiento, correspondencia pin/certificado y
  registrar solo identificadores no sensibles. No usar claves compartidas ni
  cargar secretos de proveedor. Falta implementación y revisión del emisor.
* **Roles:** cada execution role solo puede leer su secreto de run y su clave
  KMS si corresponde, además de pull/logs necesarios; ningún task role debe
  leer secretos. Resolver cómo expresar permisos por run sin ampliar el acceso
  en roles compartidos ni permitir al controlador seleccionar arbitrariamente
  roles, secretos, imágenes, comandos o red. La autorización de `RunTask`,
  `PassRole`, registro de definiciones, overrides, ECS Exec y acceso a secretos
  debe revisarse conjuntamente, incluida la confianza de roles y políticas KMS.
  La definición actual no proporciona estas garantías.
* **Red y cliente:** endpoint privado de Secrets Manager, DNS, políticas de
  endpoint, SG, rutas y permisos deben revisarse; la red actual no demuestra
  conectividad a Secrets Manager. Cliente WordPress capaz de mTLS hacia proxy,
  verificación de nombre y CA y bind del proxy siguen pendientes. No se asume
  que la configuración CONNECT existente soporte TLS al proxy.
* **Ciclo de vida:** deadline externo y detención de ambas tareas incluso ante
  fallo parcial, duplicados, timeout o caída del controlador; reconciliación
  durable e idempotente con propiedad por run. La tarea detenida no demuestra
  borrado físico de memoria o almacenamiento. Secretos deben quedar
  inaccesibles inmediatamente mediante una frontera de autorización validada,
  y su eliminación programada o inmediata debe verificarse según las reglas
  reales del servicio; retención, réplicas, versiones, backups, auditoría,
  claves y costos requieren inventario. Fallo de limpieza implica incidente y
  bloqueo de nuevos runs, no éxito silencioso.
* **Validación pendiente:** revisión IAM/KMS y modelo de amenazas; pruebas
  autorizadas específicas de ECS/Fargate y Secrets Manager, fallos de
  inicialización, denegación cruzada, revocación y reconciliación; procedencia
  de imagen, presupuesto y plan de retirada. Hasta entonces no existe ruta
  live ni autorización para crear recursos o incurrir en gastos.

## Pruebas sin red

`python scripts/test-research-mtls-contract.py` comprueba la forma inerte de
la definición presente y un pequeño modelo de estados puramente sintético,
incluidas denegaciones cruzadas y fallos de limpieza. El modelo no implementa
AWS, criptografía, autenticación, políticas, limpieza ni seguridad real.
`services/intelligence/tests/test_research_proxy_auth.py` prueba por separado
handshakes locales con certificados efímeros si OpenSSL está disponible. En
esa prueba `VERIFY_X509_STRICT` se activa explícitamente solo en el cliente;
el contexto servidor exige certificado cliente y valida CA, pero no activa
explícitamente ese flag. El caso sin certificado contrasta la causa con BIOs
en memoria y comprueba el rechazo en loopback: asyncio puede exponer un reset
en vez de la alerta TLS. Esto no prueba Fargate ni un cliente real.
