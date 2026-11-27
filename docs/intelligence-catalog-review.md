# INT-16A — Mesa de revisión de catálogo (preparación de INT-15H)

PR #59 integrado; validación de rollback y Foundation checks del PR aprobadas. No se ha sustituido Dropify en dev ni capturado el catálogo remoto. Esta mesa adelanta el trabajo de revisión sin depender del acceso al proveedor.

## Flujo de una página

1. Solo con autorización y controles de INT-15D/G, obtener una captura de una página del conector.
2. Archivar en BridgeArchive mediante el comando existente (JSON privado, operador explícito).
3. Usar el SHA-256 de página devuelto por ingest:

    cd services/intelligence
    python3 -m intelligence.catalog_review --db /ruta/privada/bridge.sqlite --page-sha256 HASH > /ruta/privada/catalog-review.json

4. Entrar en Bakatá Intelligence > Revisión de catálogo como administrador. Cargar JSON, revisar procedencia declarada, antigüedad, tipo, SKU, precios, existencias y filtros. Eliminar vista cuando termine.

El exportador abre SQLite en modo de solo lectura y reconstruye la página a partir de sus observaciones y procedencia. No conserva el JSON crudo original, ni su orden, por lo que la huella de origen es una referencia archivada, no una firma de la exportación. Se comprueba consistencia de esquema, identidad y recuentos. No se accede a credenciales ni al proveedor. Se preservan cadenas decimales, ceros iniciales y desconocidos. La UI acepta únicamente el formato compacto emitido; se rechazan campos adicionales y duplicados mediante reserialización exacta. La estructura no certifica autenticidad ni permiso de captura: no cargar datos de origen desconocido.

La vista es individual por usuario y sitio, con transient 15 minutos y eliminación explícita; puede quedar temporalmente en base/cache/backup. No se registra en medios. Sin endpoints REST, acciones de comercio, puntuaciones, márgenes, vínculos de evaluación o aprobación durable. Precios base y sugeridos no son costos finales ni se supone moneda. Stock positivo no es disponibilidad vendible. Capturas antiguas quedan marcadas, no convertidas en datos actuales. Solo una página (hasta 20 filas); no promete cobertura, no unifica tiendas.

CI añade pruebas de exportación read-only, contrato PHP y navegador real en WordPress con datos sintéticos. No habilita captura ni modifica el plugin Dropify activo. Próximo paso: aprobación de ventana/egress para INT-15H y después revisión de costos independientes y vinculación de evaluaciones; ninguna publicación automática.
