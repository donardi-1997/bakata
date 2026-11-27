# INT-08 — Automatización de trabajos offline

Se añade una cola SQLite persistente y una CLI de ejecución explícita. Solo existe el tipo fijo fixture-snapshot, que ejecuta el exportador sintético INT-07. No hay llamadas HTTP, comandos arbitrarios, publicación de productos, cron instalado ni daemon activo. No modifica Compose de la tienda.

## Ejecución local

Desde la raíz:

```sh
docker compose -f services/intelligence/compose.yaml --profile jobs build scheduler
docker compose -f services/intelligence/compose.yaml run --rm -T scheduler enqueue demo-001 --due 0
docker compose -f services/intelligence/compose.yaml run --rm -T scheduler run-once
docker compose -f services/intelligence/compose.yaml run --rm -T scheduler list
docker compose -f services/intelligence/compose.yaml run --rm -T scheduler events demo-001
docker compose -f services/intelligence/compose.yaml run --rm -T scheduler result demo-001 > intelligence-preview.json
```

El JSON resultante puede cargarse manualmente en el panel INT-07. La fecha del contenido sigue siendo la fixture, no la fecha de ejecución.

Programación recurrente explícita (epoch UTC en segundos):

```sh
docker compose -f services/intelligence/compose.yaml run --rm -T scheduler schedule demo-hourly --interval 3600 --first-due "$(date +%s)"
docker compose -f services/intelligence/compose.yaml run --rm -T scheduler tick
docker compose -f services/intelligence/compose.yaml run --rm -T scheduler run-once
docker compose -f services/intelligence/compose.yaml run --rm -T scheduler disable demo-hourly
```

tick crea trabajos vencidos; run-once reclama y procesa como máximo uno. Deben invocarse por un operador o un futuro cron/timer autorizado. Deshabilitar una programación impide nuevos trabajos, no cancela los pendientes. Repetir enqueue requiere el mismo ID y fecha original para idempotencia; no se reusa un ID terminal.

## Garantías y límites

- SQLite local con transacciones BEGIN IMMEDIATE, índice único de trabajo running y token aleatorio por intento. Una reserva válida por base; finalización y resultado/evento son atómicos. Los workers vencidos no pueden confirmar resultados. Esto no garantiza detener un proceso antiguo ni exactamente una ejecución física; la fixture es pura y no produce efectos externos. Sin heartbeat ni deadline de proceso; requeridos antes de tareas reales.
- Lease de 60 segundos, máximo tres intentos (uno inicial y dos reintentos), backoff 30/60 segundos. Recuperación de reservas vencidas al reclamar. Error terminal registrado con código fijo, sin stack traces ni secretos. Reloj UTC del host confiable; no se modelan saltos abruptos del reloj.
- Intervalos 300–86400 segundos, máximo diez programaciones, una pendiente por programación. Si se pierden intervalos, se consolida al último vencido; no se reproducen todos. Si ya hay un trabajo pendiente se omite ese nuevo intervalo.
- Máximo 1000 trabajos totales y resultado de 256 KiB por trabajo. La cola rechaza nuevas entradas al alcanzar el límite; no borra historial ni implementa retención automática. SQLite y sus índices tienen sobrecoste de almacenamiento; estos límites no son una cuota de disco.
- Perfil Docker jobs opt-in, volumen job_data separado, usuario 65532, root filesystem de solo lectura, red deshabilitada, 128 MiB RAM, 0,5 CPU, 64 procesos. El volumen conserva datos entre contenedores; down -v lo elimina. No usar ese comando en una instalación con datos que deban conservarse. CI lo usa solo en su entorno desechable.
- El resultado se genera desde el código local; no existe carga de resultados arbitrarios mediante API. La validación del resultado en la cola es de modo/esquema y tamaño; el panel aplica su propio contrato más estricto. No se autentican usuarios externos ni se conecta el programador a WordPress.

## Validación

Ocho pruebas unitarias: idempotencia, persistencia, exclusión concurrente, recuperación y fencing, backoff, programación, separación de IDs y validación de límites. CI añade smoke con contenedores separados: enqueue, ejecución, listado y resultado persistente. Pendiente confirmar CI. Antes de activar automatización real: reconciliar fases en main, definir retención/cuota de disco, migraciones y backups, supervisión y deadlines, revisar autorización y egress, integrar un programador operativo explícitamente autorizado. INT-09: importación controlada a borrador mediante Bakatá Core, sin publicación automática.
