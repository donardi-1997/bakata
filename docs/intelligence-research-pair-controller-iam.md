# INT-18H.3c.2d — Frontera IAM del controlador de par (plantilla durmiente)

`infra/research-aws/pair-controller.json` declara, solo con `EnablePairController=true`, el ledger DynamoDB del par, el rol del controlador y la función Lambda `<stack>-pair-controller`. No crea programación, origen de eventos, URL de función ni permiso de invocación: solo un operador con `lambda:InvokeFunction` puede invocarla. Tampoco crea servicio ni definición de tarea. No se ha creado ningún stack.

## Handler Lambda

`research_pair_handler.handler` (`research_pair_handler.py`) ejecuta el controlador con el ledger DynamoDB:

- Responde `disabled` sin crear clientes salvo que `BAKATA_PAIR_CONTROLLER_ENABLED` sea exactamente `true`, y solo opera en `us-east-1`.
- **Toda la configuración procede del entorno del despliegue.** El evento solo puede ser `{"action": "supervise"}` o `{"action": "launch", "role": "proxy"|"worker"}`; cualquier otra clave se rechaza antes de crear clientes, de modo que el invocador nunca aporta ARNs, subredes, tabla ni nonce.
- `launch` exige además `BAKATA_PAIR_LAUNCH_ENABLED=true` (parámetro `EnablePairLaunch`, apagado por defecto); `supervise` no.
- Clientes con `total_max_attempts=1`, timeouts de 3/5 s y endpoints configurados por entorno ignorados (probado: un `AWS_ENDPOINT_URL` hostil no los redirige).
- Nunca inicializa el ledger: `DynamoLedger.initialize` con la autorización y su nonce es una acción previa del operador; sin ella el handler falla.
- La función usa código de S3 con **versión de objeto obligatoria**, timeout de 120 s, concurrencia reservada 1 (invocaciones serializadas; la garantía real es el CAS del ledger) y logs en `ControllerLogs`. Reglas: región `us-east-1` y todos los parámetros revisados obligatorios cuando se habilita. Un test compara las variables de entorno de la plantilla con las que lee el handler.
- **Sin reintentos asíncronos de Lambda:** `EventInvokeConfig` fija `MaximumRetryAttempts=0` y `MaximumEventAgeInSeconds=60`. Sin ello, un `launch` que fallara antes de su claim podía reintentarse sin que nadie lo pidiera hasta horas después. Invocar `launch` solo de forma síncrona (`RequestResponse`), con `AWS_MAX_ATTEMPTS=1` (o `max_attempts = 1` en el perfil) y `--cli-read-timeout` mayor que 120 s: el CLI reintenta también errores como `TooManyRequestsException`, probable con concurrencia reservada 1. Esos reintentos serían seguros por el ledger, pero tardíos. La configuración se aplica a `$LATEST`; una versión o alias publicados tendrían los reintentos por defecto (la plantilla no los crea: no publicarlos).
- **Tiempo de invocación:** el controlador recibe el tiempo restante de Lambda y no persiste un `claim-launch` ni un `claim-stop` si quedan menos de 60 s (peor caso estimado del lanzamiento del worker: 4 llamadas de ~8 s más el bind). Esto **reduce** el riesgo de que un timeout deje un claim sin efecto, sin eliminarlo: el timeout de lectura limita cada lectura del socket, no la petición entera. Si se agota el tiempo durante un tick, la segunda parada se pospone a la siguiente invocación sin reservarse. Un corte por otras causas sigue exigiendo reconciliación manual, como antes.

Pruebas: `tests/test_research_pair_handler.py`, 9 casos con Moto y un ECS falso (desactivado, eventos hostiles, segundo opt-in y región, ledger no inicializado, ciclo completo, coherencia con la plantilla, clientes de producción, punto de entrada con el tiempo de Lambda y **validación de cada petición a ECS contra el modelo de la API de botocore**, incluido `ListTasks`).

Límites del handler:

- **El plazo no se aplica solo.** No hay programación: la parada por vencimiento depende de que un operador invoque `supervise` (o de una programación futura revisada). El proxy deja de aceptar túneles al llegar `BAKATA_RESEARCH_UNTIL`, pero eso no demuestra que la tarea termine; el watchdog de `watchdog.json` cubre otra definición de tarea.
- **La red se importa de `foundation.json`, no se recibe como parámetro.** `foundation.json` exporta `<foundation>-ProxyFixtureSubnet`, `-ProxyFixtureSecurityGroup`, `-ProxyFixtureWorkerSubnet` y `-ProxyFixtureWorkerSecurityGroup`, y la función los importa con `Fn::ImportValue` a partir de `FoundationStackName`. Así, el controlador solo puede pedir la red revisada, en la que el proxy solo acepta tcp/8443 desde el SG del worker. Un test comprueba que cada importación apunta a la exportación del rol correcto (sin cruzar proxy y worker) y que esas exportaciones siguen siendo las de los recursos revisados. `FoundationStackName` solo admite `bakata-research-*`: un stack ajeno con otro nombre no puede aportar la red. Límites: un principal con `cloudformation:CreateStack` podría crear otro stack `bakata-research-*` que exporte esos nombres (los exports de un foundation ya existente no se pueden suplantar, porque son únicos por cuenta y región), y las Rules no pueden exigir que `FoundationStackName` sea el mismo stack que generó el clúster y la definición del worker: revisarlo al desplegar. `_describe` sigue verificando la subred en tiempo de ejecución, no el SG, y el controlador rechaza SGs iguales.

**Orden de despliegue y acoplamiento:** primero foundation con `EnableProxyFixture=true`, después este stack. Mientras la función importe la red, foundation no puede desactivar `EnableProxyFixture`, borrarse ni aplicar cambios que **reemplacen** subredes o SGs (p. ej. `GroupDescription` o `CidrBlock`), porque cambiarían los valores exportados. Para cambiar o desmontar la red: `EnablePairController=false` (libera las importaciones; la tabla del ledger queda retenida), cambiar foundation y volver a habilitar.

**Por confirmar en un change set de sandbox:** que con `EnablePairController=false` y `FoundationStackName` vacío CloudFormation no resuelva el `ImportValue` de recursos con condición falsa, y que acepte un stack sin recursos (afecta también a `proxy-task.json`). Ambos casos fallarían de forma segura.
- Los logs y errores incluyen ARNs de tareas, cuenta, run y mensajes de botocore; no incluyen el nonce ni secretos. El nonce es visible para quien pueda leer la configuración de la función.
- La concurrencia reservada exige margen de cuota en la cuenta. No hay firma de código; la versión de objeto fijada mitiga la sustitución del paquete.

## Separación

- **Red (en `foundation.json`, sin duplicar):** SGs distintos para worker y proxy; el único ingreso al proxy es TCP 8443 desde el SG del worker; el proxy solo sale a endpoints de AWS en 443; ninguno tiene ruta a Internet.
- **Proxy:** tarea propia sin task role (`proxy-task.json`).
- **Worker:** su task role solo accede a su partición del ledger de capturas y a su prefijo S3; sin permisos ECS, IAM, STS ni Lambda y sin recursos comodín.
- **Controlador:** la política de recurso del ledger niega `PutItem`, `UpdateItem`, `DeleteItem`, `BatchWriteItem` y PartiQL de escritura a todo principal cuyo ARN no sea `<stack>-pair-controller`, incluidos los task roles. El recurso de la política es el ARN explícito de la tabla (`<stack>-pair-ledger`).

## Permisos del controlador

- `ecs:RunTask` solo sobre las dos definiciones revisadas, en el clúster revisado, con `bakata:purpose=research-fixture` y solo las claves de etiqueta `bakata:purpose|role|run|until`; denegado si se pide ECS Exec.
- `ecs:TagResource` solo durante `RunTask`; `DescribeTasks`/`StopTask` solo en tareas del clúster con la etiqueta de propósito; `ListTasks` condicionado al clúster.
- `iam:PassRole` solo para el task role del worker y los dos execution roles, y solo hacia `ecs-tasks.amazonaws.com`.
- Ledger: `GetItem`, `Query`, `PutItem` en particiones `PAIR#*` (`TransactWriteItems` se autoriza como `PutItem` por ítem); sin `UpdateItem`, `DeleteItem` ni `ConditionCheckItem`.
- Confianza: `lambda.amazonaws.com` con `aws:SourceAccount`. Sin políticas gestionadas ni `Path`. La [documentación de Lambda](https://docs.aws.amazon.com/lambda/latest/dg/permissions-managed-policies.html) admite `aws:SourceAccount`/`aws:SourceArn` en la confianza del rol de ejecución, pero no confirma explícitamente que Lambda envíe ese valor al asumirlo: si no lo hiciera, la creación o ejecución de la función fallaría (falla cerrado). Validarlo en el ensayo; la alternativa es la confianza sin condición que usa `watchdog.json`.

Las claves de condición usadas figuran en la Service Authorization Reference de ECS y DynamoDB para esas acciones (verificado en auditoría independiente, sin evaluación contra AWS).

## Lo que IAM no puede limitar

**`RunTask` no admite condiciones sobre subred, IP pública ni overrides.** Quien pueda actuar como el rol del controlador podría lanzar una definición revisada en otra subred o SG, con IP pública, con otro `command`, o pasar al proxy el task role del worker mediante `overrides.taskRoleArn`, porque `PassRole` no liga un rol a una definición. Mitigaciones:

- el controlador solo pide subredes revisadas, `assignPublicIp=DISABLED` y sin roles en overrides;
- tras verificar la identidad de la tarea (ARN, clúster, definición, `startedBy`, `group`, etiquetas), `_describe` exige que sus overrides sean **exactamente** los enviados (nombres de contenedor y solo `BAKATA_RESEARCH_RUN`/`UNTIL`; sin `command`, variables extra ni roles sobrescritos), que su ENI esté en la subred revisada del rol y que no esté en RUNNING sin ENI. Si no se cumple, `supervise` **detiene esa tarea y su par** y luego falla para revisión manual. Una tarea cuya identidad no se puede verificar nunca se detiene: podría no ser nuestra;
- **no verifica el security group efectivo**, que DescribeTasks no expone;
- se recomienda una cuenta o VPC dedicada sin subredes con salida, de modo que una subred incorrecta no tenga a dónde ir.

**Administradores:** la denegación no cubre `PutResourcePolicy`/`DeleteResourcePolicy`, para evitar un bloqueo sin salida. Un administrador puede retirar la política y DynamoDB no detecta drift de políticas de recurso, así que el cambio sería silencioso. También podría escribir quien pueda usar el rol del controlador (por ejemplo, `iam:PassRole` + `lambda:CreateFunction`, o modificar su confianza o políticas): la confianza solo exige la cuenta, no una función concreta. Antes de usarlo en serio: SCP o permissions boundary sobre esas acciones y alarmas de CloudTrail.

## Verificación

- `cfn-lint` 1.61.0 sin errores (9 avisos W1030 por parámetros vacíos por defecto; con el flag activado, `ReviewedInputsWhenEnabled` los exige).
- `scripts/test-research-pair-controller-iam.py` compara **exactamente** con los valores revisados cada sentencia del rol, su confianza, propiedades, patrones de parámetros, reglas, el conjunto de recursos y la política del ledger; y verifica entre plantillas el ingreso y la salida del proxy, la ausencia de task role del proxy y los límites del rol del worker. Detecta 52 mutaciones de plantilla, 5 de importación de red (incluidas función con lanzamiento forzado, código sin versión, concurrencia libre, programación, URL o permiso de invocación, reintentos asíncronos, eventos antiguos, región y red libre o cruzada) y 8 de red/roles, incluidas las 24 de la auditoría (21 no detectadas por la primera versión). Se ejecuta en `research-aws-validation.yml`. Cualquier cambio legítimo exige actualizar el test a propósito.

## Límites

- Pruebas estructurales: no evalúan políticas contra AWS ni permisos efectivos. Validar con IAM Access Analyzer o en un ensayo autorizado, incluido el comportamiento de `DescribeTasks` ante una tarea denegada.
- `PutItem` puede sobrescribir un ítem: la inmutabilidad depende de las expresiones condicionales del adaptador (`attribute_not_exists` en cada escritura).
- El nombre del rol `<stack>-pair-controller` limita el nombre del stack a 47 caracteres. Una Lambda futura debe configurar `LoggingConfig.LogGroup` hacia `ControllerLogs`: el rol no puede crear grupos de logs.
- Las reglas no comprueban que los ARN de parámetros pertenezcan a la misma cuenta (si no, el permiso no casa y falla cerrado).
- La tabla usa `Retain`, protección contra borrado y nombre fijo `<stack>-pair-ledger`: tiene costo bajo demanda, queda tras borrar el stack, y recrear un stack con el mismo nombre o cualquier cambio que exija reemplazar la tabla fallará (de forma segura) hasta resolver la tabla retenida. No se ha verificado si una restauración PITR conserva la política de recurso.
- No crea la red (`EnableFixtureNetwork`/`EnableProxyFixture` de foundation) ni sus endpoints con costo por hora.
