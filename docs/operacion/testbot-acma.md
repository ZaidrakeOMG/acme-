# ACMA TestBot — primera integración

## Recorrido consecutivo después de Formularios (versión 3)

Una vez que el antiguo TestBot indica **Formularios dinámicos: 7/7**, el modo **Probar sistema** ya no termina ni obliga a regresar a ChatGPT. Muestra el siguiente módulo y un botón **Siguiente · probar [módulo]**. La primera parada es **Biblioteca técnica**. Después siguen Operaciones en tiempo real, Folios, App de campo, Preventivos y los demás módulos de navegación. Se cubren los 31 módulos restantes en la cola; los tres anteriores (Catálogos, Formularios y Mis formularios) se respetan como avance previo.

En cada pulsación el bot:
- Invoca la API del módulo con solicitudes **GET** existentes. Verifica formato de respuesta y registra los resultados concretos.
- Abre el módulo correspondiente en la navegación.
- Guarda el índice y los resultados por usuario en el dispositivo; al reabrir no regresa a Formularios.
- Registra errores reales sin detener el resto de la secuencia; al terminar se puede volver al primer error.
- Para App de campo declara *requiere otro rol* porque el Superadmin no equivale a Técnico u Operador.

**Límite fundamental:** estos nuevos pasos son comprobaciones de lectura/disponibilidad; **NO** se presentan como pruebas funcionales completas de creación, edición, cierre, firma, notificaciones externas o permisos. No se hacen escrituras en los otros módulos. Las siete pruebas funcionales completas siguen siendo exclusivamente las de Formularios. Esta distinción aparece en el panel para impedir que una consulta exitosa sea tratada como una certificación total.

Los módulos restantes se incorporarán con flujos de prueba DEMO específicos (incluidas altas ficticias) cuando se puedan proteger y aislar correctamente.


## Actualización: modo autónomo DEMO

El primer TestBot fallaba al pulsar Siguiente si se había recargado el constructor y faltaban los cuatro campos. Además el backend rechaza el formulario con cliente específico si el superadmin no indica prestador_id.

Esta versión resuelve ambos problemas mediante el flujo seguro frontend/src/services/testbotFlujoDemo.ts:

1. Identifica por razón social exacta el cliente EMPRESA DEMO ACMA SA DE CV y el prestador MANTENIMIENTO DEMO ACMA SA DE CV.
2. Reutiliza por ID o nombre+cliente+prestador el formulario «Inspección de mantenimiento DEMO»; si no existe lo crea con exactamente cuatro campos.
3. Comprueba que los obligatorios rechacen vacíos y acepten datos ficticios.
4. Publica únicamente la versión DEMO pendiente; no crea una nueva si ya está publicada.
5. Comprueba que figure en Mis formularios del rol Superadmin.
6. Guarda y envía una respuesta ficticia al mismo cliente; conserva IDs y evita repetir la respuesta.
7. Relee los valores y comprueba el estado enviado e inmutable.

**Controles:** Superadmin exclusivamente; no toca otros clientes ni prestadores; no borra formularios con estructura inesperada, no toca folios/contratos/equipos reales; bitácora de errores comprensible. El botón Siguiente realiza un paso real; Ejecutar todas las pruebas DEMO encadena las siete tareas.

El avance v2 se conserva por usuario en el navegador. Las pantallas del constructor se recargan con el formulario guardado cuando se ejecuta solo el primer paso. Después de la prueba completa abre Mis formularios.


## Alcance

Asistente flotante reutilizable en React Web y en WebView Android, con imagen original optimizada, botón para mostrar/ocultar y sugerencias contextuales. Solo el rol Superadmin ve el modo **Probar sistema**. La ruta actual de pruebas es **Formularios dinámicos**.

## Estado de la revisión manual ya realizada

- Catálogos maestros: importación de familia desde Excel, altas de familias y tipos, equipo DEMO, técnico DEMO, tipo de falla y matriz de severidad con nivel Alta: revisados.
- Severidades: cinco niveles visibles (no se modificaron).
- **Pendiente actual:** constructor del formulario de inspección DEMO con cuatro campos existentes.
- Mis formularios: inicialmente vacío; debe verificarse después de publicar.

## Botón Siguiente (prueba de Formularios)

1. **Preparar:** valida exactamente cuatro campos en orden si_no, texto_amplio, texto_amplio, texto. Ajusta sus etiquetas, roles Superadmin y Técnico, y limita el alcance al tenant EMPRESA DEMO ACMA. No añade campos.
2. **Guardar:** usa la función del constructor. Si ya hay un ID, actualiza el formulario; si es nuevo, crea uno y conserva su ID.
3. **Vista previa:** abre el renderizador real.
4. **Publicar:** abre el modal existente. El usuario confirma manualmente; el bot avanza si el servidor confirma.
5. **Verificar lista:** consulta /formularios/mis-formularios y comprueba el ID publicado para el rol.
6. **Enviar DEMO:** exige nombre y tenant DEMO y esquema exacto, valida datos ficticios, guarda la ID de respuesta y evita reenviar si ya se envió.
7. **Verificar respuesta:** consulta por ID y confirma estado=enviado.

El progreso se guarda por usuario en localStorage en el dispositivo (no se sincroniza entre dispositivos). El bot no modifica usuarios, contratos, tarifas ni folios reales. No inicia migraciones ni despliegues.

## Pruebas y publicación

Esta rama requiere revisión y validación automática TypeScript/Vitest en el PR antes de fusionarse. La creación de rama o PR no cambia Railway. No mezclar con main hasta revisar los controles de alcance DEMO y confirmar que funcionan todos los pasos.

Limitación: otros módulos aún no tienen ejecutores automáticos; el asistente ofrece ayuda contextual. El motor de Formularios es la primera prueba real.

## Recursos

- Mascota: frontend/public/testbot-acma.webp
- Interfaz y motor: frontend/src/components/TestBotAcma.tsx
- Comunicación con el constructor: frontend/src/services/testbotAcma.ts
- Acción protegida: frontend/src/pages/formularios/Constructor.tsx


## Versión 4 — recorrido con escrituras DEMO (opt-in)

La cuenta Superadmin puede marcar **Autorizar altas y cambios de prueba** en ACMA TestBot y pulsar
**Ejecutar todo el recorrido DEMO y guardar resultados**. No inicia escrituras sin esa autorización
explícita. El avance se guarda por usuario en el navegador después de cada módulo; ante fallas se
continúa con los siguientes módulos y se conserva el error para reintento.

Implementación: frontend/src/services/testbotEscriturasDemo.ts y
frontend/src/services/testbotSecuencia.ts.

- Pruebas reales de **alta, edición y relectura**: unidades de negocio y grupo, inventario con entrada,
  presupuestos, planes preventivos, contratos con los cinco SLA, y criticidad ISO de un activo ficticio. Se reutilizan registros identificados con claves exactas TESTBOT DEMO.
- Pruebas reales de **alta y relectura**: folio correctivo, medidor del equipo ficticio y trabajo especial. Las transiciones
  operativas, firmas y permisos de otro rol **no se dan por aprobados**.
- **Seguimiento**: configura el período presupuestal mensual solo si falta en el cliente DEMO.
- Los módulos restantes conservan la prueba GET original. No son declarados CRUD completos.
- Los reportes distinguen Alta y edición DEMO OK, Alta DEMO OK, Consulta OK, Pendiente y Error.

Antes de escribir, el ejecutor exige coincidencia exacta y única de EMPRESA DEMO ACMA SA DE CV
y MANTENIMIENTO DEMO ACMA SA DE CV activos, y que el cliente tenga **un solo prestador vinculado
y activo**, precisamente el de DEMO. Si no se satisface el ámbito, aborta las escrituras. Nunca
debe elegirse arbitrariamente el primer cliente o prestador para escrituras.
Solo edita entidades con claves/nombres TESTBOT DEMO dentro de ese ámbito.
No genera usuarios, credenciales, pagos, envíos a proveedores, WhatsApp/SMS, firmas,
cierre de folio, órdenes de compra ERP ni elimina registros.

**Importante**: El botón de recorrido hace escrituras reales en el servidor y su base de datos
(Supabase en producción si la API de Railway está configurada así). Debe usarse solo con
el cliente/prestador de demostración. GitHub Actions valida el código y las
simulaciones del repositorio; para confirmar inserciones reales hay que ejecutar el TestBot
con sesión Superadmin en el ambiente DEMO y revisar los IDs devueltos.


## Diagnóstico TXT y prueba de rastreo de folio DEMO

El botón **Descargar diagnóstico de pruebas (.txt)** exporta, desde el navegador,
la fecha/hora de cada módulo, estado, peticiones HTTP fallidas y códigos del servidor,
IDs de registros ficticios, errores y pendientes. Se genera localmente y no incluye
cookies de sesión, tokens, contraseñas ni cuerpos de las peticiones. Si un reporte
contiene identificadores de la operación, se debe revisar antes de compartirlo.

El botón **Crear / recuperar folio DEMO y rastrearlo** funciona con la sesión **Superadmin
actual**, sin suplantar cuentas. Crea/reutiliza la UN, una familia y un tipo **globales
marcados TESTBOT DEMO**, un tipo de falla del **prestador DEMO**, un equipo ficticio
del **cliente DEMO** y un único folio DEMO. Los catálogos globales de demostración
son visibles para otros clientes por diseño de ACMA, pero no modifican los existentes.

El seguimiento consulta el **estado real del folio cada 12 segundos**. Si el folio
tiene un técnico asignado, busca el dato folio.tecnico_id en tablero.tecnicos[].usuario_id;
el ID de la ruta GPS es tablero.tecnicos[].tecnico_id (son dos campos distintos).
No fabrica coordenadas. El técnico debe entrar con **su propia cuenta Técnico**,
iniciar jornada y permitir ubicación desde un dispositivo con GPS e Internet.
Mientras no lo haga, el estado del folio puede seguirse pero la ubicación seguirá
sin datos. En **Operaciones en tiempo real**, el botón Rastrear de cada folio toma
el técnico correcto y actualiza su recorrido cada 12 segundos. Los tableros se
refrescan cada 20 segundos.

Se requiere ejecutar las pruebas contra la instancia DEMO real para confirmar
permisos, recepción de GPS, asignación, persistencia y actualizaciones. Ni
GitHub Actions ni un GET correcto prueban por sí mismos esos escenarios.


## Corrección 2026-11-18: medidores sin tipos disponibles

Si el catálogo de medidores está vacío, el TestBot Superadmin ahora crea
exclusivamente un tipo **global** con el nombre exacto
**TESTBOT DEMO - Horómetro de laboratorio ficticio**, marcado en su descripción
como equipo no real. Lo reutiliza por nombre y comprueba su persistencia.
No toma un medidor ajeno ni modifica tipos existentes. El tipo global será
visible en la plataforma por el alcance normal del catálogo.

El TestBot crea o reutiliza un medidor de número de serie TESTBOT-DEMO-MED
en el equipo TESTBOT-DEMO-EQ, modifica su límite a 99999 h y vuelve a
consultar para verificar que el cambio se guardó. El resultado se marca
**Alta y edición DEMO OK** solo después de la relectura.

Registrar lecturas, revisión de anomalías y permisos de Técnico y Operador
requieren sus propias pruebas de campo; **no** quedan aprobados por esta
corrección. El diagnóstico TXT seguirá marcando los otros módulos que
únicamente validan consultas GET.

Para comprobar el arreglo en ACMA: refrescar la web después del despliegue,
usar TestBot con Superadmin y habilitar escrituras DEMO. Elegir
**Repetir recorrido DEMO** (o reintentar el error de Medidores), descargar
el TXT y compartirlo para confirmar la inserción real en la base conectada.
Para el folio GPS, pulsar **Crear / recuperar folio DEMO y rastrearlo**;
el último TXT muestra que todavía no se hizo ese paso.


## Prueba GPS personal DEMO con Superadmin — 2026-11-19

En TestBot → Probar sistema → Crear/recuperar folio DEMO, tras obtener F-000001
u otro folio etiquetado DEMO, se habilita **Iniciar mi GPS personal DEMO (pedir permiso)**.

El usuario Superadmin puede conceder permiso explícito de geolocalización de
su propio navegador. Se usa navigator.geolocation.watchPosition y un
BroadcastChannel del mismo origen web para mostrar el marcador rojo
TESTBOT DEMO y la trayectoria en **Operaciones en tiempo real**, incluso en
otra pestaña de ACMA del mismo navegador. El botón **Detener mi GPS personal
DEMO** suspende watchPosition y borra el marcador de la prueba.

**Privacidad y alcance:** esta prueba NO cambia roles, NO crea sesiones Técnico,
NO envía posiciones al endpoint /api/operacion/posiciones, NO almacena ubicaciones
en Supabase ni en localStorage y NO crea una jornada real. Por tanto verifica
la captura GPS del navegador, actualizaciones de mapa y comunicación local
entre pestañas, pero NO certifica el recorrido del Técnico en el servidor. La
prueba formal debe completarse posteriormente con una cuenta Técnico real,
una jornada iniciada y un folio asignado mediante el flujo autorizado.

**Mapa:** el backend antes enviaba Referrer-Policy: no-referrer también para
la SPA; OpenStreetMap rechazaba teselas con 403 sin Referer. Ahora la web
solo envía el ORIGEN al proveedor de mapas usando
strict-origin-when-cross-origin. Las rutas API y WebSocket conservan
no-referrer; no se envían tokens ni rutas privadas. Se mantiene la
atribución oficial de OpenStreetMap.

**Tablero de folios:** los folios abiertos en estado capturado,
en_revision, pendiente_informacion y otros estados no finales aparecen
aunque se hayan creado en días anteriores. Antes el tablero omitía
F-000001 cuando pasaba al día siguiente. Esto no implica que estén
asignados ni que haya GPS: se muestran como pendientes y la ubicación
requiere jornada Técnica real o la capa local de prueba personal.


## Indicadores visuales por módulo — 2026-11-19

La navegación del Superadmin y la lista del TestBot muestran iconos SVG de la
**última prueba**, acompañados de color, leyenda accesible y detalles al pasar
el cursor. Los iconos también están en el menú lateral de móvil.

- **Verde (círculo con paloma):** alta, edición y relectura DEMO comprobadas.
- **Turquesa (círculo con +):** alta DEMO comprobada, otros pasos pueden faltar.
- **Azul (círculo con i):** solo consultas GET comprobadas; NO indica CRUD completo.
- **Ámbar (reloj):** prueba pendiente o requisito de otro rol.
- **Rojo (X):** error detectado en la última prueba.
- **Gris (círculo):** apartado sin prueba específica guardada.

El constructor de Formularios muestra verde solo si su recorrido DEMO
completó los 7 pasos; Mis formularios y Catálogos maestros pueden seguir
grises si no tienen un registro de prueba independiente. **No significa que
estén dañados**, solo que no hay certificación para ese módulo.

Los indicadores se basan en el último recorrido guardado localmente por
usuario (acma.testbot.secuencia.v1.<usuario_id>), no en una comprobación de
salud en tiempo real. Al guardar un nuevo resultado o terminar Formularios
se actualizan inmediatamente en la misma pestaña y entre pestañas mediante
el evento storage; el TestBot no requiere repetir escrituras para pintar
el estado. No se muestra el resultado de pruebas de Superadmin a otros roles.

El TXT del 19-nov-2026 contiene 31/31 evaluados, 0 errores, 12 pruebas con
alguna escritura DEMO verificada, 16 consultas sin CRUD y 3 pendientes.
No demuestra que todos los apartados estén funcionalmente completos; el
folio F-000001 todavía figura sin Técnico asignado ni jornada GPS oficial.
