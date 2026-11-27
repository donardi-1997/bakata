# INT-18A — Procesamiento incremental y recuperable

Primera etapa de escalabilidad sobre INT-17D ya integrado. No amplía la cola fixture de INT-10 ni activa cron, daemon, captura remota, notificaciones o escrituras WooCommerce. Usa el motor de priorización existente sobre tres archivos locales read-only.

## Operación

Crear un identificador nuevo para cada recorrido y política explícita (valores ilustrativos):

    cd services/intelligence
    python3 -m intelligence.batch_runs --db /privado/batches.sqlite create --run-id RUN --alerts /privado/alerts.sqlite --bridge /privado/bridge.sqlite --commercial /privado/commercial.sqlite --archive-ref ARCHIVO --store 7 --price-threshold-bps 500 --min-score-bps 7500 --min-margin-bps 2500 --batch-size 10

Consultar status --run-id RUN para obtener checkpoint_sha256 (64 ceros al inicio). Ejecutar un solo lote:

    python3 -m intelligence.batch_runs --db /privado/batches.sqlite step --run-id RUN --alerts /privado/alerts.sqlite --bridge /privado/bridge.sqlite --commercial /privado/commercial.sqlite --expected-checkpoint-sha256 DIGEST

Repetir manualmente con el último checkpoint hasta completed. Consultar page --run-id RUN --sequence N para obtener el informe archivado. Un lote sin candidatos puede avanzar: el cursor recorre identidades con alertas, incluso si están resueltas. No se descarta ese checkpoint. Si la respuesta se pierde, consultar status antes de reintentar; no volver a usar el digest anterior.

## Límites y recuperación

1–10 identidades por paso, hasta 1 MiB de JSON por página, 50 recorridos, 2.000 páginas totales y presupuesto de 128 MiB del archivo principal. El CLI de Linux termina un paso a los 45 s (SIGALRM); SQLite revierte la transacción no confirmada al recuperar el archivo. Un único escritor por archivo mediante BEGIN IMMEDIATE y espera máxima SQLite de 5 s por bloqueo. No hay reintento automático ni lease de efectos externos. El resultado y cursor se insertan juntos; el digest esperado evita repetir un paso confirmado desde un checkpoint antiguo. Historial append-only y cadena de hashes; status comprueba las últimas dos páginas y continuidad numérica, no audita toda la cadena. Los hashes no autentican ni detectan truncado completo sin anclaje. No se elimina información automáticamente al alcanzar un límite.

El CLI vincula el recorrido a ruta resuelta, dispositivo e inode de los tres archivos; una sustitución/restauración de archivos requiere un nuevo recorrido. No es identidad criptográfica del contenido y no sustituye permisos privados; evitar modificaciones o sustituciones concurrentes de rutas. La base se mantiene separada de evidencia, con umask 077; no corrige permisos previos. El límite no incluye journal, temporales ni backups. No se promete límite de RAM o CPU estricto, rendimiento medido ni aislamiento global. El procesamiento por página usa el tiempo real de cada paso: el catálogo o las alertas pueden cambiar entre páginas, incluyendo inserciones detrás del cursor. El estado completed significa fin del recorrido local, no cobertura total, snapshot consistente o ranking global. Para una evaluación comparable entre páginas, trabajar sobre copias privadas coherentes y documentar su instante; nunca usar resultados antiguos para autorizar acciones.

Pruebas sintéticas sobre los motores existentes: persistencia de página, reanudación tras excepción, paginación, checkpoint obsoleto, página filtrada vacía, ámbito, cronología, inmutabilidad y cursor inválido. Pendiente medir rendimiento bajo carga y ensayar interrupción real con procesos independientes. INT-18B añadirá índices y pruebas de carga reproducibles; INT-18C límites de ejecución y pruebas de recuperación operacional.
