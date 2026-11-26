# Validación final del rediseño lifestyle

## Reconciliación
Los PR #32 y #33 se fusionaron inicialmente en ramas intermedias. La revisión de main posterior a #35 confirmó que faltaban el megamenú y las colecciones. Este PR recupera sus cambios a partir del commit 19b91af15fc2552edb52d94f08339b0ea8c2eafe, conservando las tarjetas y búsqueda de #35. Se restauran también las fixtures aisladas y las pruebas de regresión.

## Criterios de salida
- PR #36, #37, #38, #39 y reconciliación integrados en main, con checks requeridos sobre su estado final.
- CI de main exitoso: lint, Compose, pruebas de portada, navegación, búsqueda, catálogo, producto, carrito, checkout y cuenta, aislamiento de pedidos y controles de Dropify.
- Presupuestos SEO/performance de #39 aprobados; Lighthouse revisado como diagnóstico.
- Revisar capturas en resoluciones móviles y escritorio; verificar manualmente teclado, lector de pantalla, contraste y dispositivos reales.
- Confirmar deploy_dev exitoso del SHA final de main y comprobar el entorno de desarrollo sin enviar pedidos ni ejecutar pagos.
- No publicar productos, no transmitir pedidos a proveedores, no cambiar credenciales ni protecciones.

Los PR fusionados no constituyen por sí solos evidencia de despliegue o de presencia de todos los cambios. Comprobar los archivos del SHA desplegado. La confirmación de Core Web Vitals de campo, la fotografía definitiva del catálogo y la validación de pagos en sandbox quedan fuera de la aprobación automática de esta fase.

## Corrección de QA tras integración de fases 6–9

La ejecución 45896660213 falló en carrito a 1440 px tras recarga con cupón; 320 y 768 px pasaron. WooCommerce usa un contenedor sticky cuando la referencia del CTA queda por debajo del viewport y oculta ese contenedor en escritorio. La prueba desplaza el wrapper nativo persistente a la vista, exige visibilidad y ejecuta un click de prueba (trial, sin navegación). Se conservan validaciones de sesión, cantidades, descuento, totales, enlace local, accesibilidad y eliminación; no se fuerza visibilidad mediante CSS ni se omite la comprobación. Se añade diagnóstico de geometría del CTA en caso de fallo. Pendiente confirmar la nueva ejecución de CI.
