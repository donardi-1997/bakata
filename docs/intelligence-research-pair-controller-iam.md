# INT-18H.3c.2d — Frontera IAM del controlador de par (plantilla durmiente)

`infra/research-aws/pair-controller.json` declara, solo con `EnablePairController=true`, el ledger DynamoDB del par y el rol del controlador. No crea Lambda, programación, servicio ni definición de tarea. El controlador (`research_pair_controller.py`) puede usar este ledger mediante `research_pair_dynamo_ledger.py` (probado con Moto); falta el handler y su despliegue. No se ha creado ningún stack.

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
- Confianza: `lambda.amazonaws.com` con `aws:SourceAccount`. Sin políticas gestionadas ni `Path`.

Las claves de condición usadas figuran en la Service Authorization Reference de ECS y DynamoDB para esas acciones (verificado en auditoría independiente, sin evaluación contra AWS).

## Lo que IAM no puede limitar

**`RunTask` no admite condiciones sobre subred, IP pública ni overrides.** Quien pueda actuar como el rol del controlador podría lanzar una definición revisada en otra subred o SG, con IP pública, con otro `command`, o pasar al proxy el task role del worker mediante `overrides.taskRoleArn`, porque `PassRole` no liga un rol a una definición. Mitigaciones:

- el controlador solo pide subredes revisadas, `assignPublicIp=DISABLED` y sin roles en overrides;
- tras verificar la identidad de la tarea (ARN, clúster, definición, `startedBy`, `group`, etiquetas), `_describe` exige que sus overrides sean **exactamente** los enviados (nombres de contenedor y solo `BAKATA_RESEARCH_RUN`/`UNTIL`; sin `command`, variables extra ni roles sobrescritos), que su ENI esté en la subred revisada del rol y que no esté en RUNNING sin ENI. Si no se cumple, `supervise` **detiene esa tarea y su par** y luego falla para revisión manual. Una tarea cuya identidad no se puede verificar nunca se detiene: podría no ser nuestra;
- **no verifica el security group efectivo**, que DescribeTasks no expone;
- se recomienda una cuenta o VPC dedicada sin subredes con salida, de modo que una subred incorrecta no tenga a dónde ir.

**Administradores:** la denegación no cubre `PutResourcePolicy`/`DeleteResourcePolicy`, para evitar un bloqueo sin salida. Un administrador puede retirar la política y DynamoDB no detecta drift de políticas de recurso, así que el cambio sería silencioso. También podría escribir quien pueda usar el rol del controlador (por ejemplo, `iam:PassRole` + `lambda:CreateFunction`, o modificar su confianza o políticas): la confianza solo exige la cuenta, no una función concreta. Antes de usarlo en serio: SCP o permissions boundary sobre esas acciones y alarmas de CloudTrail.

## Verificación

- `cfn-lint` 1.61.0 sin errores (5 avisos W1030 por parámetros vacíos por defecto; con el flag activado, `ReviewedInputsWhenEnabled` los exige).
- `scripts/test-research-pair-controller-iam.py` compara **exactamente** con los valores revisados cada sentencia del rol, su confianza, propiedades, patrones de parámetros, reglas, el conjunto de recursos y la política del ledger; y verifica entre plantillas el ingreso y la salida del proxy, la ausencia de task role del proxy y los límites del rol del worker. Detecta 34 mutaciones de plantilla y 8 de red/roles, incluidas las 24 de la auditoría (21 no detectadas por la primera versión). Se ejecuta en `research-aws-validation.yml`. Cualquier cambio legítimo exige actualizar el test a propósito.

## Límites

- Pruebas estructurales: no evalúan políticas contra AWS ni permisos efectivos. Validar con IAM Access Analyzer o en un ensayo autorizado, incluido el comportamiento de `DescribeTasks` ante una tarea denegada.
- `PutItem` puede sobrescribir un ítem: la inmutabilidad depende de las expresiones condicionales del adaptador (`attribute_not_exists` en cada escritura).
- El nombre del rol `<stack>-pair-controller` limita el nombre del stack a 47 caracteres. Una Lambda futura debe configurar `LoggingConfig.LogGroup` hacia `ControllerLogs`: el rol no puede crear grupos de logs.
- Las reglas no comprueban que los ARN de parámetros pertenezcan a la misma cuenta (si no, el permiso no casa y falla cerrado).
- La tabla usa `Retain`, protección contra borrado y nombre fijo `<stack>-pair-ledger`: tiene costo bajo demanda, queda tras borrar el stack, y recrear un stack con el mismo nombre o cualquier cambio que exija reemplazar la tabla fallará (de forma segura) hasta resolver la tabla retenida. No se ha verificado si una restauración PITR conserva la política de recurso.
- No crea la red (`EnableFixtureNetwork`/`EnableProxyFixture` de foundation) ni sus endpoints con costo por hora.
