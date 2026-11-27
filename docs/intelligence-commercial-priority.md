# INT-17D — Priorización comercial basada en evidencia

Backend offline, depende del lector de alertas INT-17C (#67), del ledger #66 y del radar #65; integra expedientes INT-16B ya disponibles. Integrar los PR dependientes primero y validar contra main. No modifica la UI ni realiza decisiones, importaciones, publicación o notificaciones.

    cd services/intelligence
    python3 -m intelligence.commercial_priority --alerts /privado/alerts.sqlite --bridge /privado/bridge.sqlite --commercial /privado/commercial.sqlite --archive-ref ARCHIVO --store 7 --price-threshold-bps 500 --min-score-bps 7500 --min-margin-bps 2500

Los parámetros del ejemplo (cambio de precio 5%, score 75/100, margen mínimo 25%) son ilustrativos y explícitos, no política aprobada para Bakatá. El margen se compara con contribución/venta exactos en centavos COP, sin redondear el porcentaje mostrado. No se convierte precio base observado en costo de compra.

Por tienda, agrupa las alertas abiertas o reconocidas por identidad de producto, conserva referencias de alerta y evento, y consulta la última pareja de observaciones archivadas. Solo señales de esa pareja cuentan como actuales en el archivo. Una alerta resuelta no entra; las anteriores no se cierran automáticamente. Una alerta histórica prioritaria sin resolver exige atención. Se separa:

- urgent-review: captura vencida/futura, stock simple no positivo o riesgo prioritario de la pareja actual sin atender.
- historical-risk-review: riesgo prioritario histórico aún abierto.
- evidence-review: vínculo de evaluación actual ausente, múltiple o no revalidado.
- candidate-for-review: señal actual de disminución del precio base reportado o reaparición de stock, sin los riesgos anteriores, expediente revalidado y umbrales satisfechos. Es candidato a investigación, no compra ni importación.
- below-policy: evaluación vigente pero debajo de umbral de score o contribución.
- monitor: señales solo históricas no prioritarias, o evaluación vigente sin señal actual de oportunidad.

No se elige el vínculo con mayor score entre múltiples vínculos. Se revalida el único vínculo actual con el motor existente, evidencia de costo COP independiente, digest, vigencia y correspondencia de identidad. En caso de error de datos se retiene el candidato para revisar evidencia sin mostrar score. Errores SQLite o falta de procedencia del catálogo bloquean el reporte. La clasificación no consulta el ledger de decisiones: no autoriza borradores y no sustituye un rechazo o aplazamiento humano.

Hasta 25 identidades por lote, 100 alertas históricas por identidad (más bloquea el lote). Cursor lexicográfico next_after, incluso si la página queda vacía por alertas resueltas. Orden de categorías anterior; dentro de una categoría score descendente, luego margen de contribución y ID; ausencias sin score inventado. Recuentos y ranking locales al lote, no globales. No se detectan productos sin alertas registradas. Las tres bases se abren read-only, con transacciones separadas: no existe snapshot global atómico ni verificación criptográfica de que el alcance declarado identifica la misma instalación. Usar archivos privados coherentes y revalidar antes de cualquier acción. Los datos son históricos, sin garantía de disponibilidad ni resultado comercial.

Pruebas sintéticas en Foundation checks: candidato revalidado, umbrales, múltiples vínculos, prioridad de stock, alertas anteriores y resueltas, aislamiento, expiración, digest alterado y conflicto entre señales. Siguiente: presentar la lista en el dashboard y definir política de notificaciones antes de activar entrega.
