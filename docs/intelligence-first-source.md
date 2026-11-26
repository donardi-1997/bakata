# INT-11 — Primera fuente autorizada (piloto manual)

Se propone una tienda WooCommerce propia de pruebas o expresamente autorizada por su propietario como primera fuente. Usar el recurso público de productos de Store API, no una API privada de Dropi, no credenciales WooCommerce ni scraping de marketplaces. No hay dominio real configurado, autorización otorgada ni solicitud comercial realizada. La tienda principal de bakatá no se presupone como destino del piloto.

## Requisitos externos de activación

- INT-10 integrado en main, CI acumulativo verde, revisión de seguridad y entrega offline verificada.
- Confirmar dominio, propiedad o permiso expreso para investigación comercial, condiciones vigentes y copia revisada de robots.txt. Registrar referencias a documentos reales fuera del repositorio, fecha y vencimiento.
- Confirmar una IPv4 pública aprobada y firewall de salida que limite a esa dirección y TCP/443 (DNS únicamente mediante resolver confiable). La IP comprobada por la aplicación no sustituye egress de infraestructura. Si el DNS cambia, detener el piloto y revisar, no ampliar automáticamente el allowlist.
- Host Linux aislado, usuario no privilegiado, directorio privado 0700 con un único ledger persistente por piloto, almacenamiento protegido y supervisión. Revisar dependencias e imagen antes de cualquier ejecución comercial. No usar directamente el host de la tienda, no habilitar la red en Compose de Intelligence ni instalar cron.
- Confirmar política de tratamiento, retención y eliminación de datos autorizados. No cargar respuesta cruda ni secretos en Git.

## Manifiesto local

Crear fuera de Git un JSON con campos exactos. La plantilla siguiente es deliberadamente inválida e inactiva hasta completar valores revisados; no es autorización:

```json
{
  "version": "int11-v1",
  "enabled": false,
  "source": "first-owned-store",
  "host": null,
  "expected_ip": null,
  "reviewed_at": null,
  "approved_until": null,
  "robots_valid_until": null,
  "robots_text": "",
  "owner_permission_ref": "",
  "terms_ref": "",
  "robots_ref": "",
  "egress_ref": ""
}
```

Fechas ISO 8601 UTC; aprobación hasta siete días desde revisión, robots hasta 24 horas. Solo host DNS exacto y ruta fija /wp-json/wc/store/v1/products sin parámetros. El parser de robots es deliberadamente restrictivo: cualquier Disallow simple coincidente, directiva no soportada, comodín o sintaxis ambigua bloquea. No pretende implementar todo RFC 9309. Referencias de revisión son anotaciones confiables del operador, no comprobación automática de permiso, firewall ni firma.

## Procedimiento

Con el manifiesto completo, aún disabled, ejecutar en el entorno aislado:

```sh
cd services/intelligence
python3 -m intelligence.pilot plan --manifest /ruta/privada/pilot.json
```

El plan no hace DNS ni llamadas HTTP ni crea recibos. Revisar ruta, IP, vigencia y digest. Solo después de confirmar todos los requisitos externos y autorización explícita, habilitar el manifiesto, repetir plan y aprobar su nuevo digest. El comando siguiente se documenta para el futuro operador autorizado; no forma parte de CI ni del despliegue:

```sh
umask 077
python3 -m intelligence.pilot execute \
  --manifest /ruta/privada/pilot.json \
  --ledger /ruta/privada/pilot.sqlite \
  --confirm DIGEST_SHA256_DEL_PLAN_APROBADO > /ruta/privada/result.json
```

Una única GET HTTPS, IPv4 revisada debe coincidir con la dirección pública seleccionada por DNS, conexión numérica con SNI y verificación TLS del hostname. Sin redirects, reintentos, cookies, proxy ambiental ni paginación. Deadline de proceso Linux 30 s, timeout de socket 10 s, respuesta JSON sin compresión hasta 512 KiB y máximo 100 filas según contrato Store API de INT-03. Un 429/403, cambio de DNS, error de certificado, JSON inválido, caducidad o interrupción exige revisión manual. No se siguen enlaces. Solo se exportan observaciones normalizadas y evidencia SHA-256 de la captura; no se emite el cuerpo original. Los precios de rangos siguen desconocidos.

El ledger local reserva de forma persistente antes del intento, por hostname, con estado reserved, succeeded o failed-review. Una reserva existente impide nuevas solicitudes por ese host en el mismo ledger incluso si el manifiesto cambia. No borrar/recrear el ledger para reintentar; no coordina hosts diferentes, otras máquinas o herramientas. Sin API ni scheduler, no es un limitador distribuido. El resultado JSON se conserva por el operador; si falla la salida después de confirmar recibo, se revisa manualmente. El hash sin cuerpo original no permite reconstruir la evidencia; almacenamiento comercial completo es INT-12.

## Pruebas y estado

Nueve pruebas sintéticas validan manifiesto, vigencia, robots, IP, confirmación, recibos, ausencia de redirects y validación de catálogo. Prueba TLS real usa servidor loopback, certificado generado temporalmente por OpenSSL, CA de prueba y socket redirigido explícitamente a loopback; comprueba verificación de hostname y conexión con IP seleccionada, sin DNS ni acceso externo. CI ejecuta obligatoriamente esta prueba en el host Linux. No constituye prueba de egress real, DNS real, certificados del proveedor ni rendimiento de red en Lightsail.

La CLI de piloto no se registra en ningún contenedor, endpoint o tarea operativa. El perfil existente sigue sin red. La salida del piloto no se conecta a la UI sintética ni al importador CI; no se crean productos. La activación real permanece bloqueada por falta de dominio y permiso confirmados, CI integrado y controles externos. INT-12: persistencia de capturas, observaciones, evidencias y revisiones comerciales con migraciones y retención.
