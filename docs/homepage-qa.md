# QA de homepage

El job obligatorio checks ejecuta pruebas reales con Chromium vía Playwright y axe-core. No se instala nada en Lightsail. Se reutiliza el WordPress local desechable de CI y sus fixtures. Las pruebas de carrito no completan checkout ni crean pedidos, y el contexto del navegador bloquea destinos externos. Lighthouse es un diagnóstico separado, no una condición de merge por puntuación. 

## Cobertura
- Catálogo vacío: 375 y 1440 px.
- Catálogo poblado con datos de prueba: 320, 375, 576, 768, 1024, 1440 y 1920 px.
- Presencia de secciones, un H1 principal, ausencia de scroll horizontal, fuentes realmente cargadas, imagen del hero, errores JS y respuestas locales HTTP >=400.
- Menú móvil accesible mediante Tab/Enter, foco visible, navegación de escritorio.
- axe-core: reglas WCAG 2.0/2.1/2.2 A/AA disponibles en las etiquetas configuradas. Cualquier violación detectada bloquea checks. No implica conformidad WCAG completa.
- Enlace al catálogo, búsqueda de un producto real del fixture, formulario de carrito y confirmación mediante Store API. No se comprueba compra completa ni medios de pago.
- Capturas completas, JSON de axe y resúmenes por estado; informes como artefactos de GitHub Actions, retención 7 días. Son evidencia visual, todavía no comparación pixel a pixel contra un baseline aprobado.
- Lighthouse móvil simulado, JSON con métricas de laboratorio y diagnósticos. Revisar LCP/CLS/TBT y fijar presupuestos tras obtener línea base; INP de usuarios reales requiere telemetría de campo. No se bloquea por puntuación ni se confunde laboratorio con CrUX.

## Ejecución local
Usar solo una instancia nueva y descartable en http://localhost:8080/ (nunca el servidor remoto ni una base con datos comerciales). Seguir los pasos Bootstrap, fixtures y QA del workflow ci.yml en el orden indicado. Node/npm compatibles; instalar paquetes con npm --prefix qa install --ignore-scripts --no-audit --no-fund --package-lock=false y Chromium con qa/node_modules/.bin/playwright install --with-deps chromium. BAKATA_CI_FIXTURES=1 habilita pruebas; las fixtures tienen su propia protección por dominio local. Los paquetes directos tienen versión exacta; falta generar y revisar lockfile de npm para fijar todas las dependencias transitivas. La acción de artefactos está fijada por SHA. Revisar los artefactos antes de fusionar el primer cambio. 

Pendiente: Firefox/WebKit, dispositivos físicos, auditoría manual por lector de pantalla y zoom, baseline de regresión visual, presupuestos de performance y pruebas de checkout en sandbox. La prueba solo valida la homepage, enlaces y flujo parcial, no la tienda completa.

## Correcciones de la primera ejecución
El nombre accesible del botón conserva el texto visible completo al inicio (`Añadir al carrito: nombre`), según Label in Name. Se mantiene axe-core sin excepciones. La búsqueda prueba resultados múltiples y admite la redirección nativa de WooCommerce para una coincidencia exacta, verificando el producto de destino. Se conserva la comprobación real del carrito y su cantidad mediante Store API.
