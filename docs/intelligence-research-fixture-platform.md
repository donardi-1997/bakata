# Plataforma explícita para el lanzador fixture

El controlador fija `platformVersion=1.4.0` en RunTask Fargate, en lugar de depender de `LATEST`. Es la versión Linux mínima exigida por `intelligence-research-aws-foundation.md` para el ensayo fixture. La prueba offline inspecciona los argumentos del cliente falso; no inicia tareas.

La revisión de main remoto `5425490` confirmó que #81 implementa el supervisor y #82 la red y autenticación sintética: este cambio no los duplica ni modifica. El código aquí parte de `eb5ccc8` y debe integrarse sobre ese main, no sustituirlo.

Fijar la versión no demuestra disponibilidad regional, compatibilidad de imágenes, ejecución real, IAM, aislamiento ni parada garantizada. Continúan pendientes los controles y ensayos documentados en #81 y #82 antes de habilitar cualquier ejecución; no hay despliegue, credenciales, consultas al proveedor ni recursos creados.

Evidencia offline: `wsl python3 -B -m unittest discover -s tests -p 'test_research_launcher.py' -v`, desde `services/intelligence`.
