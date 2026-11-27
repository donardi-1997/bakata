# INT-18F — Worker de investigación aislado (fixture)

Primer paso de la separación Lightsail / Fargate / Lambda. La imagen ejecuta WP-CLI directamente, sin Apache, Nginx, HTTP entrante ni DNS público. Usa WordPress real, WooCommerce y el ZIP Dropify catalog-only generado desde la distribución 4.7.3 con hash fijado. No copia wp-content ni bases de datos de la tienda. La imagen de esta etapa es exclusivamente sintética: el wp-config exige un flag explícito, DB local de fixture y token canario. No tiene una ruta de carga de credenciales reales.

## Prueba en CI

El workflow Dropify catalog validation reconstruye y valida el ZIP, prepara un contexto mínimo (sin checkout completo, secretos ni respuestas de proveedor), construye la imagen y ejecuta el worker junto a MariaDB desechable. Los dos contenedores comparten namespace de red y se comunican por 127.0.0.1, como modelo local de una tarea ECS awsvpc. La red Docker es interna, sin puertos publicados; el MU plugin simula las respuestas y bloquea HTTP externo. El worker corre como UID/GID 33, raíz read-only, tmpfs limitado, sin capabilities, con no-new-privileges, 768 MiB y 0,75 CPU; MariaDB 512 MiB y 0,5 CPU. Estos valores de CI no son un dimensionamiento probado en AWS.

El proceso exige DB vacía, instala WordPress, activa WooCommerce y Dropify endurecido, prepara la tabla sintética de integración y solicita dos páginas (10+3 productos). El tercer intento debe quedar bloqueado por página parcial. Se verifica que no existan productos publicados, borradores ni pedidos processing y que las dos páginas sean archivables sin duplicación en SQLite. El mismo entorno no permite reinicializar DB existente. Al acabar, la prueba elimina contenedores, volumen anónimo y red; no crea recursos AWS.

## Condiciones antes de activar un worker real

- INT-18G: infraestructura declarativa ECS/Fargate, ECR, S3, DynamoDB e IAM; revisión de costos, red, cifrado, logs y ciclo de vida. Imágenes por digest, versiones revisadas de WordPress y WooCommerce. Las bases WordPress del Dockerfile están fijadas por digest ([pins](intelligence-research-image-pins.md)), pero los plugins se ensamblan en CI desde ZIP y no forman una imagen revisada; no publicar esta imagen a ECR como runtime operativo.
- INT-18H: reserva persistente condicional por tienda/run/página antes de cualquier llamada, independiente de la MariaDB efímera; reconciliación sin reintentos automáticos de incertidumbres; persistencia verificada de proyección en S3. Control de exclusión y cooldown entre tareas.
- Secretos: autorización específica antes de mover un token de Dropify. No copiar la base de producción ni sus clientes, pedidos o opciones. Validar alcance del token y compatibilidad desde otra IP. Eliminar fixture de la futura imagen live y mantener el wrapper fail-closed sin autorización persistente.
- Egress: en AWS, aislar de Lightsail y controlar tráfico saliente hacia el endpoint autorizado y servicios AWS estrictamente necesarios; no asumir que un security group filtra por dominio ni que localhost prueba aislamiento de red de AWS.
- INT-18I: piloto real de hasta 30 productos solo después de aprobar las condiciones anteriores. Sin importaciones, ventas ni publicación. No programar recurrencia hasta verificar límites y respuestas reales.

No se ha desplegado nada ni se ha ejecutado un piloto de proveedor con este cambio.
