# ACMA TestBot — primera integración (solo rama de revisión)

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
