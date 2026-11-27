# INT-06 — Product scoring

Motor de evaluación offline, determinista y explicable. No publica productos ni fija precios. Rúbrica provisional int06-v1, pendiente calibrar con datos reales de bakatá.

## Criterios

| Criterio | Peso | Evidencia para revisión | Anclas 0 / 25 / 50 / 75 / 100 |
| --- | ---: | --- | --- |
| Rentabilidad potencial | 25 | Escenario unitario completo revisado | Margen <=0% / 7,5% / 15% / 22,5% / >=30%; interpolación lineal |
| Demanda | 20 | Señales recientes de mercado, muestra y período documentados | Nula / débil / moderada / fuerte / fuerte y sostenida |
| Fiabilidad del proveedor | 15 | Historial de entregas, exactitud de stock, incidencias y autorización | Inaceptable / deficiente / suficiente / buena / excelente |
| Facilidad logística | 15 | Cobertura, costo, tamaño, fragilidad y plazo confirmado | Inviable / compleja / manejable / sencilla / muy sencilla |
| Potencial publicitario | 10 | Creatividades autorizadas, prueba de audiencia y restricciones | Inviable / bajo / moderado / alto / alto y validado |
| Diferenciación | 10 | Comparables y propuesta verificable de valor | Ninguna / baja / moderada / clara / clara y difícil de replicar |
| Riesgo de devolución | 5 | Datos de defectos, devoluciones, garantías y condiciones | Inaceptable / alto / moderado / bajo / bajo y validado |

Las seis puntuaciones manuales son juicios explícitos en los niveles 0,25,50,75,100, con referencia de evidencia y justificación. Un nivel 0 exige evidencia negativa, no ausencia de datos. No inferir demanda por precio, proveedor fiable por publicidad ni riesgo por categoría. Estas anclas cualitativas no constituyen todavía un instrumento calibrado; se requerirá calibración y revisión consistente entre operadores.

## Cálculo

Puntos = puntuación del criterio × peso / 100. La suma solo se emite cuando la cobertura ponderada alcanza 100% y la observación no es caduca. No reponderar criterios faltantes. Cada componente muestra puntuación, puntos, evidencia y razón. Las referencias son anotaciones de un llamador confiable, no prueba criptográfica ni permisos autenticados.

Los cálculos decimales, incluido `margin_pct`, usan un contexto local fijo de 28 dígitos y redondeo half-even; el total se cuantiza a dos decimales con half-up. Precisión, redondeo, límites de exponente, traps y flags del llamador no alteran el resultado ni se modifican. El ranking compara los totales sin redondearlos de nuevo. Los importes admitidos están entre 0 y 10¹² unidades menores, con precio de venta estrictamente positivo cuando se conoce.

Rentabilidad: escenario en la misma moneda que la observación, centavos COP/USD/EUR. Precio bruto de venta menos costo de proveedor, envío asumido, comisión fija, reserva de devoluciones, otros costos y deducciones variables agregadas en bps (redondeadas hacia arriba). Sin valor implícito para costos desconocidos. Margen = contribución / precio bruto. Se sigue la convención matemática de Bakatá Core Pricing Preview, pero no se invoca el motor PHP ni se garantiza paridad completa de políticas fiscales, redondeo por concepto, promociones o asignación por pedido. El precio de mercado observado no se toma automáticamente como costo ni precio de venta.

Bloqueos iniciales: contribución <=0, evidencia explícita de proveedor o riesgo de devolución en nivel 0, observación caduca. Revisión posterior de requisitos legales, seguridad de producto, propiedad intelectual, stock, pagos y condiciones comerciales sigue siendo obligatoria. No son puertas automáticas de publicación.

Estados: incomplete, blocked, review-ready. Solo review-ready entra al ranking; no equivale a aprobado. Ranking de hasta 1.000 identidades, misma versión de rúbrica, fecha y ventana de vigencia; desempate determinista por clave. Los datos de evaluación deben vincularse a la observación exacta, con fecha de revisión no anterior a ella ni futura. La ventana máxima de vigencia es 30 días, seleccionada explícitamente por el llamador.

## Validación y alcance

Las pruebas sintéticas cubren pesos, contribución, redondeo, aislamiento del contexto decimal y valores límite, datos faltantes, bloqueos, vigencia, vínculos, validación y ranking. No se consulta ninguna fuente ni se guarda un scoring comercial real. Las revisiones, evidencia y resultados no se persisten todavía; no hay interfaz ni permisos de revisor. La siguiente fase, INT-07, construirá el panel y los contratos de lectura/revisión, sin activar fuentes vivas ni publicación automática.
