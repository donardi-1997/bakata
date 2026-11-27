# Bakatá Store

E-commerce y dropshipping basado en WordPress y WooCommerce. Dominio previsto: **bakata.store**.

## Desarrollo local

Requisitos: Git, Docker con Compose v2 y Bash (en Windows, WSL).

```sh
git clone https://github.com/donardi-1997/bakata.git
cd bakata
cp .env.example .env
# Editar .env: contraseñas locales y correo de administración.
bash scripts/bootstrap.sh
```

Tienda: http://localhost:8080. Administración: http://localhost:8080/wp-admin/.
Si cambia el puerto, ajustar también WP_URL en .env antes de instalar.

Comandos:

```sh
docker compose ps
docker compose run --rm cli wp plugin list
docker compose run --rm cli wp theme list
docker compose logs -f wordpress
docker compose down
```

El bootstrap es repetible: no reinstala un WordPress existente. Los datos se conservan en volúmenes; `docker compose down -v` los destruye. No ejecutar contra producción.

### QA de homepage con WebKit (opt-in)

Solo para una instancia local desechable con los fixtures de CI ya cargados y las dependencias de `qa` instaladas. Instalar WebKit de Playwright si aún no está disponible y ejecutar la suite de presentación y navegación, sin repetir la prueba de carrito:

```sh
qa/node_modules/.bin/playwright install --with-deps webkit
BAKATA_CI_FIXTURES=1 BAKATA_QA_BROWSER=webkit BAKATA_QA_LAYOUT_ONLY=1 node qa/homepage.mjs
```

Los informes quedan en `qa/reports/webkit-layout/`. Chromium y la suite completa siguen siendo los valores por defecto. Playwright WebKit no sustituye una prueba en Safari real. Esta ejecución no se añade automáticamente a CI.

## Código propio

- `wp-content/themes/bakata`: tema de bloques.
- `wp-content/plugins/bakata-core`: extensiones comerciales.
- `docs/architecture.md`: arquitectura y decisiones.
- `docs/roadmap.md`: alcance y criterios de aceptación.

Las imágenes Docker usan etiquetas de desarrollo y WooCommerce se instala desde WordPress.org; antes de staging se deberán fijar versiones/digests y comprobar compatibilidad. No se incluyen plugins de proveedores, pagos reales, productos ni credenciales. Este entorno no está endurecido para producción.

## Entorno remoto de desarrollo

Ver [infraestructura, seguridad y despliegue](docs/infrastructure.md). No usar las configuraciones de desarrollo como producción.
