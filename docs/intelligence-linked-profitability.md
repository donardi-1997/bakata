# INT-16B — Expediente de rentabilidad vinculada

Primera pieza backend de la revisión comercial. Independiente del PR #60 (mesa de catálogo); no cambia la interfaz de WordPress todavía. No sustituye Dropify, no captura el catálogo remoto y no habilita publicación.

## Uso local y privado

Después de capturar y archivar una observación autorizada, registrar una evaluación en CommercialStore con costos independientes revisados y vincularla explícitamente mediante BridgeArchive link-score (INT-15D). El costo de compra no es el precio base que aparece en Dropify. El operador selecciona un ID de vínculo exacto; no se selecciona automáticamente la evaluación más favorable.

    cd services/intelligence
    python3 -m intelligence.linked_review --db /ruta/privada/bridge.sqlite --commercial /ruta/privada/commercial.sqlite --link-id ID

El comando abre los dos archivos existentes en modo read-only, sin migraciones. Comprueba identidad, tipo simple, stock reportado positivo, observación de catálogo más reciente en el archivo, referencia de mapeo, coincidencia de costo independiente COP, digest de evaluación y cronología. Reconstruye la evaluación con el motor de scoring y compara su resultado archivado. Reevalúa frescura de evidencia al momento de exportar. Rechaza observación vencida (>24h), sustituida por otra observación, evidencia vencida, costo diferente, evaluación incompleta o digest alterado. Si hay datos faltantes no calcula un margen ficticio.

El JSON contiene precios observados separados de los costos revisados, contribución y margen del escenario, puntuación y componentes, ventana de validez, referencias de evidencia y vínculo; montos económicos en centavos COP. No incluye URL, credenciales, justificaciones de texto libre o respuesta remota. approval_granted=false y woo_mutation=false. El margen es contribución del escenario con los costos explícitos, no utilidad neta ni garantía de resultado. La integridad del digest no prueba autenticidad del operador o la veracidad de costos; se requieren revisiones de procedencia. La validez es una cota analítica; nueva evidencia puede invalidar el expediente antes. No garantiza disponibilidad vendible, ni que la observación local sea la última del proveedor. Lecturas separadas no ofrecen snapshot global atómico entre bases.

Pruebas unitarias sintéticas en Foundation checks: coherencia de cálculo, independencia de precios, read-only, expiración, supersesión, costo alterado y digest incorrecto. Siguiente paso: después de fusionar la mesa de revisión, integrar presentación del expediente en la interfaz y añadir decisiones humanas persistentes, sin publicación automática.
