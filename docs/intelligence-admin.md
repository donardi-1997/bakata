# INT-07 — Panel administrativo

Bakatá Core registra Bakatá Intelligence en wp-admin para usuarios con manage_options. Es una vista previa experimental, sin endpoints REST, conexiones a fuentes, publicación, aprobación persistente ni cambio de precios o stock.

## Ejecución local

Desde la raíz, con el servicio INT-01 construido:

```sh
docker compose -f services/intelligence/compose.yaml run --rm -T fixture python -m intelligence.admin_export > intelligence-preview.json
```

Entrar en wp-admin como administrador, abrir Bakatá Intelligence y cargar el JSON. Se muestran dos candidatos sintéticos: uno listo para revisión (77,77 puntos) y uno incompleto. La fecha de evaluación es la de la fixture, no la fecha actual. No se presenta como dato vigente. Buscar por título, fuente o ID y filtrar por estado; expandir la evidencia de cada criterio. Eliminar la vista previa al finalizar.

## Contrato y seguridad

- Exportación versionada desde el motor Python, sin duplicar la rúbrica en cálculos de rentabilidad PHP. PHP valida esquema, límites, coherencia de componentes y cobertura. Los puntos se transmiten en centésimas de punto; tolerancia de cuatro centésimas para la suma de componentes redondeados individualmente.
- Solo modo fixture, identificadores de fuente fixture, dominios .invalid, sin query ni credenciales. El validador no certifica autenticidad o naturaleza sintética de texto arbitrario: no cargar información real o personal.
- 256 KiB y 100 filas máximo. Carga mediante POST autenticado y nonce dedicado; nunca se registra archivo en biblioteca multimedia. Caché temporal por usuario y sitio mediante transient de 15 minutos, revalidada al leer. WordPress puede eliminarla antes y la limpieza física en DB no es inmediata. La eliminación explícita está disponible.
- Capability manage_options tanto en menú como callbacks; sin endpoints nopriv. No se concede permiso a gestores de tienda. Texto de entrada escapado; URL mostrada como texto, sin petición de red.
- Estados y ranking son informativos: review-ready significa listo para revisar, no autorizado para vender. La UI es nativa de WordPress, sin dependencias JS nuevas.

## Pruebas y siguientes fases

CI añade prueba Python de exportación, prueba de contrato Python/PHP con snapshot real de fixture, y prueba de navegador en WordPress desechable: acceso invitado/suscriptor, rechazo de POST sin nonce, carga, filtros, evidencia y eliminación. No se ha validado aún en producción ni diseñado aprobación durable, autenticación granular de revisores, histórico de precios en UI o API de lectura. No hay edición de scoring en este panel. INT-08 deberá implementar programación y persistencia con controles de ejecución; INT-09 integrará importación controlada a borrador; INT-10 verificará seguridad, recursos y despliegue.
