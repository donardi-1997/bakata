# INT-18H.3c.2d — Imágenes research fijadas por digest

Estado: entradas inmutables, **no** imágenes publicadas ni revisadas. No se creó ECR ni se publicó nada.

## Bases (resueltas el 2026-11-27 con `docker buildx imagetools inspect`, índice OCI multiarquitectura)

| Imagen | Base |
|---|---|
| `infra/research-aws/proxy.Dockerfile` | `python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b` |
| `infra/research-aws/coordinator.Dockerfile` | misma base Python |
| `services/intelligence/Dockerfile` | misma base Python |
| `infra/research-worker/Dockerfile` | `wordpress:php8.3-apache@sha256:9b46af6a…92eb26` y `wordpress:cli-php8.3@sha256:fc50189a…71029` (PHP 8.3.37) |

El coordinador instala `infra/research-aws/coordinator-requirements.lock` con `--require-hashes --no-deps --only-binary=:all:` (boto3/botocore 1.44.12 y 5 dependencias). El lock se generó dentro de la base fijada.

## Verificación local

- `scripts/test-research-image-pins.py`: toda instrucción `FROM` research usa `@sha256:`, todo `pip install` exige hashes y el lock está completo; incluye mutaciones negativas. Se ejecuta en `research-aws-validation.yml` junto al test y `cfn-lint` de `proxy-task.json`.
- Builds locales: proxy (importa `research_proxy_auth` sin red), coordinador (`pip freeze` coincide con el lock) e inteligencia (248 pruebas dentro de la imagen, sin red).
- El worker no se construyó localmente: su contexto (`plugins/`, `dropify-capture-page.php`) lo ensambla CI desde ZIP. Solo se verificó que sus dos bases se resuelven.

## Límites

- Un digest fija la entrada; no demuestra revisión, escaneo, SBOM ni firma. La procedencia sigue pendiente.
- Las capas de la build no son bit a bit reproducibles (timestamps); no se fijaron paquetes del sistema operativo.
- Actualizar bases exige regenerar el digest y el lock deliberadamente; no hay renovación automática.
