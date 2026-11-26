# Bakatá Design System v1.0

Base de la homepage aprobada, Raíz contemporánea. **El catálogo y las promesas comerciales no se inventan.** Los patrones de marca originales están en brand/; usar el isotipo romboidal oficial, no la B ilustrativa de los mockups.

## Capas y contrato
- `assets/brand/tokens.css`: colores y familias aprobados, sin alterar originales.
- `assets/css/design-system.json`: tokens semánticos, tipografía, espacios, radios y layout.
- `assets/css/design-system.css`: componentes con prefijo bk-, cargados en frontend y editor mediante enqueue_block_assets. Las variables de color coinciden con el JSON; theme.json conserva aliases anteriores y añade tamaños de fuente/espaciado nativos. No se introduce JS ni dependencia remota.
- `assets/icons/sprite.svg`: iconos de línea de 24 unidades, usar con clase bk-icon y use href a la ruta del sprite + #id. Marcar iconos decorativos aria-hidden=true; controles icon-only necesitan nombre accesible.
- `docs/design-system-preview.html`: laboratorio estático de componentes, abrir localmente desde un clon (si el navegador bloquea SVG externo bajo file://, servir la raíz con python3 -m http.server 8000 y abrir /docs/design-system-preview.html). No publicar como página comercial.

## Componentes y uso
| Componente | Clases / comportamiento |
|---|---|
| Contenedor y sección | bk-container, bk-section, bk-stack, bk-cluster |
| Grid | bk-grid: 2 columnas, 1 bajo 22rem, 3 desde 48rem, 4 desde 64rem |
| Titulares | bk-heading con bk-h1/h2/h3; mantener jerarquía semántica |
| Logo | bk-logo; utilizar SVG horizontal de assets/brand, alt Bakatá |
| Botón | bk-button, bk-button--secondary; button type=button para acciones, a href válido para navegación |
| Icono | bk-icon, bk-icon-button; área interactiva 44px, aria-label cuando no hay texto |
| Enlace | bk-link, subrayado visible |
| Tarjeta | bk-card, bk-card__media, bk-card__body, bk-price; conectar a datos WooCommerce reales |
| Categoría | bk-category; enlace a categoría existente, no crear categorías ficticias |
| Formulario | bk-form-field, bk-label, bk-field, bk-help, bk-error; label asociado por for/id, aria-describedby y aria-invalid cuando aplica |
| Aviso | bk-notice, variantes --success y --error; role=status para mensajes dinámicos no urgentes, role=alert si urgente |
| Etiqueta | bk-badge; nunca comunicar estado solo mediante color |
| Superficie inversa | bk-inverse; usar logo negativo, titulares y enlaces de alto contraste |

## Accesibilidad y uso visual
Texto normal >=4.5:1, controles y foco >=3:1 respecto al fondo como objetivos. Verde profundo con marfil es CTA principal; terracota original decorativo, variante oscura #8C4427 solo para texto de acento. No usar valoraciones, precios o envíos ficticios. Estados hover, focus-visible, disabled y error; respetar reduced-motion. Diseñar navegación por teclado y probar lectores de pantalla, zoom 200%, anchos 320/375/768/1024/1440. Los checks de contraste estáticos no certifican WCAG.

Plus Jakarta Sans e Inter se sirven localmente tras ejecutar scripts/install-fonts.sh; las licencias OFL están versionadas. Se conserva fallback del sistema. No hay solicitudes a CDN de fuentes desde el navegador. Las medidas de escala, colores auxiliares, radios e iconos son propuestas técnicas derivadas del diseño aprobado.

## Próximos pasos
Construir hero, categorías y catálogo con APIs/bloques nativos; validar responsive y accesibilidad en navegador real. La cabecera y el favicon de fallback se documentan en docs/store-header.md.
