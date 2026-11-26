# INT-05 — Inteligencia de precios

Motor offline y de solo lectura. Los precios originales permanecen inalterados; no modifica WooCommerce, no estima rentabilidad ni recomienda precios de venta automáticos.

## Historial

ObservationStore.history_rows consulta una identidad (fuente, identificador externo) con SQL parametrizado, hasta 1.000 registros sin truncamiento silencioso. price_history exige una sola identidad y moneda (COP, USD o EUR, centavos), elimina repeticiones idénticas, rechaza conflictos y observaciones futuras, y ordena cronológicamente. Reporta mínimo, máximo, mediana exacta (puede contener medio centavo), número de precios conocidos y desconocidos, antigüedad del último dato y variación porcentual entre las dos últimas observaciones. Un precio desconocido no se sustituye por cero ni se saltan huecos; una base cero no admite variación porcentual. Los porcentajes usan Decimal y redondeo half-up a dos decimales.

El historial representa precios anunciados del identificador, no confirma continuidad de variante, disponibilidad o condiciones de compra.

## Comparación de mercado

ReviewedPriceContext liga costos y escenario a la clave exacta de observación, con referencia de evidencia revisada. El total unitario entregado suma precio anunciado, impuestos adicionales y envío; si los impuestos están incluidos no se duplican. Si precio, base fiscal, impuesto adicional necesario o envío se desconocen, se rechaza la comparación. Cero explícito es válido; no se calcula IVA ni se consultan transportadoras.

market_comparison exige 2–50 fuentes distintas, misma moneda, destino, condición, tipo de precio (minorista o proveedor) y cantidad unitaria. Antigüedad máxima explícita de hasta 30 días y desfase máximo explícito entre capturas. Se requiere un ReviewedLink por cada par de observaciones, sin inferir transitividad; una captura nueva requiere revisión nueva. Los identificadores de fuente no garantizan independencia comercial de los operadores.

Devuelve totales con claves de procedencia, mínimo, máximo, mediana, dispersión absoluta y variación del precio mínimo respecto al máximo (negativa si es menor). No constituye margen, ahorro garantizado, costo de adquisición definitivo ni recomendación. No hay conversión FX implícita, descuentos inferidos ni precios faltantes inventados. Antes de comparar deben verificarse también cargos obligatorios, condiciones de oferta, equivalencia de variante y disponibilidad: el contexto inicial no modela cada uno de ellos.

## Validación y límites

Diez pruebas sintéticas descubiertas por unittest cubren lectura del historial, duplicados, desconocidos, base cero, precisión, escenarios, impuestos, transporte, monedas, vigencia y revisiones directas. Los costos y vínculos son anotaciones de un llamador confiable: aún no se autentican ni persisten las revisiones, no se implementa interfaz de autorización y no se habilita red. No usar con datos comerciales reales hasta completar los controles operativos de etapas posteriores.

INT-06: scoring explicable con evidencia de demanda, logística, diferenciación, proveedor y rentabilidad, sin confundir precio observado con costo o margen.
