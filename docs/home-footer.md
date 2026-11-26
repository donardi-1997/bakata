# Homepage · footer e información de compra

La banda de información contiene enlaces reales a catálogo y cuenta. Envíos, cambios/devoluciones y contacto aparecen únicamente si se configura una página publicada, de tipo page y sin contraseña. El footer muestra navegación WooCommerce, logo negativo oficial, tagline y copyright dinámico. Privacidad y términos se resuelven desde las opciones nativas de WordPress y WooCommerce, sin enlazar borradores ni páginas privadas. No hay afirmaciones de cobertura, plazos, devoluciones garantizadas, pasarelas, certificaciones ni redes sociales inventadas. Sin newsletter hasta definir consentimiento y proveedor.

## Configuración editorial
Crear y revisar páginas reales antes de publicar. Configurar privacidad y términos en los ajustes nativos. Para las otras tres páginas, después de confirmar sus IDs y contenido, usar WP-CLI desde el checkout de desarrollo:

    docker compose run --rm -T cli wp option update bakata_shipping_page_id ID_REAL
    docker compose run --rm -T cli wp option update bakata_returns_page_id ID_REAL
    docker compose run --rm -T cli wp option update bakata_contact_page_id ID_REAL

Sustituir ID_REAL por el identificador de la página correspondiente; no copiar literalmente. Si una página pasa a borrador o se protege con contraseña, desaparece automáticamente del sitio. Para ocultarla sin modificar la página, eliminar la opción correspondiente con wp option delete. No se han creado ni publicado políticas. La selección por ID está documentada, no hay pantalla de ajustes adicional en esta versión.

## Pruebas
CI comprueba la salida HTML, ausencia de enlaces sin configurar, y presencia/ausencia según estado de páginas con fixtures exclusivos del entorno local desechable. Revisar diseño real, teclado, zoom, lectores de pantalla, enlaces y contenido legal antes de producción. No equivale a una auditoría legal ni certificación de seguridad.
