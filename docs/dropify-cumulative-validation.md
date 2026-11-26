# Validación acumulada y base criptográfica de Dropify 4.7.3

Se verificó el ZIP suministrado por el usuario (SHA-256 bf23c6b1c5dd640aab3d38e3f370a41fbd60139ac60a1ce5f0347a059e9b6700) con los tres parches acumulados de main. Los cuatro archivos del generador y las tres suites PHP utilizados localmente coincidieron con los SHA de blobs Git. PHP local 8.4.24: 35 archivos sin errores de sintaxis, 8 casos de rechazo AJAX, 12 aserciones de reserva/consultas y 16 aserciones HPOS de lectura con stubs. El runner nuevo repitió toda esa validación con éxito.

Ejecutar desde el repositorio, en un entorno descartable sin salida de red:
    python3 scripts/verify-dropify.py /ruta/original.zip

El runner crea una copia temporal, aplica los parches, verifica los PHP y ejecuta las tres suites; elimina la copia al terminar. No instala ni activa WordPress ni Dropify. El ZIP no se versiona ni se descarga en CI; la prueba acumulada requiere el archivo local autorizado. CI ejecuta el test de reserva concurrente real por separado; PR #28 lo aprobó.

## Cifrado aislado

TokenVault (tools/dropify-quarantine/token-vault.php) utiliza libsodium XChaCha20-Poly1305 con clave externa de 32 bytes, nonce aleatorio, contexto estable sitio/tienda autenticado, sobre versionado y key ID. No acepta texto plano al descifrar. La prueba local de 18 aserciones incluye manipulación, contexto y clave incorrectos, longitud máxima, redacción de debugInfo y recifrado con otra clave. CI ejecutará la prueba en PHP 8.3. No registrar ni serializar instancias ni claves; no se protege frente a compromiso del proceso PHP.

Este componente NO está conectado a Dropify: no cifra su base de datos actual ni crea claves reales. El código original contiene token VARCHAR(1000) en db_tables/token_db_table.php, usa búsquedas por igualdad del token en TokenModel y copia _dropi_token a postmeta desde ProductsModel, Helper y OrdersModel. El sobre cifrado aleatorio no admite igualdad directa y puede superar VARCHAR(1000). Sustituir sin migración rompería consultas, borrado y sincronización.

Antes de integración: definir identidad inmutable de tienda y referencia por ID, almacenamiento cifrado con capacidad suficiente, índice de búsqueda no reversible con clave separada si se necesita deduplicar tokens, migración transaccional o reinicio autorizado de credenciales sin afectar productos, eliminar copias de token en metadata/opciones, revisar todos los consumidores y rutas antiguas, probar rotación y recuperación con clave externa y respaldos. No utilizar tokens reales hasta completar estos controles. Despacho permanece deshabilitado en la compilación de validación.

Pendiente: pruebas positivas de WordPress real, ambos motores de pedidos, aislamiento de red efectivo, almacenamiento/rotación integrados y sandbox autorizado. No habilitar Dropify ni ampliar CD para instalarlo en esta fase.
