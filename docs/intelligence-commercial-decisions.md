# INT-16D — Registro persistente de decisiones comerciales

Backend offline de revisión humana. Depende del expediente revalidado INT-16B (#61). La rama se basa en ese PR, por lo que se debe integrar primero #61 y después verificar esta rama contra main. No depende de la vista #62, que seguirá siendo de lectura hasta integrar autenticación y el flujo de confirmación.

## Decisiones

- approve-for-draft-review: candidato apto para preparar una revisión posterior de borrador; no crea borrador ni autoriza venta.
- reject: rechazo registrado.
- defer: aplazamiento registrado.

Las tres acciones exigen un vínculo de evaluación válido y completo. No se infiere que un candidato incompleto esté aprobado ni se registra aún un rechazo de candidato sin evaluación. Un nuevo evento reemplaza la decisión efectiva, no borra el histórico. Se conserva referencia de actor y motivo (ticket/evidencia revisada), no texto libre ni datos personales. El actor es una declaración del operador CLI de confianza; aún no hay autenticación vinculada a identidad WordPress ni control de doble aprobación.

## Flujo

Desde services/intelligence, usar tres archivos privados y distintos, con un identificador de alcance estable por pareja de archivos de evidencia. No mezclar instalaciones ni usar otro archivo con la misma referencia de alcance. El nombre de alcance no es una identidad criptográfica de la instalación.

    python3 -m intelligence.decisions --ledger /privado/decisions.sqlite --archive-ref ARCHIVO --bridge /privado/bridge.sqlite --commercial /privado/commercial.sqlite preview --link-id VINCULO

Revisar el expediente. La salida incluye dossier_sha256 y previous_sha256. El digest excluye únicamente el instante de exportación, no la evidencia ni vigencia.

    python3 -m intelligence.decisions --ledger /privado/decisions.sqlite --archive-ref ARCHIVO --bridge /privado/bridge.sqlite --commercial /privado/commercial.sqlite record --link-id VINCULO --event-id ID_UNICO --action approve-for-draft-review --actor-ref REVISOR --reason-ref TICKET --expected-dossier-sha256 DIGEST_EXPEDIENTE --expected-previous-sha256 DIGEST_ANTERIOR

Consultar con history o status --store ID --product-id ID en lugar de record. Una decisión por identidad local de tienda/producto y secuencia de eventos. El último evento prevalece, incluido rechazo o aplazamiento. El estado de aprobación vuelve a leer ambas fuentes y pierde elegibilidad al expirar o cambiar la evidencia; no es una autorización de importación. No reintentar automáticamente un ID existente. En caso de incertidumbre revisar history.

SQLite separado con APP_ID, versión 1, transacción BEGIN IMMEDIATE, expectativa de último digest (evita confirmación concurrente obsoleta), digest encadenado por candidato, IDs únicos, triggers contra UPDATE/DELETE ordinarios, máximo 20.000 eventos, 100 por candidato y presupuesto 128 MiB del archivo principal. No hay borrado ni retención automática. Triggers y hashes no son firma ni protección contra administrador de base; la integridad de un prefijo no detecta truncado completo sin anclaje externo. Mantener backups y acceso de sistema restringido. El CLI exige bases distintas, no migra evidencia y opera bajo umask privado; no corrige permisos de archivos preexistentes. Lecturas de dos bases no son globalmente atómicas; revalidar en cualquier operación posterior y no tratar status como permiso durable.

Los tests usan dos archivos de evidencia en memoria, verifican aprobación limitada, rechazo/aplazamiento, conflictos, caducidad y append-only. No hay cambios en WooCommerce ni llamadas de proveedor. INT-16E requiere una política adicional de importación, identidad del revisor autenticada y revalidación de los datos comerciales reales antes de cualquier escritura.
