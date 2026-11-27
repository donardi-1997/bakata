# INT-16E — Preparación de borradores aprobados

Depende de INT-16D (#63), por lo que se basa en su rama. Integrar #63 primero y verificar después. INT-16C (#62) continúa en paralelo. No se abre un endpoint ni se registra un hook de importación.

## Plan offline

El módulo intelligence.approved_draft consulta la última decisión y revalida evidencia en los archivos originales. Exige SHA-256 explícito de la decisión, mapeo exacto, título editorial, categoría, referencia numérica de revisor y política de precio explícita. Conserva los costos independientes COP y el escenario evaluado. El plan incluye la huella de decisión, expediente y evaluación y establece draft, hidden, stock 0, sin precio activo. Un digest no es firma ni permiso de importación. El revisor numérico aún es una declaración del operador CLI, no autenticación. Se comprueba el estado al preparar, no se reserva una decisión entre bases. Nueva evidencia o rechazo puede invalidarlo.

    cd services/intelligence
    python3 -m intelligence.approved_draft --ledger /privado/decisions.sqlite --archive-ref ARCHIVO --bridge /privado/bridge.sqlite --commercial /privado/commercial.sqlite --store ID --product ID --decision-sha256 DIGEST --mapping-ref MAPEO --title TITULO --reviewer-id ID --category-id ID --target-bps 2500 --step-minor 100000 --ceiling-minor 20000000

Los valores de política del ejemplo son ilustrativos, no política de producción. El plan debe satisfacer el margen y paso explícitos; el consumidor CI exige además que el precio propuesto por DraftPlanner coincida exactamente con el escenario revisado. Si difiere, revisar política y evaluación, no sustituir silenciosamente precio. El CLI abre evidencias read-only; DecisionLedger abre su archivo existente y verifica esquema. No hace escrituras Woo.

## Ensayo de extremo a extremo

Foundation checks construye desde archivos SQLite sintéticos una evaluación, vínculo, decisión y plan; obtiene ID de administrador y categoría fixture en WordPress de CI. ApprovedDraftSandbox comprueba JSON canónico, huella explícita, alcance fixture, usuario WordPress, categoría, moneda, caducidad y precio recalculado; reutiliza WooDraftImporter. Serializa el SKU, conserva recibo pending ante fallo incierto, rechaza SKU o recibo existente, comprueba estado inerte y conserva huellas de decisión y plan. No reintenta automáticamente. Solo WP_CLI + BAKATA_CI_FIXTURES=1 + sitio localhost/127.0.0.1 + administrador con edición de productos. Clase no cargada por bootstrap; solo se requiere en la prueba. Las pruebas no autentican el archivo ni garantizan protección contra otros escritores o efectos de terceros. No se utiliza token ni proveedor.

## Bloqueo operativo

No habilitar el consumidor CI en dev ni producción. Falta identidad autenticada de revisor vinculada a la decisión, canal de confianza entre Intelligence y WooCommerce, revalidación contemporánea bajo coordinación de escrituras, idempotencia/reconciliación operativa y autorización expresa. Captura real y sustitución Dropify siguen pendientes. El borrador de CI no es un producto vendible ni una aprobación de publicación.
