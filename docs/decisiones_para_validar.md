# Decisiones que necesitan su visto bueno

El documento de diseño no definía estos puntos, así que ACMA tomó una decisión razonable para poder avanzar. **Todo
funciona hoy con la opción marcada.** Esta lista es para que alguien del negocio confirme o cambie cada una.

Cómo leerla: cada punto trae **la pregunta**, **lo que ACMA hace hoy** y **qué cambia si responde distinto**. No hace
falta saber nada técnico. Lo que no se cambie se queda como está.

Hay 33 preguntas, agrupadas por tema. Las de la primera sección son las que más conviene revisar: afectan al dinero
y a lo que se le cobra o se le descuenta al prestador.

---

## SLA: cuándo corre el reloj y cuándo se penaliza

Aquí se decide cuánto se le puede cobrar de penalización al prestador, así que conviene que lo revisen las dos
partes.

### 1. ¿El tiempo de respuesta se cumple al asignar al técnico o cuando el técnico va en camino?

**Hoy:** se cumple **al asignar al técnico**. En cuanto la mesa de control le pone nombre al folio, el reloj de
respuesta se detiene.

**Si responde distinto:** si el compromiso es «va en camino», el tiempo medido crece (incluye lo que el técnico tarda
en salir) y habrá más incumplimientos y más penalizaciones con los mismos tiempos contratados.

### 2. ¿El reloj arranca cuando el operador captura el folio?

**Hoy:** sí, **desde la captura**. La única excepción son los folios no críticos que el cliente tiene que clasificar
primero: ahí arranca cuando el cliente autoriza, porque antes el prestador no podía hacer nada.

**Si responde distinto:** si arranca en la autorización para todos, el prestador deja de cargar con el tiempo que
tarda el cliente en revisar.

### 3. Cuando el folio queda esperando información del cliente, ¿se pausa el reloj?

**Hoy:** **sí se pausa**. El prestador no puede avanzar sin ese dato, así que ese tiempo no cuenta contra él. El
documento de diseño no lo contemplaba.

**Si responde distinto:** sin la pausa, el prestador paga el tiempo que el cliente tarda en contestar.

### 4. ¿Se penaliza solo por no resolver a tiempo, o también por no responder a tiempo?

**Hoy:** **solo por la resolución**. El tiempo de respuesta se mide y se reporta, pero no genera descuento.

**Si responde distinto:** penalizar también la respuesta duplica los casos de descuento. Habría que definir si los
dos se acumulan en el mismo folio.

### 5. Si el cliente clasifica tarde un folio, ¿ese folio cuenta como cumplido?

**Hoy:** **cuenta como cumplido y no genera penalización**, con el motivo anotado en el expediente. La demora fue del
cliente.

**Si responde distinto:** el folio entraría al cálculo normal y el prestador cargaría con una demora que no provocó.

### 6. ¿Un período de penalizaciones ya cerrado se puede recalcular?

**Hoy:** **no**. Una vez cerrado el mes, los folios que se cierren después no lo modifican. El número que se entregó
al cliente no cambia solo.

**Si responde distinto:** recalcular hace los números más exactos, pero el monto acordado de un mes podría cambiar
después de haberlo entregado.

### 7. ¿Puede haber dos contratos activos al mismo tiempo entre el mismo cliente y el mismo prestador?

**Hoy:** **no**. ACMA rechaza un segundo contrato activo cuyas fechas se traslapen, porque quedaría indefinido qué
tiempos de SLA y qué horario de servicio aplican.

**Si responde distinto:** permitir traslapes (por ejemplo, un contrato general y otro para ciertos equipos) exige
definir una regla de prioridad entre ellos.

## Dinero: costos, presupuestos e inventario

### 8. ¿Con qué método se valúa el inventario de refacciones?

**Hoy:** **costo promedio ponderado**. Cada entrada recalcula el promedio según la cantidad; las salidas no cambian
el costo. El consumo de un folio se valúa al promedio de la ubicación de donde salió.

**Si responde distinto:** los otros métodos usuales (PEPS/FIFO, costo específico) cambian el costo que se carga a
cada folio. Conviene confirmarlo con el contador, porque afecta los estados financieros.

### 9. ¿De dónde salen las horas de mano de obra de un folio?

**Hoy:** del formulario de atención si el técnico las capturó; si no, **se calculan** entre el inicio de la atención
y el cierre, con un mínimo de media hora. El expediente anota cuál de los tres caminos se usó.

**Si responde distinto:** exigir siempre la captura del técnico da números más fieles pero bloquea el cierre si se le
olvida.

### 10. Cuando hay varias tarifas de mano de obra aplicables, ¿cuál gana?

**Hoy:** **la más específica**: una tarifa para ese cliente y ese tipo de trabajo gana a una tarifa general. Si dos
tienen la misma especificidad, gana la que entró en vigor más recientemente.

**Si responde distinto:** la alternativa sería siempre la más reciente, sin importar lo específica que sea.

### 11. ¿El costo del tiempo que el equipo estuvo parado entra en el costo total del activo?

**Hoy:** **sí**. Se cuentan las horas entre la falla y el cierre por el costo/hora del equipo (o el de su tipo si el
equipo no lo tiene). Es lo que hace visible que un equipo viejo sale caro aunque sus reparaciones sean baratas.

**Si responde distinto:** sin ese costo, el total del activo solo refleja lo que se pagó en reparaciones y la
decisión de reemplazar se vuelve más difícil de justificar.

### 12. ¿Cómo se calcula el costo total de un activo (TCO)?

**Hoy:** **adquisición + preventivos + correctivos + tiempo parado − valor residual**. Las refacciones se muestran
aparte como desglose, porque ya están dentro del costo de los folios: sumarlas otra vez las contaría doble.

**Si responde distinto:** cualquier cambio en la fórmula cambia la recomendación de «reparar o reemplazar».

### 13. ¿Qué valor residual se usa?

**Hoy:** el **valor en libros** del método de depreciación configurado. Si el equipo no tiene método configurado, se
usa su costo de adquisición (es decir, no se deprecia).

**Si responde distinto:** usar un valor comercial estimado en lugar del contable da un número más realista pero
menos auditable.

### 14. En el presupuesto, ¿el trabajo ya autorizado pero no cerrado cuenta como gastado?

**Hoy:** **se muestra aparte como «comprometido»** y resta del disponible, pero no se suma a lo consumido. Así se ve
lo que ya está comprometido sin ensuciar el gasto real.

**Si responde distinto:** sumarlo al consumido infla el gasto del mes; no restarlo del disponible deja autorizar por
encima del presupuesto.

### 15. ¿Cuántas pólizas de reposición de caja chica se generan?

**Hoy:** **una por fondo y por día**. Si no hay gastos aprobados pendientes, no se genera una póliza vacía.

**Si responde distinto:** una póliza por semana o por quincena reduce el papeleo del contador pero retrasa la
reposición del fondo al técnico.

## Minuta del día y seguimiento

### 16. ¿Se genera minuta de una unidad que no tuvo actividad?

**Hoy:** **no** para las unidades sin movimiento; la minuta global del cliente sí se genera si hubo actividad en
alguna de sus unidades. Se puede forzar una minuta vacía a mano.

**Si responde distinto:** generarla siempre deja constancia diaria de que «no pasó nada», a costa de más correos.

### 17. Si nadie valida la minuta en su ventana de tiempo, ¿se envía igual?

**Hoy:** **se envía automáticamente**, marcada como «enviada sin validación», y queda registrado.

**Si responde distinto:** no enviarla evita que salga información sin revisar, pero el cliente se queda sin su
minuta por un descuido interno.

### 18. ¿Qué significa hoy que el PDF de la minuta está «firmado»?

**Hoy:** lleva un **sello digital (SHA-256)** que permite comprobar que el archivo no se alteró. **No es una firma
electrónica con valor legal** ante un tercero.

**Si responde distinto:** si se necesita validez legal (e.firma del SAT o un proveedor de firma), hay que elegir el
proveedor y presupuestarlo: es trabajo adicional.

### 19. Las respuestas a un hallazgo después del plazo, ¿cuentan?

**Hoy:** **se aceptan y cuentan en la calificación** del cliente, con su retraso registrado. Se prefiere tener la
respuesta tarde que no tenerla.

**Si responde distinto:** rechazarlas deja hallazgos sin responder para siempre.

### 20. Cuando el cliente clasifica tarde, ¿cuánto baja su calificación?

**Hoy:** un **descuento por cada hora de retraso**, con un tope configurable. Los valores actuales son un punto de
partida, no una política acordada.

**Si responde distinto:** hay que dar los números: cuánto por hora y cuál es el tope.

## Preventivos

### 21. Un mantenimiento preventivo programado para toda una unidad, ¿genera orden de trabajo?

**Hoy:** **no hasta asignarle un equipo**. Se programa y se publica en el calendario, pero la orden necesita un
equipo concreto. La tarea nocturna los reporta como omitidos.

**Si responde distinto:** generar una orden «de unidad completa» exige definir cómo se cierra y con qué evidencia.

### 22. ¿Quién puede cancelar un preventivo ya programado?

**Hoy:** el cliente (Admin empresa) lo cancela directo. Si lo pide el prestador, **necesita autorización formal** del
responsable de la unidad o del Admin empresa.

**Si responde distinto:** dejar que el prestador cancele solo agiliza, pero el cliente pierde el control de su
calendario de mantenimiento.

### 23. ¿Qué severidad tiene un preventivo?

**Hoy:** la que traiga su plan; si el plan no la define, **el nivel más bajo**. Un preventivo no tiene tipo de falla,
así que no puede usar la matriz de severidad.

**Si responde distinto:** una severidad más alta por defecto le daría tiempos de SLA más exigentes a trabajo
planeado.

### 24. ¿Con cuánta anticipación avisan las alertas?

**Hoy:** preventivo vencido en cuanto pasa su fecha y su ventana; autorización pendiente a las **24 horas**;
calendario del mes siguiente sin publicar **a partir del día 25**. Son valores elegidos por ACMA.

**Si responde distinto:** son configurables; solo hay que decir los números.

## Operación de campo y accesos

### 25. ¿Un técnico puede ver los folios de otros técnicos?

**Hoy:** **no**. Cada técnico ve solo los que tiene asignados o capturó él mismo. La restricción está también en la
base de datos, no solo en la pantalla.

**Si responde distinto:** darle visibilidad de su cuadrilla o de su zona ayuda a cubrirse entre ellos, pero expone
información de clientes que no está atendiendo.

### 26. ¿El Supervisor de operadores ve información de dinero?

**Hoy:** **no ve nada financiero**: su tablero tiene conteos y SLA en riesgo, y el sistema le niega cualquier
indicador de costos.

**Si responde distinto:** si necesita ver costos para su trabajo, hay que decidir cuáles y de qué unidades.

### 27. ¿Se pueden escribir mensajes en un folio ya cerrado?

**Hoy:** **no se admiten mensajes de texto**; sí se puede agregar evidencia en imagen. El expediente cerrado se
conserva inalterado cinco años.

**Si responde distinto:** permitir comentarios posteriores es cómodo, pero debilita la inmutabilidad del expediente,
que es justo lo que pide la certificación.

### 28. La encuesta de satisfacción: ¿48 horas de plazo y comentario obligatorio con calificación baja?

**Hoy:** **48 horas** (configurable por cliente) y, con una calificación de 6 o menos, **el comentario es
obligatorio**: una mala nota sin explicación no sirve para corregir nada.

**Si responde distinto:** más plazo sube la tasa de respuesta y retrasa el indicador; quitar el comentario
obligatorio hace la encuesta más rápida y menos útil.

---

## Capacitación del personal y manuales

### 29. Si a un técnico se le vence una certificación, ¿se le puede seguir asignando ese tipo de trabajo?

**Hoy:** **no**. Al vencer, el sistema le retira la habilidad y deja de aparecer como candidato para esos folios; el
despachador puede mandarlo igual solo por la vía de la reasignación con razón registrada, que queda en el historial.

**Si responde distinto:** si el vencimiento solo debe avisar, el técnico seguiría recibiendo esos folios y la
certificación pasaría a ser un dato informativo. Con la regla de hoy, la operación se detiene para ese técnico hasta
que se registre el curso de refresco: conviene que capacitación lleve las fechas al día.

### 30. ¿Qué puede ver el cliente del personal que lo atiende?

**Hoy:** los técnicos habilitados en sus unidades y los que atendieron un folio suyo en los **últimos 90 días**, con
sus certificaciones vigentes: nombre del curso, tipo, norma, proveedor y hasta cuándo vale. Nada más: ni teléfono, ni
calificaciones, ni las constancias en archivo.

**Si responde distinto:** se puede acortar o alargar la ventana de 90 días, mostrar también las certificaciones ya
vencidas (para que el cliente vea el historial) o quitarle del todo esta vista.

## Avisos por WhatsApp y SMS

### 31. El aviso de privacidad del teléfono: ¿este texto es el que debe revisar el área legal?

**Hoy:** cuando alguien registra su celular en ACMA ve este texto y, al marcar la casilla, queda su consentimiento
con fecha:

> «Tu número de celular se usa solo para enviarte avisos operativos de ACMA: folios, aprobaciones, minutas y alertas
> del servicio. No se usa para publicidad ni se comparte con nadie más que el proveedor de mensajería que entrega el
> mensaje (Meta para WhatsApp, Twilio para SMS). El número se guarda cifrado y en las bitácoras solo aparece
> enmascarado. Puedes darte de baja cuando quieras: escribe BAJA por WhatsApp o SMS, o quita el consentimiento en
> esta pantalla; para volver, escribe ALTA.»

**Esto lo tiene que revisar el área legal**, porque es tratamiento de datos personales de empleados y de personal
del cliente: la ley pide decir para qué se usa el dato, con quién se comparte y cómo darse de baja. Cambiar el texto
no toca nada más del sistema.

**Si responde distinto:** se cambia el texto; si legal pide un consentimiento firmado aparte, la casilla de la
pantalla dejaría de ser suficiente y habría que registrar también ese documento.

### 32. ¿Está bien el horario de silencio de 22:00 a 07:00 y el tope de 1 000 mensajes al mes?

**Hoy:** fuera de ese horario solo salen los avisos **críticos** (aprobación pendiente o bloqueada, SLA en riesgo o
incumplido, severidad crítica y trabajo especial de urgencia); los demás esperan. Al llegar al tope mensual se
bloquean los no críticos y, al 80 % del tope, se levanta una alerta al Admin prestador. Cada cliente puede tener su
propio horario y su propio tope.

**Si responde distinto:** se ajustan horario y tope por cliente en *Mensajería → Canales y consumo*, o se cambia qué
eventos cuentan como críticos. Ojo: ampliar la lista de críticos significa mensajes de madrugada.

### 33. ¿Confirman que una aprobación nunca se resuelve desde el mensaje?

**Hoy:** **no se resuelve**. El WhatsApp de una aprobación trae los botones «Aprobar» y «Rechazar», pero no ejecutan
la decisión: contestan con el enlace a la pantalla de aprobación, donde la persona entra con su usuario y su
verificación en dos pasos si su rol la exige. Igual con cualquier otra acción: el mensaje informa y lleva.

**Si responde distinto:** se podría aprobar con un botón del mensaje, pero entonces quien tenga el teléfono —o la
sesión de WhatsApp abierta en una computadora— podría autorizar gasto sin contraseña ni segundo factor. Por eso
quedó así.

## Dos cosas que no son preguntas de negocio pero hay que decidir antes de publicar

No son decisiones de producto; son de infraestructura, y sin ellas el sistema queda a medias en lo que promete.

**A. ¿Dónde se guarda la copia de los respaldos, fuera del servidor?**
ACMA respalda todos los días y verifica cada respaldo, pero **mientras la copia viva solo en el mismo servidor, un
daño en ese servidor se lleva también los respaldos**. Hay que elegir el destino (otro servidor, un almacenamiento
en otra región) y quién lo custodia.

**B. ¿Cuánto trabajo se puede permitir perder?**
Con el respaldo diario, perder el servidor significa **perder hasta un día de trabajo**. La certificación ISO 27001
pide que no se pierda más de una hora. Bajarlo a minutos no cuesta dinero en licencias, solo disco y configuración
(archivado continuo de la base), pero hay que decidirlo y activarlo. El detalle está en
[`docs/operacion/recuperacion_desastres.md`](operacion/recuperacion_desastres.md).

---

## Qué pasa si no responden nada

Nada se detiene: ACMA opera hoy con las opciones marcadas arriba. Pero tres de ellas conviene no dejarlas pasar,
porque después son más difíciles de cambiar:

- **Las cuatro primeras preguntas de SLA** definen cuánto se penaliza. Cambiarlas más adelante altera números que ya
  se entregaron al cliente.
- **El método de valuación del inventario** (pregunta 8) afecta la contabilidad: cambiarlo con movimientos ya
  registrados obliga a recalcular el histórico.
- **El destino de los respaldos** (punto A) es lo único de esta lista que, si falla, no tiene vuelta atrás.
