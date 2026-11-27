# INT-18H.3c.1 — Ensayo de credenciales, política HTTP y detención

El modo real sigue deshabilitado. Esta etapa integra una credencial sintética emulada con las reservas de INT-18H.1 y el WordPress de INT-18H.2. Después de reservar una página, antes de escribir el request IPC, el coordinador de CI consulta Secrets Manager emulado con ARN, versión y AWSCURRENT exactos, verifica la tienda y compara exclusivamente con el canario de fixture ya instalado en la DB temporal. No transporta el secreto por IPC. Error de credencial deja la reserva bloqueada; no autoriza la página ni reintenta.

El MU plugin de fixture verifica la reserva local y aplica el predicado HTTP de INT-18H.3a a los argumentos HTTP que genera el conector original endurecido dentro de WordPress. El adaptador de prueba usa una identidad piloto sintética sólo para probar el predicado; el recibo sigue ligado al run fixture. Todo tráfico HTTP se intercepta y el entorno Docker no tiene egress. Verifica dos aprobaciones de política, dos respuestas, 13 productos y ausencia de canario en IPC y evidencia. No cambia el modo no persistente ni el WordPress comercial. No demuestra todavía la entrega de un token real, TLS a través del proxy ni IAM de AWS.

El módulo research_watchdog implementa la lógica de un controlador externo: recibe una vinculación inmutable y confiable de cluster, task ARN completo, revision de task definition fixture, run y vencimiento. Antes del vencimiento no llama AWS. Después, DescribeTasks exige identidad exacta, FARGATE y tags de propósito/run/expiry; sólo entonces StopTask de esa tarea exacta. No descubre tareas por tag, no tiene permisos ni trigger desplegado, no detiene producción, no libera reservas. Un resultado stop-requested no significa STOPPED; debe confirmarse posteriormente. La vinculación debe proceder de un launcher confiable con registro persistente, no de inputs públicos ni del worker.

## Pendiente de INT-18H.3c.2

Integrar controlador confiable y permisos IAM mínimos, ejecutar ensayos reales Fargate con secretos sintéticos y proxy aislado, provisionar red/egress en change set aprobado, definir autenticación del proxy y bloqueo de rutas alternativas. Construir imagen live separada sin fixture, autorización piloto real con reserva durable, entrega segura del secreto sin imprimirlo ni copiar DB, verificación TLS end-to-end y detención independiente. No habilitar el proveedor antes de esos controles. El PR #78 contiene el relay CONNECT; este cambio no lo conecta aún al worker.

No se ha desplegado infraestructura ni leído un secreto real ni llamado a Dropi.
