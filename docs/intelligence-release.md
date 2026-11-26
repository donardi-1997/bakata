# INT-10 — Validación y despliegue controlado

## Reconciliación

Los PR #41–49 figuran fusionados y sus últimas ejecuciones individuales de CI fueron exitosas. Sin embargo, en main 8d8dc78e9fe53d3889b2ec53b6f2d94dfdee637c únicamente estaba presente INT-01: las fusiones apiladas integraron cambios en ramas intermedias y no en main. Se recuperan 36 archivos faltantes o divergentes del árbol validado de INT-09 (3f3b7951f9b314441a28970aaa2f1072f62ac533), se añaden las inclusiones de Bakatá Core y se reconcilian exclusivamente los pasos Intelligence del CI, preservando las pruebas de storefront, rendimiento/SEO y el despliegue protegido existente. No se modifica la configuración de producción ni el Compose de la tienda.

## Controles de esta entrega

- Cola: límite del archivo principal SQLite de 320 MiB por conexión mediante max_page_count, además de 1000 trabajos y resultados de 256 KiB. No es cuota total del volumen: journal, temporales y respaldos consumen espacio adicional. El CLI usa umask 077; el worker one-shot de Linux tiene alarma de 45 s, inferior al lease de 60 s. Una terminación abrupta deja una reserva recuperable; no garantiza detener procesos externos ni se habilitan subprocesses de scraping.
- Prueba integral sintética de captura CSV autorizada, hash de evidencia, persistencia idempotente, normalización, equivalencia explícita, comparación y scoring; complementa las pruebas existentes de transporte y exportación. La segunda ruta de CI conserva el snapshot sintético de la cola, valida contrato Python/PHP, ejercita panel y crea un borrador inerte con aprobación simulada. No es todavía una única tubería de datos reales de extremo a extremo.
- Prueba de respaldo/restauración mediante SQLite backup e integrity_check en base temporal; verifica resultado y eventos. No crea respaldos operativos ni restaura volúmenes de producción.
- Probe de runtime en ambos contenedores: UID/GID, sistema de archivos de aplicación read-only, solo loopback, sin capabilities efectivas, no-new-privileges, cgroup v2 de 128 MiB, 0,5 CPU y 64 procesos. Reporte de RSS del probe, no benchmark de carga. CI valida ausencia de servicios Intelligence en Compose principal y que scheduler sea opt-in.
- Todos los tests son bloqueantes; se conservan QA y checks del resto de la tienda. Los reportes de runtime se guardan en el artefacto QA de CI. No se cambia el workflow de despliegue protegido.

## Política provisional de operación offline y recuperación

El volumen job_data es independiente. Conservar historial de trabajos por defecto, sin borrado automático ni reutilización de IDs. Revisar capacidad y antigüedad semanalmente, alertar al llegar a 80% del límite de trabajos o del archivo principal y detener nuevas programaciones al llegar al límite. No existe alertador ni retención automatizados todavía. No ejecutar down -v sobre datos que deban conservarse. Antes de operar permanentemente: cuota de volumen con espacio para journals, respaldos verificados y política aprobada de archivo/retención; decidir RPO/RTO con el responsable. Propuesta inicial (no SLA): copia diaria cifrada y restauración ensayada antes de cada cambio de esquema, retención de 30 días previa aprobación.

Procedimiento de recuperación: detener invocaciones tick/run-once y confirmar que no haya procesos activos; obtener copia consistente con SQLite Backup API desde una conexión confiable, no copiar a ciegas una base abierta; comprobar integrity_check y restaurar en archivo/volumen nuevo sin sobrescribir el original; revisar lista, resultados, eventos y reservas vigentes antes de reanudar. No reintentar importaciones WooCommerce con recibos pendientes/fallidos sin inspección del producto y del recibo. La prueba automatizada verifica solo la recuperación de SQLite, no backups WordPress ni recuperación AWS.

## Puertas de liberación

**Entrega offline experimental:** PR acumulativo aprobado, checks verdes sobre commit integrado, SHA de main verificado, pipeline protegido exitoso y SHA desplegado confirmado si CD está habilitado. Verificar menú admin solo autorizado, ningún servicio jobs activo, ningún puerto nuevo, ningún producto comercial nuevo. Si falla, detener promoción y usar el mecanismo existente de rollback con revisión de compatibilidad de datos; nunca borrar volúmenes o revertir a ciegas. El servicio Python no forma parte del Compose de la tienda.

**Activación comercial:** bloqueada. Requiere fuente expresamente autorizada y revisión vigente de condiciones/robots, prueba controlada de TLS/transporte y deadline DNS/HTTP, firewall egress y rate limiting coordinado, dependencias e imagen base con digest y revisión de vulnerabilidades, gestión de secretos, persistencia de evidencia y revisores autenticados, datos reales calibrados, precio/impuestos/logística validados, importación comercial con capacidad específica, conciliación de recibos y variantes, pruebas de concurrencia de terceros, límites/retención/backup, prueba de carga en Lightsail y aprobación explícita. No usar endpoints privados de Dropi ni publicar productos automáticamente.

El CI acumulativo, revisión manual y despliegue no se consideran confirmados por el mero éxito individual de #41–49. INT-10 prepara la entrega offline y sus criterios; no declara listo para uso comercial.
