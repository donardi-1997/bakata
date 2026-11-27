# Entrega mTLS fixture offline: bloqueo

**NO-GO:** no se implementa un emisor ni una entrega de material criptográfico.
El contrato de Fargate no especifica una frontera local de identidad y permisos
que permita demostrar que proxy y worker no pueden leer el paquete del otro.
Directorios separados, nombres de rol o permisos simulados en Python no son
aislamiento entre procesos; tampoco se ha validado una frontera de sistema
operativo portable para este repositorio. Un proceso privilegiado o el emisor
pueden necesitar acceso a ambos paquetes. No se debe interpretar el modelo de
prueba como protección frente a ellos.

Para desbloquear una implementación hacen falta, como mínimo, un diseño revisado
de identidades y adversarios locales, emisión efímera y transporte aislado,
pruebas de denegación cruzada ejecutadas bajo identidades reales, manejo de
fallos y limpieza, y verificación criptográfica de certificados, claves, SAN,
vigencia y pin. Hay que definir las garantías y limitaciones por plataforma;
la eliminación de archivos no demuestra borrado físico. La eventual revisión
AWS/IAM, el cliente real y el ciclo de vida del contrato original siguen
pendientes y separados de cualquier prueba local.

`python scripts/test-research-mtls-offline-contract.py` ejecuta únicamente una
especificación sintética de los contenidos permitidos por destinatario y de los
requisitos de evidencia para levantar este bloqueo. No genera ni entrega claves,
no crea identidades, no prueba permisos, criptografía ni limpieza, y no habilita
ningún despliegue o recurso remoto. Los valores y resultados son ficticios.
