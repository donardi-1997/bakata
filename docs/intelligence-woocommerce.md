# INT-09 — Integración WooCommerce

Bakatá Core carga DraftBridge como API PHP interna sin invocadores operativos. Solo se puede llamar desde WP-CLI, con BAKATA_CI_FIXTURES=1, home localhost/127.0.0.1 y usuario con manage_options y edit_products. No se registra botón de importación, REST, cron ni conexión a Dropi. No ejecutar la prueba en una tienda con datos comerciales.

## Flujo integrado en CI

1. INT-08 genera y conserva un snapshot sintético. INT-07 valida su contrato.
2. Seleccionar una fila exacta review-ready, cobertura 100%, sin bloqueos. No se trata el scoring sintético como aprobación comercial real.
3. Proporcionar por separado SupplierProduct sintético, evidencia de mapeo, costos unitarios, política comercial y una categoría WooCommerce existente. Solo producto simple, disponibilidad cero, moneda común y exponente 2. El precio observado del competidor no se utiliza como costo de proveedor. La equivalencia entre la investigación y el SKU del proveedor es una anotación revisada del llamador; no se infiere automáticamente.
4. DraftPlanner recalcula el precio candidato y exige contribución positiva y frescura de la observación de proveedor. La fecha histórica del snapshot de fixture se mantiene; no se acredita su vigencia real. No hay conversión de moneda.
5. Preview devuelve una huella SHA-256 de la propuesta vinculada a snapshot, candidato, observación de proveedor, plan de precios, categoría, referencia de mapeo, actor y política de frescura. El llamador debe confirmar exactamente esa huella y una referencia de aprobación para crear.
6. WooDraftImporter crea un borrador simple oculto, sin precio de venta, sin inventario vendible ni backorders. DraftBridge aplica una categoría explícita mediante CRUD y metadatos privados de trazabilidad. No importa imágenes, descripción, atributos variables ni impuestos de venta.
7. Recibo persistente no autoload en WordPress (por identidad de proveedor) con huella, evidencia, actor, estado y ID. La repetición exacta de un recibo exitoso devuelve el ID sin escribir. Un SKU preexistente, recibo pendiente/fallido, aprobación modificada o borrador alterado se bloquea para revisión manual.

## Concurrencia y seguridad

Se utiliza GET_LOCK de MariaDB/MySQL con nombre acotado por sitio/identidad, sin espera y comprobación de propiedad de conexión antes y después de escrituras. No hay SQL directo de productos ni pedidos. El lock serializa únicamente participantes de este puente; no bloquea plugins externos, ediciones manuales ni garantiza continuidad si se pierde la conexión. El recibo pendiente evita reintentos automáticos de efectos inciertos. No hay transacción distribuida entre recibo, CRUD y hooks; una excepción puede dejar un borrador parcial que requiere inspección. No se borra automáticamente ni se fuerza una publicación. La huella de aprobación no es firma, token de autorización ni prueba de consentimiento humano por sí sola; el CI simula la confirmación de un operador autorizado.

## Validación y límites

CI utiliza el resultado persistido del trabajo sintético INT-08 y prueba acceso sin permisos, candidato incompleto, categoría inexistente, fuente caducada, costos incompatibles, preview sin escritura, rechazo de confirmación incorrecta o mapeo modificado, precio candidato recalculado, borrador inerte, categoría, procedencia, recibo, replay, SKU ajeno, incertidumbre y edición posterior. Se ejecuta después del QA de storefront, sobre WooCommerce desechable.

Pendiente CI del PR. Antes de habilitar uso real: autorización de proveedores, evidencia y revisiones durables y autenticadas, vigencia del scoring real, vinculación de variante, concurrencia de importadores externos, conciliación de recibos, capacidad específica y UI de aprobación con nonce, retención y respaldo, política fiscal/comercial, pruebas de seguridad y reconciliación acumulada en main. No se publica ningún producto ni se activa el módulo en Lightsail.
