# INT-14 — Calibración del scoring comercial

Se introduce una evaluación prospectiva de la rúbrica int06-v1, sin alterar los siete pesos ni los bloqueos existentes. No hay datos comerciales reales, resultados de ventas importados ni nueva rúbrica calibrada. El objetivo de esta fase es obtener evidencia comparable antes de modificar el algoritmo.

## Diseño de cohortes

- Registrar una cohorte antes de iniciar su ventana de 30 días. Declarar mínimo de pedidos entregados y referencia a protocolo de exposición (población, categoría, precio, inventario, inversión publicitaria, canal y comparabilidad). El éxito operativo se define como alcanzar dicho mínimo y contribución total estrictamente positiva. No se impone un umbral universal; el test usa 10 pedidos ficticios.
- Inscribir una identidad comercial revisada por grupo, una identidad fuente/ID y una evaluación por cohorte antes del inicio. No reusar evaluaciones ni incluir candidatos bloqueados, incompletos o fuera de vigencia; solo COP para esta versión. Se conserva ID y hash del baseline, versión, costos y evidencia originales. La evaluación debe existir antes de inscribir y no superar siete días de antigüedad al inicio.
- Tras los 30 días y 14 adicionales de maduración, registrar agregados completos por grupo: pedidos entregados, pedidos devueltos (subconjunto de entregados), ventas brutas y contribución económica del mismo periodo, en unidades menores COP. Usar una definición de contribución coherente con INT-06 y conciliada con costos, impuestos, devoluciones, comisiones, logística y publicidad aplicables. No importar datos de clientes ni IDs de pedidos. Cero ventas comprobadas es un resultado; ausencia de datos o exposición no confirmada es dato faltante, no fracaso.
- La API recibe tiempos y referencias del operador local confiable. No prueba criptográficamente inscripción prospectiva, identidad del revisor, equivalencia de variantes ni exposición. No admite editar o reemplazar resultados ya registrados; una corrección exige revisión y protocolo de auditoría externo. No considerar grupos coincidentes entre cohortes como observaciones independientes.

## Indicadores

| Indicador | Definición |
| --- | --- |
| Cobertura | Resultados observados / inscritos |
| Éxitos | Pedidos entregados >= mínimo y contribución positiva |
| Concordancia del ranking | Proporción de pares éxito/no éxito correctamente ordenados por score, contando empate como 0,5; en porcentaje |
| Concordancia por criterio | Misma comparación para cada componente, como diagnóstico descriptivo |
| Tasa de éxito por banda | Éxitos / observados en intervalos [0,25), [25,50), [50,75), [75,100] |
| Error absoluto medio de margen | Media de diferencias absolutas entre margen de escenario y contribución real / ventas brutas, en puntos porcentuales; excluir denominador cero |
| Tasa observada de devolución | Total devueltos / total entregados, no media de tasas por producto |

Para mostrar concordancia y tasas: cohorte madura, cobertura 100%, al menos 30 productos y al menos cinco éxitos y cinco no éxitos; cada banda necesita cinco observaciones, margen requiere 30 denominadores positivos. Umbrales provisionales descriptivos, no potencia estadística ni garantía de generalización. Si no se cumplen, mostrar recuentos y estado insufficient-evidence, métricas correspondientes null. El reporte se limita al as_of y no usa resultados registrados después de esa fecha.

Score 0–100 es ordinal, no probabilidad: no interpretar concordancia como precisión de predicción ni tasa de éxito como probabilidad individual. No usar Brier score ni error de probabilidad sobre esta rúbrica. Comparar criterios no demuestra efecto causal ni justifica reponderación. Sesgos de selección/exposición, agrupación, devoluciones tardías y datos incompletos necesitan revisión; el protocolo no los verifica automáticamente.

## Persistencia y operación

CommercialStore migra transaccionalmente esquema v1 a v2 (también instalaciones nuevas) con tres tablas: calibration_cohorts, calibration_members, calibration_outcomes. FK, unicidad, máximo 100 cohortes y 1.000 miembros por cohorte, límites de archivo existentes. No modifica evaluaciones antiguas. Antes de migrar una base real, detener escritores, respaldar y verificar integridad; no se ha aplicado migración a producción. API Python local Calibration.create/enroll/outcome/report; no endpoint, tarea, interfaz administrativa ni integración de pedidos todavía.

## Decisión sobre pesos

Mantener int06-v1 como referencia. Solo después de reunir cohortes reales maduras, revisar definiciones y exposición comparable, establecer hipótesis y criterios de aceptación antes de evaluar una nueva versión. Separar cohortes de desarrollo y validación temporal independiente; evitar reutilizar holdout para ajustar pesos. Exigir revisión humana, intervalos de incertidumbre y seguimiento de estabilidad antes de promover cambios. INT-14 no optimiza ni cambia pesos, no deriva demanda de precios ni estima fiabilidad por anuncios. Para esos indicadores se necesitan datos autorizados de tráfico, ventas, inventario, entregas y campañas que aún no están disponibles.

Nueve pruebas sintéticas: migración, inscripción prospectiva, baseline, madurez, datos faltantes, concordancia, empates, clases ausentes e integridad del baseline. CI ejecutará las pruebas existentes y nuevas. La siguiente fase INT-15 desarrollará la integración comercial con Dropi a través del conector WooCommerce autorizado, no mediante endpoints privados.
