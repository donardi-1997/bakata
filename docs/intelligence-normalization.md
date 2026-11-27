# INT-04 — Normalización y deduplicación

El módulo es offline, puro y no modifica observaciones, catálogos, precios ni pedidos. La clave de identidad sigue siendo (source, external_id). La clave de observación añade fecha UTC; latest_observations genera una vista ordenada de la última observación por identidad, detecta conflictos de una misma clave y conserva el historial original en el almacén existente.

## Normalización

- Títulos: Unicode NFKD, casefold, eliminación de diacríticos y separación de palabras para propuestas de búsqueda, nunca como identificador comercial.
- Marca y modelo: comparación normalizada NFC, casefold y espacios, conserva signos, sufijos y ceros iniciales. No se extrae marca/modelo desde el título.
- GTIN-8/12/13/14: formato decimal y dígito de control módulo 10; representación de 14 dígitos. No certifica asignación GS1 ni autenticidad.
- Variantes: pares explícitos atributo/valor, sin conversión de unidades, inferencia de equivalencias, traducción de colores ni alias. Los atributos anotados deben corresponder a la clave exacta de la observación y tener referencia de evidencia. La referencia por sí sola no certifica que la evidencia sea cierta.

## Reglas de comparación

1. No comparar observaciones duplicadas de una identidad; distintos IDs de una misma fuente no se vinculan.
2. Cualquier contradicción explícita en GTIN, marca, modelo o variante común bloquea la propuesta.
3. GTIN coincidente validado o marca y modelo coincidentes generan propuestas revisables. Título normalizado coincidente es únicamente una pista débil.
4. Si falta cobertura de variantes se informa. Toda aprobación necesita confirmación explícita de equivalencia de variante y referencia de revisión de 1 a 128 caracteres ASCII de `A-Z`, `a-z`, `0-9`, `.`, `_` o `-`, sin normalización; el título por sí solo no permite aprobar. La referencia no autentica ni autoriza al revisor.
5. ReviewedLink vincula dos claves de observación concretas. No fusiona registros, no deduce vínculos transitivos y no se reutiliza automáticamente para capturas futuras.

No se utilizan precios, SKU local ni similitud de texto como prueba suficiente de equivalencia. Los resultados son propuestas deterministas, no probabilidades. Se limita la vista a 1.000 observaciones y el comparador a 200 identidades (hasta 19.900 pares). Para catálogos mayores se necesitarán índices de candidatos.

## Validación y límites

Las pruebas sintéticas descubiertas por unittest verifican normalización, GTIN, historial, duplicados, conflictos, datos incompletos, aprobación explícita y límites. El archivo comercial local puede persistir una revisión de equivalencia con sus anotaciones y huella; la comparación pura no verifica su autenticidad ni consulta automáticamente ese archivo. No hay interfaz ni autorización de revisores en este flujo: las anotaciones y vínculos se suministran por un llamador confiable. Los pares no aprobados no son comparables automáticamente; la comparación de precios también exige contexto de moneda, fecha, variante, impuestos, envío y fuente.
