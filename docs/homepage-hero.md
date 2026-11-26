# Homepage · hero Bakatá

Primera sección comercial implementada a partir del diseño aprobado Raíz contemporánea. El copy y CTA se renderizan como HTML real (no texto incrustado en imagen); el shortcode bakata_hero se registra en el tema y se usa desde la plantilla front-page. En el editor se verá el shortcode, no un bloque editable de alta fidelidad. El CTA resuelve la página de tienda WooCommerce; si no existe catálogo ni tipo product, se omite.

La imagen assets/images/hero-editorial.webp (600×305, 6778 bytes) procede de un recorte de una composición editorial generada para el proyecto, no de fotografía de inventario. Solo se usa como ambientación decorativa, sin afirmar disponibilidad de los artículos representados. Se conserva el patrón vectorial original del kit como textura sutil. Imagen local, alt vacío por su función decorativa, dimensiones explícitas, prioridad alta y sin lazy-load. No hay solicitudes de imágenes a terceros. Evaluar reemplazar o añadir resolución mayor si los tests visuales lo requieren; no se promete nitidez retina con este recorte. Se usa una única composición, sin carrusel ni indicadores simulados.

La interfaz usa tokens existentes y CTA verde para contraste. Layout mobile-first: imagen bajo copy, dos columnas desde 48rem, ancho máximo 1200px. El fondo no depende de la imagen. No se publican precios, opiniones, promociones, categorías ni productos ficticios.

CI comprueba que la sección, el CTA y la imagen existen en la salida de WordPress y que la imagen servida conserva su hash Git. Revisar en navegador anchos 320/375/768/1024/1440, contraste efectivo, foco, zoom, enlace y métricas de rendimiento antes de declarar validación visual completa.
