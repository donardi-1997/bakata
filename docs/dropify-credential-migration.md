# Migración de credenciales Dropify 4.7.3

Inspección del ZIP suministrado: el esquema original en db_tables/token_db_table.php usa token VARCHAR(1000) con índice de igualdad. wc-dropi-integration.php, Helper.php y OrdersModel.php contienen rutas de migración antiguas que vuelven a copiar el token a _dropi_token. ProductsModel.php también escribe esa metadata al importar. Dropi.php, SyncedProdTable.php y OrdersModel.php la leen. No basta con cifrar la columna token.

## Planificador offline

tools/dropify-quarantine/credential-migration.php usa TokenVault de la etapa anterior. Requiere identidad estable de sitio y snapshots completos de las filas legacy (id, token), todas las filas _dropi_token (post_id, token), todos los IDs distintos asociados a Dropify, y el valor de la opción legacy dropi-woocomerce-token. No lee ni escribe la base de datos; la extracción y la cobertura de snapshots todavía deben implementarse y probarse.

La salida contiene sobres cifrados asociados al ID existente de tienda y referencias post_id/store_id. No contiene token en claro ni huella reutilizable del token. La correspondencia se calcula en memoria con HMAC de clave efímera. Rechaza opciones antiguas no conciliadas, duplicados, referencias huérfanas o ausentes y entradas inválidas. Límites deliberados: 1000 tiendas, 10000 productos, IDs hasta 2147483647; excederlos requiere revisión. Los sobres cifrados siguen siendo material sensible y no deben publicarse.

El destino propuesto es una tabla separada de credenciales con ID estable y capacidad suficiente para el sobre (TEXT), y metadata _bakata_dropify_store_id para productos. No se ha creado esta tabla ni modificado el plugin. Conservar nombre y configuración comercial de la tienda sin duplicar el secreto; el despacho sigue deshabilitado. No almacenar una clave de cifrado junto a los sobres.

## Próximo corte (no implementado)

- Diseñar captura consistente, sin actividad del plugin, y comprobar todas las ubicaciones de secretos, incluidos objetos serializados y opciones.
- Deshabilitar todas las rutas legacy de inicialización y reintroducción de credenciales.
- Implementar almacenamiento cifrado, resolución por ID en consumidores e importador y eliminación controlada de referencias antiguas.
- Probar con datos sintéticos en WordPress/MariaDB aislado, rollback, rotación, backups, ausencia de secretos en interfaces y registros. Evitar borrar datos legacy hasta verificar la migración y recuperación; proteger las copias que aún los contienen.
- Nunca habilitar el envío automático ni usar tokens reales en esta etapa.

## Pruebas

php scripts/test-dropify-credential-migration.php

22 aserciones definidas con credenciales sintéticas, incluyendo cifrado, contexto, cobertura, duplicados y límites. Añadidas a Foundation checks en PHP 8.3. Resultado pendiente al abrir el PR. Sin conexión a Dropi ni cambios de producción.
