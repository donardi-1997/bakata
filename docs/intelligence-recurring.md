# INT-13 — Capturas comerciales recurrentes autorizadas

Se incorpora un programador explícito para Store API, separado de la cola de fixtures INT-08. No se instala cron, daemon, timer ni perfil de red. No existe fuente real habilitada. Se utiliza la misma base de recibos INT-11 y el archivo comercial INT-12, ambos locales y privados. No se conecta a WordPress ni se crean productos.

## Puertas de activación

Requiere entrega integrada y CI verde, piloto INT-11 exitoso con captura efectivamente almacenada (mismo host, fuente, adapter, digest y hash), permiso expreso adicional para frecuencia recurrente, revisión vigente de condiciones y robots, IP pública aprobada, egress restringido y host Linux aislado. La referencia de autorización es una anotación local confiable, no una firma ni verificación de permisos. No ejecutar contra la tienda principal o proveedor sin aprobación.

El manifiesto INT-11 debe estar habilitado y su digest exacto confirmado durante configure. La autorización de recurrencia identifica frecuencia y presupuesto revisados por el operador. Cada tick revalida el manifiesto y su digest; cambiarlo o vencerlo impide nuevas solicitudes. No se renueva ni se resetea una programación registrada, incluso agotada o deshabilitada. La renovación supervisada, revocación persistente y conciliación operativa están pendientes.

## CLI (procedimiento futuro, no activado)

Desde services/intelligence, con bases existentes distintas, resultado previo autorizado y manifiesto revisado:

```sh
python3 -m intelligence.recurring --ledger /ruta/privada/pilot.sqlite --archive /ruta/privada/commercial.sqlite configure --manifest /ruta/privada/pilot.json --confirm DIGEST_APROBADO --approval-ref REFERENCIA_RECURRENCIA --interval 21600 --attempts 2
python3 -m intelligence.recurring --ledger /ruta/privada/pilot.sqlite --archive /ruta/privada/commercial.sqlite tick --manifest /ruta/privada/pilot.json
python3 -m intelligence.recurring --ledger /ruta/privada/pilot.sqlite --archive /ruta/privada/commercial.sqlite list
python3 -m intelligence.recurring --ledger /ruta/privada/pilot.sqlite --archive /ruta/privada/commercial.sqlite inspect
python3 -m intelligence.recurring --ledger /ruta/privada/pilot.sqlite --archive /ruta/privada/commercial.sqlite disable DOMINIO_AUTORIZADO
```

Configure y list no contactan fuentes. Tick procesa como máximo una captura vencida, no recupera intervalos perdidos en ráfaga y no ejecuta antes del vencimiento programado. Un futuro timer autorizado puede invocarlo, pero no se proporciona instalación automática. El primer vencimiento está al menos un intervalo después de configurar; los siguientes se calculan a partir de la finalización de la captura, sin retroceso. Se exige reloj UTC confiable.

## Límites y semántica

- Una programación por hostname, hasta diez registradas en el ledger. Intervalo de seis a 24 horas y al menos tan estricto como las directivas de robots revisadas. Máximo cuatro intentos por registro, incluyendo errores. El número efectivo puede ser menor: robots caduca como máximo 24 horas tras revisión y solo se programa dentro de esa ventana.
- Una única reserva running en el ledger, mediante BEGIN IMMEDIATE e índice único. El intento y descuento del presupuesto se guardan antes de la red. Un proceso interrumpido deja reserva incierta que impide nuevas capturas del mismo ledger; no se reclama automáticamente. No protege frente a operadores que usan otra base, otros hosts o herramientas; no es un limitador distribuido.
- Una GET a ruta fija Store API con IP fijada, TLS, límite 512 KiB, hasta 100 productos y timeout de socket 10 s. CLI Linux con alarma 45 s para el proceso completo. Sin redirects, reintentos, paginación, credenciales ni proxy.
- 403, 429, otro error HTTP, DNS/TLS, respuesta inválida, autorización vencida durante ejecución o error de archivo bloquean o impiden la captura. El estado bloqueado no tiene reintento automático. Si el manifiesto vence antes del tick, se rechaza la ejecución sin cambiar el registro; list muestra el estado persistido, no una autorización actual.
- La captura se confirma primero en CommercialStore, luego se marca evento succeeded en ledger. No hay transacción distribuida: si se interrumpe entre ambas bases, conciliar por manifest digest, fuente, tiempo y hash antes de decidir cualquier operación. Nunca borrar el ledger para reintentar.
- disable impide futuros ticks de un registro enabled, pero no cancela una solicitud iniciada ni resuelve una reserva incierta.

## Inspección local de interrupciones (Sprint 03)

`inspect` abre ambas bases existentes en modo SQLite de solo lectura, sin inicializar ni migrar esquemas y sin contactar la red. Para cada programación `running`, muestra el intento reservado, presupuesto restante y candidatos archivados con host, fuente, adapter Store API y digest de manifiesto coincidentes, observados desde el inicio de la reserva. Expone ID, fecha y hash validados, pero no URL, host ni fuente; no compara el hash con un hash del intento, porque la reserva no lo registra. Los digests son metadatos privados y deben tratarse como tales.

`absent` significa únicamente que no se encontró un candidato local: **no implica que no se haya enviado una solicitud**, ni que no haya existido una captura perdida. `unique` indica un solo candidato, no prueba de identidad; `ambiguous` indica varios. Una reserva ausente, duplicada o incoherente se informa como `inconsistent`. No hay límite superior temporal fiable en la reserva, por lo que capturas posteriores independientes también pueden aparecer. Un reloj incorrecto o archivos incompletos pueden ocultar evidencia.

El ledger actual no tiene identidad de aplicación propia: se exige `application_id=0`, `user_version=0` y las tablas requeridas. El archivo debe tener el `application_id` de CommercialStore y versión 1 o 2; no se migra. Estas comprobaciones y los formatos esperados (digest hexadecimal, fecha UTC, límites de intentos) son invariantes estructurales, **no autentican las bases ni sus registros**: una base alterada puede falsificar evidencia válida. Como máximo se examinan 11 filas de reservas y 101 capturas coincidentes por reserva, se devuelven hasta 100 candidatos y se aplica un presupuesto de instrucciones SQLite; al exceder un límite de filas se informa `truncated`, nunca `unique` ni `absent`. Si una consulta excede el presupuesto o los datos son inválidos, la inspección falla con error genérico sin incluir contenidos ni rutas. La función de Python instala temporalmente límites e interceptores de progreso en conexiones independientes y sin transacción; no debe usarse con un interceptor de progreso previo.

Antes de devolver incluso una lista vacía se comprueba que existan las columnas necesarias en ambas bases. Para cada reserva se revisa un historial acotado: intentos consecutivos y cronológicos, todos los anteriores `succeeded` (un `failed-review` bloquea el flujo), y la reserva actual debe ser el último evento. Además, intento actual más presupuesto restante no puede superar cuatro; si no se cumplen estas reglas se informa `inconsistent`. El presupuesto inicial no se conserva, por lo que no se puede verificar si el restante corresponde exactamente al autorizado ni demostrar que una secuencia aparentemente válida ocurrió realmente. Tampoco se verifica aquí que cada evento previo tenga captura archivada ni que sus próximos vencimientos fueran correctos. El límite de 101 capturas se aplica **antes** del filtro de fecha, por lo que capturas antiguas pueden provocar `truncated` aunque haya pocos candidatos posteriores.

El modo de solo lectura lo garantiza la CLI al abrir las conexiones con `mode=ro`. La función Python también acepta conexiones de lectura y escritura: ella misma solo consulta, pero no impide que otro código escriba usando esas conexiones.

Las lecturas de ledger y archivo no constituyen una instantánea distribuida: un proceso concurrente puede estar guardando o finalizando mientras se inspecciona. Detenerlo y revisar de nuevo bajo supervisión; incluso entonces el resultado no autoriza ninguna acción. La inspección nunca resuelve ni desbloquea la reserva, devuelve presupuesto o reintenta. La conciliación y cualquier recuperación siguen pendientes de diseño y autorización; conservar ambas bases.

## Validación

Diez pruebas unitarias sintéticas, transport mock, bases temporales: exige piloto archivado, evita duplicar registros, respeta frecuencia y presupuesto, no acumula intervalos, bloquea ante 429, interrupción y fallo de persistencia, verifica digest, vencimiento y políticas. CI existente descubre estas pruebas. No hay resultados de rendimiento comercial, egress real, DNS de proveedor ni datos reales. Antes de habilitar recurrencia: autorización real, política de retención y renovación/revocación, operación de conciliación, prueba de carga y supervisión de infraestructura. INT-14 calibrará scoring con evidencia revisada; no inventar métricas reales.

## Corrección de CI

La ejecución 45915254636 pasó las 94 pruebas de Intelligence, incluidas las diez pruebas de recurrencia, así como TLS local, persistencia, aislamiento, contrato PHP y smoke de WordPress. Falló al instalar dependencias de Chromium: APT recibió HTTP 403 de packages.microsoft.com para Ubuntu 26.04 resolute. Se fija únicamente el job checks a ubuntu-24.04 LTS para estabilizar la plataforma de QA; se conserva Playwright con --with-deps, la verificación de paquetes y todas las pruebas. No se modifica el job deploy_dev ni se considera confirmada la solución hasta que la nueva ejecución pase.
