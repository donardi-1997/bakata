# INT-18H.3a — Contrato de credenciales y comunicación segura

Esta etapa es una base verificable, **no un conector live ejecutable**. Las políticas son funciones puras no conectadas al runtime. No se crea ni se lee ningún secreto real. El rol CloudFormation está separado de las tareas existentes y deshabilitado por defecto. No desplegarlo aún.

## Credencial

Se requiere una credencial autorizada para investigación mediante la integración WooCommerce existente, no una API nueva. Si Dropi no permite separar el alcance de una credencial, documentar el riesgo residual sobre el token compartido y obtener autorización explícita antes del piloto. No copiar la DB comercial. El secreto será creado por el operador mediante un canal privado de Secrets Manager (no chat, CLI con valores en argumentos, Git ni logs), bajo bakata/research/dropify/, en us-east-1. El envelope JSON admite exactamente schema=bakata-dropify-research-secret-v1, store_id y token. La versión aprobada debe seguir marcada AWSCURRENT; la rotación invalida la autorización existente y obliga a una revisión nueva. La validación limita token a ASCII imprimible sin espacios (hasta 1000 bytes); comprobar compatibilidad real sin mostrar el valor.

El lector exige ARN completo, cuenta, versión y tienda; no usa fallback, lista ni describe secretos, y redacta errores. El IAM permite exclusivamente GetSecretValue para el ARN y VersionId/VersionStage aprobados, con aws:ResourceAccount local. Usar cifrado administrado aws/secretsmanager inicialmente; una CMK propia requiere una política KMS explícita posterior. No se incluye permiso para crear, cambiar, rotar, borrar o listar secretos. El rol no se adjunta a ningún contenedor. Para no compartir credencial IAM con todos los contenedores de una tarea ECS, separar el proceso autorizado o utilizar un mecanismo de entrega de secreto revisado (no asumir aislamiento IAM por contenedor). No serializar ResearchCredential ni activar debug del SDK.

## Política HTTP

Comparada con el ZIP 4.7.3 SHA-256 bf23c6b1c5dd640aab3d38e3f370a41fbd60139ac60a1ce5f0347a059e9b6700 y el parche de catálogo. La única operación candidata es POST HTTPS api.dropi.co/integrations/products/index. Scope piloto: páginas 1–3, diez productos por página, búsqueda vacía, id asc, sin filtros adicionales, sin redirecciones ni cookies, TLS verificado, timeout 15 s, límite de respuesta 512 KiB, token exacto. Coincidencia de cuerpo JSON serializado original. Las pruebas son sintéticas; aún falta conectar la validación a la solicitud real del conector endurecido y comprobar los defaults de WP HTTP.

## Red y transporte (diseño pendiente de integración)

Worker en subred sin ruta directa a Internet, endpoints privados y proxy de salida dedicado en una tarea/subred distinta. El proxy debe limitar CONNECT a api.dropi.co:443, rechazar respuestas DNS no públicas o mezcladas y conectar al número IP ya validado sin resolver otra vez. La política Python valida solo el destino, no implementa un listener, DNS, firewall ni TLS. WordPress debe verificar hostname/cadena TLS de extremo a extremo, sin interceptar ni registrar token. Un proxy CONNECT no puede validar ruta/cuerpo cifrado; la comprobación PHP es una segunda capa cooperativa, no una frontera ante un worker comprometido. Revisar acceso DNS, endpoints AWS, autenticación del proxy, límites de tamaño/tiempo, ausencia de ruta alternativa y bloqueo de otros puertos. No habilitar NAT, IGW ni permisos de producción con este cambio.

## Condiciones restantes

Fusionar y validar INT-18H.2. Después crear imagen live separada de fixtures, integrar reserva persistente para piloto no sintético con presupuesto máximo de tres consultas y pausa, ligar la lectura de credencial a la reserva y el secreto a la tienda autorizada, implementar proxy y red de salida, política de evidencia y watchdog externo de detención. Ensayar Fargate y IAM con credenciales sintéticas antes de autorización de proveedor. No afirmar que un ARN/versión equivale a permiso comercial o que el secreto está configurado. No hay consultas al proveedor, despliegue, ni programación.
