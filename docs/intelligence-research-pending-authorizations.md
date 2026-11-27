# Autorizaciones pendientes del responsable

Estas decisiones no son rutinarias: tienen efectos externos o costos. Nada de lo siguiente se ha ejecutado.

## A. Fusión del PR #83 en `main` (activa `deploy_dev`)

- `ci.yml` ejecuta `deploy_dev` tras un push a `main` protegido con `BAKATA_CD_ENABLED=true`: comando SSM `Bakata-DeployDev` sobre la instancia de desarrollo. Las fusiones #79–#82 lo dispararon con éxito.
- Requiere: confirmación explícita de aceptar ese despliegue de desarrollo, checks del PR en verde y revisión del diff (65+ archivos, incluye cambios de tema WooCommerce).
- Alternativa sin despliegue: desactivar temporalmente `BAKATA_CD_ENABLED` (también es una decisión del responsable).

## B. Ensayo AWS fixture de INT-18H.3c.2d (genera costos)

Sigue NO-GO técnico: faltan entrega mTLS operativa, controlador que autorice y supervise ambos ARN, IAM/red efectivos y procedencia de imágenes. Cuando eso esté resuelto, se requiere:

- Autorización de cambios por fase: repositorio ECR proxy → publicación de imagen revisada → definición de tarea → red de foundation.
- Tope y ventana de gasto: endpoints Interface (cobro por hora aun sin tareas), Fargate de dos tareas, ECR, logs, S3 versionado y DynamoDB/PITR, más recursos `Retain`.
- Plan de limpieza y responsable de inventario de recursos retenidos. Presupuestos y alertas no garantizan corte.

Estado verificado (solo lectura, us-east-1): ningún stack CloudFormation activo ni clúster ECS con `bakata` en el nombre; no excluye otros nombres.

## C. Piloto real INT-18I y siguientes

Requieren además autorización explícita del operador/proveedor, credenciales reales ligadas a tienda y reserva, y un presupuesto de consultas. No se ha usado ninguna credencial real.
