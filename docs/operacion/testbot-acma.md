# ACMA TestBot — primera integración

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
