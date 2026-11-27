# INT-02 — Motor de scraping

Se añaden SourcePolicy, Fetcher, PinnedHTTPS, extract_products y research_page. No se registra una fuente real ni se cambia el contenedor sin red de INT-01. El ejemplo de CLI sigue siendo una fixture en memoria.

## Restricciones

- Solo GET HTTPS, host exacto aprobado, puerto 443, sin credenciales ni fragmentos. Las redirecciones se revalidan y se limitan a dos. No se cambia de host.
- Revisión explícita de términos y texto robots con vencimiento; deny por defecto si faltan. RobotFileParser es una implementación conservadora inicial, no una garantía de conformidad RFC 9309 para todos los casos. Antes de activar cada fuente se requiere verificar su política real y las rutas permitidas.
- Resolución DNS: rechazar cualquier respuesta no pública, multicast y ciertos mecanismos IPv6 de transición. Conectar a la IP validada manteniendo SNI y verificación TLS del hostname; sin proxy ambiental. La política no sustituye un firewall de salida.
- 512 KiB máximo de respuesta HTML, sin compresión, timeout de socket de 10 s y presupuesto de lectura del cuerpo. No se promete plazo total estricto: resolución DNS, cabeceras y operaciones individuales pueden extenderlo. Se requiere aislamiento de proceso con deadline total y controles de egress antes de habilitar red.
- Intervalo por instancia de al menos 2 s, respeta crawl-delay y request-rate interpretados por RobotFileParser. El diseño es serial, no thread-safe ni coordinado entre procesos. No se habilitarán workers paralelos hasta contar con coordinación por fuente.
- Hasta dos reintentos para 429/502/503/504; cinco solicitudes totales, incluyendo redirecciones. Retry-After superior a 30 s exige diferir el trabajo; 403 no se reintenta. No se eluden barreras de acceso.
- JSON-LD Product y Offer único, UTF-8, hasta 20 bloques y 100 candidatos. Solo COP/USD/EUR en centavos; precios ambiguos o no válidos permanecen desconocidos. No se deduce SKU, moneda, stock, demanda ni identidad cuando faltan. Un candidato aún no es una observación persistible: INT-03 deberá aportar identidad estable, URL final, evidencia y fecha de captura.

## Validación

La suite de unittest existente descubre test_scraping.py automáticamente. Las pruebas inyectan respuestas HTTP, DNS y reloj sintéticos, sin red. La implementación TLS/socket real todavía requiere pruebas de integración controladas antes de autorizar acceso externo. No se añade Playwright ni Scrapy en esta etapa para mantener bajo consumo.

Próxima fase: INT-03, seleccionar fuentes con autorización verificable y preparar adaptadores específicos. No acceder a endpoints privados de Dropi ni publicar productos.
