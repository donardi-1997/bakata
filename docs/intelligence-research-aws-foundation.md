# INT-18G — Infraestructura declarativa AWS (dormida)

La plantilla CloudFormation infra/research-aws/foundation.json define una infraestructura separada de Lightsail. No contiene integración con el despliegue de WordPress, no se despliega desde CI y no inicia ninguna tarea. Validación offline con tests de invariantes y cfn-lint. AWS ValidateTemplate verificó la sintaxis general en us-east-1; esto no sustituye un change set ni una prueba real de creación.

## Fase 1: fundación (EnableFixtureNetwork=false por defecto)

Dos repositorios ECR independientes con tags inmutables, escaneo y cifrado; bucket S3 privado/versionado/cifrado, sin ACL públicas y con TLS obligatorio; DynamoDB on-demand con clave pk/sk, cifrado, protección contra eliminación y PITR; clúster ECS sin servicio; Lambda placeholder con concurrencia reservada 0, IAM exclusivo de logs, sin acceso a RunTask, S3, DynamoDB o secretos. No hay eventos, trigger, cron, secretos ni conexión con la tienda.

El bucket, ledger y repositorios se retienen ante borrado/reemplazo de stack. Revisar inventario y costos de recursos retenidos manualmente. No hay política de eliminación automática de evidencias. Almacenamiento, operaciones, PITR, logs e imágenes pueden generar costos; no asumir nivel gratuito. Mantener nombre de stack suficientemente corto para el nombre Lambda (<52 caracteres).

## Fase 2: ensayo de tarea Fargate (opt-in separado)

Antes de habilitar la red, aprobar una ventana de gasto y subir a los dos ECR las imágenes revisadas por digest SHA-256. La plantilla requiere ambos digests; no valida que su contenido corresponda al build revisado: verificar proveniencia, plataforma amd64, escaneo e identidad de las imágenes antes del change set.

EnableFixtureNetwork=true crea una VPC privada de una sola AZ, subred sin IPv4 pública por defecto, tabla de rutas sin Internet Gateway, NAT, peering ni rutas de salida a Internet. Endpoints privados ECR api/dkr y CloudWatch Logs, y gateway S3 restringido al bucket regional de capas ECR. Los tres endpoints Interface facturan por hora aunque no haya tareas: revisar tarifas y retirarlos con el parámetro false al terminar el ensayo. El SG del worker no tiene ingress y permite TCP 443; el aislamiento depende de la ausencia de rutas externas y de los endpoints, no de filtrado DNS. No se adjunta a la red de producción. El DNS y los endpoints AWS no constituyen filtrado general de exfiltración; no usar datos reales.

Se registra una definición Fargate de 1 vCPU, 2 GiB, 21 GiB de almacenamiento efímero, dos contenedores y comunicación localhost. Worker UID 33, raíz read-only, capacidades eliminadas, scratch efímero; MariaDB con credenciales **sintéticas** fijas y volumen desechable. No hay task role ni Secrets Manager. La ejecución role solo obtiene token ECR (requiere Resource "*"), lee ambos repositorios y escribe en su grupo de logs. No otorga permisos al proceso de aplicación. No se registra task service, no se invoca RunTask, no se habilita ECS Exec.

La plantilla no impone la configuración de red de una llamada RunTask: el operador debe elegir exclusivamente los outputs FixtureSubnet/FixtureSecurityGroup, assignPublicIp=DISABLED y plataforma Fargate Linux 1.4.0 o posterior. Validar también dependencias de arranque, escritura en /tmp con el UID del worker, timeouts, límites de CPU/memoria y apagado automático en una ejecución real. La configuración local Docker de CI no garantiza que estos aspectos funcionen en Fargate. La tarea actual emite exclusivamente proyecciones sintéticas al log; no conecta aún con S3/DynamoDB. No habilitar tráfico hacia Dropi.

## Siguiente: INT-18H

Implementar reserva condicional en DynamoDB con una identidad estable de corrida/tienda/página, exclusión y cooldown durables, estados uncertain que no vuelvan a ejecutarse automáticamente, persistencia verificada en S3, permisos IAM por prefijo, y cierre de tarea con límite de tiempo externo. Diseñar el canal de secreto sin reutilizar DB de producción. Secrets Manager y salida a Dropi se incorporarán en un cambio posterior revisado, sin habilitarlos por defecto. La red privada fixture actual no admite llamadas al proveedor.

No se ha creado ningún recurso AWS, enviado token ni realizado consulta comercial con este PR.
