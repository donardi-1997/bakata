# INT-17C — Dashboard administrativo de alertas

Depende de INT-17B (#66) y del radar #65. Integrarlos primero y verificar la rama contra main. En Bakatá Intelligence > Radar comercial se visualiza una página histórica del registro, con filtros por estado, prioridad, producto/SKU/ID, recuentos locales y procedencia.

    cd services/intelligence
    python3 -m intelligence.alert_dashboard --ledger /privado/alerts.sqlite --archive-ref ARCHIVO --price-threshold-bps 500 --store 7 > /privado/dashboard.json

Abrir el archivo privado desde el administrador. Si hay next_after, exportar otra página con --after CURSOR. Máximo 20 alertas por exportación, 256 KiB. Los recuentos y filtros son de la página, no métricas globales. El exportador usa una conexión read-only y valida los hashes e historial con el lector existente, sin inicializar ni migrar. Conserva referencias de páginas y eventos, no la cadena completa. No hay verificación criptográfica de autenticidad del archivo cargado en WordPress; los hashes son referencias, no autorización. La UI valida estructura, identidad de señal, fechas, recuentos y campos permitidos; no certifica los estados actuales ni recalcula señales o costos. No cargar archivos de origen desconocido.

Solo administradores; carga y limpieza POST con nonce. Vista individual por sitio y usuario en transient 15 minutos, sin medios; puede quedar temporalmente en caché/base/respaldo. Los estados se consultan, no se alteran desde WordPress. No consultas a proveedor ni avisos externos. CI genera capturas sintéticas, ejecuta el radar y ledger reales, registra una resolución, exporta y valida contrato PHP y navegador (permisos, nonce, escape HTML, filtro y limpieza). La captura de CI no representa datos comerciales reales.
