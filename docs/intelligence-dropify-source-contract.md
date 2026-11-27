# INT-15C — Contrato del catálogo Dropify 4.7.3

## Fuente inspeccionada

Archivo aportado por el operador: wc-dropi-integration.4.7.3.zip. SHA-256 bf23c6b1c5dd640aab3d38e3f370a41fbd60139ac60a1ce5f0347a059e9b6700, coincide con la auditoría existente. wc-dropi-integration.php y readme.txt declaran versión 4.7.3. El operador instaló Dropify desde el directorio de WordPress y desconoce la versión instalada; no se ha consultado su instalación, tokens, logs ni datos.

## Hallazgos estáticos

Rutas y líneas relativas al ZIP original:

| Evidencia | Conclusión |
|---|---|
| clasess/views/Products.php:61–63 | La vista ejecuta prepare_items y display en cada renderizado. |
| clasess/tables/Product_List.php:49–105 | Filtros por verificación, stock, descripción, categoría, bodega, tienda, búsqueda y orden. El listado invoca getProducts. |
| clasess/models/ProductsModel.php:87–176 | getProducts utiliza el cliente HTTP de WordPress y el token de la tienda elegida (o primera cuenta); consulta remota bajo demanda, no lectura de tabla de catálogo local. |
| clasess/models/ProductsModel.php:93–102; Product_List.php:97–104 | La consulta pide no_count y la paginación usa literalmente total_items = 9999. No es el total real comprobado. |
| clasess/tables/Product_List.php:61–76 | Tamaño inicial 10 en prepare_items; inicio 0 en página 1 y page * per_page en las siguientes. Si startData es un offset convencional, página 2 con 10 filas comienza en 20 en lugar de 10. Semántica de servidor no verificada; no se garantiza cobertura. |
| clasess/tables/Product_List.php:427–444 | Precio mostrado = sale_price más incremento fijo o porcentual del plan del proveedor, redondeado sin decimales; no afirmar costo final de adquisición. |
| clasess/tables/Product_List.php:341–396 | Precio sugerido se redondea; stock combina stock de bodegas o aplica lógica agregada sobre variantes. No representa disponibilidad por variante/destino ni una reserva. |
| clasess/tables/Product_List.php:274–296 | Categoría puede concatenar varias categorías; Bodega procede de user.name. |
| clasess/tables/Product_List.php:144–165 | Nombre se imprime en strong y acciones de fila aparte; ajustar exportador al markup. |
| clasess/models/TokenModel.php:37–47; Product_List.php:156,314; ProductsModel.php:183–195; Product_List.php:95 | El objeto de tienda asignado originalmente puede contener token; se serializan objetos en atributos de importación y se registran respuestas/listas. Riesgo de exposición de credencial; no copiar DOM, data-item ni logs. |
| clasess/models/ProductsModel.php:155–176 | Original desactiva verificación TLS y permite redirecciones. No iniciar consultas adicionales con esa configuración. |

No se llamó al endpoint, no se validaron tarifas, paginación remota, permisos o frescura, y no se presupone que estos hallazgos apliquen sin cambios a otra versión instalada.

## Diagnóstico sin token

El nuevo diagnóstico de Bakatá Intelligence lee el encabezado del plugin local en ruta estándar y compara cinco huellas SHA-256 con el archivo original (entrada, Product_List, ProductsModel, TokenModel y vista). Solo administrador, no ejecuta métodos Dropify, no inspecciona opciones/BD de credenciales y no hace red. Resultado: not-detected, original-files-match o requires-review; cada archivo matches-original/different/unavailable. Coincidir con cinco archivos no certifica toda la instalación ni su seguridad. Distinto no significa corregido. La prueba de navegador usa instalación desechable sin Dropify y comprueba el estado no detectado.

## Acción operativa

Verificar versión desde Plugins > Plugins instalados > Dropify; después del CI/despliegue, consultar diagnóstico local. Si coincide con original, suspender automatización/importación/despacho y evaluar correcciones acumuladas en sandbox aislado. Revisar registros y exposición de tokens de forma privada; no enviar capturas de la página Tokens, atributos data-item, HTML completo ni registros sin redacción. Rotar el token cuando se disponga de un conector seguro y se haya coordinado continuidad; no realizar rotación automática ni desactivar el conector sin autorización. No instalar el ZIP recibido ni sustituir archivos de la tienda en esta fase.

No se construye lector SQL de un catálogo inexistente ni un segundo cliente directo de la API privada. El exportador explícito de filas visibles es temporal; no hace consultas adicionales. El adaptador automatizado futuro requiere versión confirmada, autorización de acceso recurrente, controles TLS/secretos y un contrato revisado para leer resultados del conector existente o una exportación autorizada. Corregir o confirmar paginación antes de declarar cobertura. No asumir que se pueden capturar 9999 productos reales.
