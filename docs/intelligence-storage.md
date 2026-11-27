# INT-12 — Persistencia de datos comerciales

Se incorpora CommercialStore, archivo SQLite independiente de la cola INT-08, del ledger INT-11 y de WordPress. Sin conexión de red nueva ni cambios en Compose o Lightsail. Inicialización transaccional de esquema v1 con application_id, user_version y claves foráneas; se rechazan bases desconocidas y versiones no compatibles. No existe todavía migración desde una versión anterior: las observaciones en memoria de INT-01 no se importan automáticamente.

## Modelo y contratos

- sources: identidad estable por fuente, host y adaptador. No implica autorización permanente; cada captura exige registro revisado vigente.
- products: identidad compuesta fuente/ID externo, no SKU global ni entidad canónica.
- captures: ID determinista de fuente, URL y fecha UTC; hash SHA-256 de bytes originales, tamaño, número de filas, referencia y vencimiento de autorización, identificador explícito JSON-LD cuando corresponde y digest opcional del manifiesto piloto. No guarda respuesta cruda ni credenciales. La captura vacía sigue siendo registrable. El hash no acredita autenticidad ni permite reconstruir el cuerpo.
- observations: título, URL, moneda, precio en unidades menores o null, fecha UTC; conserva cada observación. capture_observations vincula una observación a una o varias capturas con FK.
- evaluations: registro inmutable por ID de revisión a través de la API, actor referenciado, insumos, rúbrica, resultados recalculados y hash del JSON canónico. Decimal como cadena y duración en microsegundos. No acepta score total arbitrario; una revisión nueva usa otro ID.
- equivalences: vínculo entre observaciones exactas, evidencia de atributos, confirmación explícita de variante, resultado de las reglas INT-04 y referencia de revisión. No fusiona productos ni infiere transitividad. No selecciona automáticamente una revisión vigente ni implementa revocación.

Los actores y referencias de autorización son anotaciones de operadores locales confiables, no identidad autenticada ni firma. El hash de revisión detecta alteraciones accidentales del payload, no protege frente a quien puede modificar toda la base. No guardar datos personales ni información confidencial; antes de uso real verificar y minimizar los datos de fuente.

## Operaciones

CommercialStore.ingest(registry,capture,now=...) vuelve a interpretar los bytes autorizados con INT-03 y persiste todo el lote bajo BEGIN IMMEDIATE. Replay exacto devuelve el mismo ID y cero observaciones nuevas; conflicto de captura u observación revierte todo. La autorización debe ser vigente cuando se procesa; SourceSpec no acredita la fecha original de concesión, por lo que el operador debe comprobar permiso durante la captura. No se modifica el histórico. history(source,external_id,start=...,end=...,limit=...) consulta intervalo UTC semiabierto y exige estrecharlo si supera el límite, sin truncar. provenance(key) consulta evidencia de captura. record_evaluation y record_equivalence ejecutan validación y cálculo de INT-06 e INT-04 respectivamente; review devuelve el registro verificando hash. No hay interfaz remota ni CRUD de catálogo.

Desde INT-12, el comando execute del piloto requiere --archive con una ruta privada distinta del --ledger. El piloto persiste captura y observaciones antes de marcar recibo succeeded. Las dos bases no forman una transacción distribuida: si ocurre una interrupción entre escrituras puede quedar una captura válida y recibo reserved/failed-review. Conciliar por fuente, manifiesto y hash; nunca repetir la solicitud automáticamente. El CLI no se activa ni se programa en producción.

## Capacidad y conservación

Límites iniciales: 10.000 capturas, 100.000 observaciones, 20.000 evaluaciones y 20.000 equivalencias, 32 KiB por payload de revisión, 320 MiB para archivo principal SQLite (max_page_count por conexión). El primer límite alcanzado bloquea nuevas escrituras. El límite de archivo no es cuota del volumen y no incluye journals, temporales ni backups; no hay borrado automático. Consultas de historial y procedencia acotadas a 1.000 registros. Uso de SQLite local con un escritor transaccional; no usar en filesystem de red ni compartir con la cola.

Retención provisional: conservar histórico sin sobrescribir, revisar capacidad semanalmente, detener nuevas capturas al límite y acordar con responsable plazo y finalidad antes de archivar o eliminar. No se implementa todavía limpieza/retención automatizada ni cifrado propio. Usar directorio privado y permisos restrictivos, cifrado de volumen y respaldos fuera de Git. Para respaldo consistente usar SQLite Backup API, comprobar integrity_check y foreign_key_check, restaurar a una ruta nueva y revisar capturas, observaciones y revisiones antes de reanudar. Respaldar también ledger por separado con procesos detenidos. No copiar a ciegas bases abiertas ni resetear recibos.

## Validación

Nueve pruebas del archivo verifican reapertura/versionado, provenance, desconocidos, histórico, replay, rollback, capacidad, conflicto de fuente, integridad referencial y revisiones recalculadas. Dos pruebas adicionales del piloto verifican persistencia antes del recibo y bloqueo de éxito ante error de archivo. CI existente descubre los tests sin acceso comercial. No se han ejecutado pruebas con datos reales ni aplicado migraciones en Lightsail. CI acumulativo pendiente. INT-13 deberá enlazar captura programada con controles de autorización, frecuencia y egress; no reutilizar el piloto single-use como mecanismo de scraping recurrente.
