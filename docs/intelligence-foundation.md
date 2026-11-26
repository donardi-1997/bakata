# Bakatá Intelligence — INT-01

Servicio experimental de inteligencia comercial, independiente de WordPress, WooCommerce y Dropify. Solo procesa fixtures sintéticas. No tiene endpoints HTTP, credenciales, programador de tareas ni acceso a red en ejecución. No se incorpora a Compose de la tienda ni al despliegue operativo.

## Contrato inicial

- Adapter: identificador estable de fuente y lote de observaciones; máximo 1.000 observaciones aceptadas por transacción.
- Observation: fuente, identificador externo, título, URL HTTPS, fecha UTC, código de moneda y precio entero en unidades menores (COP: centavos, 49.900 COP = 4.990.000 unidades); null significa desconocido, no gratis. El adaptador futuro debe verificar la moneda, su exponente y los valores originales; validar tres letras no equivale a validar ISO 4217.
- Clave única: fuente + identificador externo + fecha de observación. Repetición idéntica es idempotente, conflicto revierte todo el lote. Observaciones posteriores conservan historial. No se asume equivalencia entre fuentes.
- SQLite es un almacenamiento de referencia en memoria para pruebas; no se conecta a la base comercial. La persistencia durable y migraciones se diseñarán según volumen y necesidades de concurrencia.
- Contenedor no root, sistema de archivos de solo lectura, red deshabilitada, límites de CPU/memoria y sin puertos publicados. La construcción sí puede requerir descargar la imagen base; su digest se fijará antes de habilitar un entorno permanente.

## Ejecución

Desde la raíz:
```sh
docker compose -f services/intelligence/compose.yaml config --quiet
docker compose -f services/intelligence/compose.yaml build fixture
docker compose -f services/intelligence/compose.yaml run --rm -T fixture python -m unittest discover -s tests -v
docker compose -f services/intelligence/compose.yaml run --rm -T fixture
```

Salida esperada del ejemplo: modo fixture, 2 inserciones, 0 inserciones al repetir, 2 observaciones. El ejemplo no conserva datos al salir.

## Próximas etapas

INT-02: transporte HTTP con lista de destinos permitidos, validación de URLs y redirecciones, protección SSRF/DNS, límites de descarga y tiempo, rate limiting, política robots y términos, manejo de 429, reintentos acotados y pruebas con servidor sintético. Ninguna fuente real se habilita hasta verificar condiciones de acceso y aprobación explícita. No eludir CAPTCHA, autenticación, paywalls ni controles del proveedor. No recolectar datos personales ni copiar activos comerciales sin derechos.

INT-03: adaptadores por fuente autorizada; API oficial preferida. Dropi únicamente mediante mecanismos autorizados de WooCommerce. INT-04–06: normalización, historial y scoring verificables; INT-07–09: panel, programación e importación aprobada como borrador usando Bakatá Core; INT-10: seguridad, consumo, calidad y despliegue. No se publican productos ni se envían pedidos.
