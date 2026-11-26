# Infraestructura de desarrollo

Lightsail `bakata-dev-2gb` (us-east-1a, Ubuntu 24.04, 2 GB RAM), IP estática 98.86.5.107. Spaceship resuelve dev.bakata.store; no modificar el dominio de producción. Nginx TLS termina HTTPS; WordPress solo escucha en 127.0.0.1:8080; MariaDB no publica puertos. Docker y Nginx arrancan automáticamente, SWAP 2 GiB con swappiness 10. SSM híbrido permite administración saliente HTTPS.

## Reconstrucción (Ubuntu limpio)
1. Actualizar Ubuntu, instalar Docker Engine + Compose, Git, Nginx, Certbot, apache2-utils, UFW. Crear SWAP persistente. Registrar SSM con rol limitado y activación de un uso. No guardar código de activación.
2. Clonar repositorio como ubuntu en /home/ubuntu/bakata, crear .env con secretos locales, chmod 600, configurar WP_URL=https://dev.bakata.store. Ejecutar bootstrap. Conservar volúmenes.
3. DNS A dev hacia IP estática; firewall AWS 22/80/443 únicamente. Crear /var/www/letsencrypt, instalar infra/nginx/bakata-acme.conf como sitio temporal bakata-dev, habilitarlo, validar nginx -t y recargar. Emitir certificado con certbot certonly --webroot -w /var/www/letsencrypt -d dev.bakata.store.
4. Crear /etc/nginx/.htpasswd-bakata con htpasswd -cB; root:www-data, 640. Usar contraseña distinta de WordPress.
5. Con una sesión SSH y SSM de respaldo, ejecutar sudo bash scripts/apply-host-hardening.sh; revisar salida y probar nueva conexión SSH. El script presupone Ubuntu y el subdominio de desarrollo, no sirve para producción. UFW permite 22/80/443; no publicar otros puertos Docker porque Docker puede eludir UFW.
6. Ejecutar sudo bash scripts/harden-wordpress.sh. Validar curl HTTP 301, HTTPS 401 sin credenciales, 200 con credenciales, certbot renew --dry-run. Verificar home/siteurl, y acceso admin. No cambiar URL de una instalación existente sin comprobar ambos valores.

## Despliegue
El script scripts/deploy-dev.sh está diseñado para instalarse como /usr/local/sbin/bakata-deploy-dev (root:root, 0755) desde un commit revisado. Recibe SHA exacto, exige main limpio, fast-forward, bloqueo de concurrencia, verifica servicios y preserva volúmenes. No aplica hardening de host automáticamente ni ejecuta bootstrap sobre una base existente. No incluye rollback automático: un cambio puede incluir migraciones irreversibles; respaldar antes de cambios de datos. Un fallo requiere inspección y corrección. El despliegue de código de main mediante Docker equivale a confiar en sus contribuidores con privilegios de host. Proteger main y revisar cambios antes de habilitar CD automático.

## Secretos y operaciones
No versionar .env, htpasswd, certificados, claves privadas, dumps, activaciones SSM, archivos wp-config.php ni datos de clientes. El backup local de hardening está en /root/bakata-hardening-20261126-043900/ (contiene configuraciones sensibles, no es backup completo). Mantener SSH por clave hasta verificar un acceso alternativo. Pendiente: protección contra abuso, restricciones SSH según origen, backups externos con prueba de restauración, escaneo de imágenes y alertas. No confundir noindex con control de acceso.
