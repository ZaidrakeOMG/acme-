# Decisiones que necesitan su visto bueno

El documento de diseño no definía estos puntos, así que ACMA tomó una decisión razonable para poder avanzar. **Todo
funciona hoy con la opción marcada.** Esta lista es para que alguien del negocio confirme o cambie cada una.

Cómo leerla: cada punto trae **la pregunta**, **lo que ACMA hace hoy** y **qué cambia si responde distinto**. No hace
falta saber nada técnico. Lo que no se cambie se queda como está.

Hay 42 preguntas, agrupadas por tema. Las de la primera sección son las que más conviene revisar: afectan al dinero
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

## Ubicación de los técnicos en la jornada

### 34. El aviso que ve el técnico la primera vez que inicia su jornada: ¿este texto es el correcto?

**Hoy:** antes de abrir su primera jornada, el técnico tiene que aceptar este aviso, y su aceptación queda guardada
con fecha:

> «Mientras tu jornada esté iniciada, ACMA registra la ubicación de tu teléfono cada 30 segundos (cada 5 minutos en
> pausa) para que el despachador sepa dónde estás, pueda apoyarte si te detienes y pueda decirle al cliente a qué
> hora llegas. No se registra nada cuando cierras la jornada, ni cuando la app está cerrada o el teléfono
> bloqueado. El recorrido se guarda 90 días y solo lo ve el personal de tu prestador: el cliente nunca ve tu
> ubicación. Consultar tu recorrido queda registrado en la bitácora de accesos.»

**Esto lo tiene que revisar el área legal y, si existe, el área de recursos humanos**: es geolocalización de
empleados, que en México exige avisar para qué se usa el dato, por cuánto tiempo se guarda y quién lo consulta.
Cambiar el texto no toca nada más del sistema.

**Si responde distinto:** se cambia el texto; si legal pide un consentimiento firmado aparte (en el contrato o en
una carta), la casilla de la app dejaría de ser suficiente y habría que registrar ese documento.

### 35. ¿Noventa días de recorrido es lo correcto?

**Hoy:** el recorrido completo (una posición cada 30 segundos de cada jornada) se guarda **90 días** y después se
borra solo, soltando el día entero. Lo que **no** se borra nunca es la hora de llegada y la hora de cierre de cada
folio, que viven en el historial del folio.

Noventa días alcanzan para aclarar un reclamo de servicio del trimestre y es la misma retención que la bitácora de
accesos a la API. Más tiempo significa guardar los movimientos de una persona durante más tiempo; menos, quedarse
sin cómo demostrar un recorrido cuando el cliente reclama un mes después.

**Si responde distinto:** se cambia un número en la tarea de limpieza. También se puede guardar menos (por ejemplo
30 días) y conservar aparte solo las llegadas y los cierres, que ya son permanentes.

### 36. ¿Confirman que el cliente nunca ve la ubicación de los técnicos?

**Hoy:** **no la ve**. Ni el Admin empresa, ni el Admin UN, ni el operador: ni en pantalla ni por la API, y la base
de datos tampoco se la muestra. La ubicación la ven el Despachador, la Mesa de control, el Admin prestador y la
Dirección del prestador; el técnico ve la suya.

**Si responde distinto:** el diseño contempla para más adelante un «ETA al operador» —decirle al cliente a qué hora
llega el técnico, sin mostrarle el mapa— que llega con el bloque de optimización de rutas. Mostrarle el mapa en
vivo al cliente sería otra decisión, y conviene que la tomen las dos partes del contrato.

### 37. ¿«En servicio» debería exigir que el técnico esté en la unidad, o basta con que su folio esté en ejecución?

**Hoy:** basta el folio. El tablero pinta **en servicio** a quien tiene un folio en ejecución, sin mirar dónde está
su marcador; **en ruta** es el resto. En la operación normal eso coincide, porque un folio solo pasa a ejecución
cuando el técnico confirma su llegada. Donde se separa es cuando el técnico **termina el trabajo y se va sin cerrar
el folio**: queda «en servicio» mientras ya va manejando a otra parte, y el despachador lo lee como que todavía
está atendiendo.

**Si responde distinto:** se le agrega al estatus la condición de estar dentro de la geocerca de la unidad del
folio (los mismos 150 m de la llegada), y quien tenga folio en ejecución pero esté lejos y moviéndose saldría
**en ruta**. Es un cambio chico y no toca la base de datos; lo que cambia es el conteo del tablero y el tiempo que
se le atribuye a cada estatus, así que conviene decidirlo antes de que esos números se empiecen a comparar entre
meses.

## Medidores y mantenimiento por uso

### 38. Una lectura rara, ¿se rechaza o se manda a revisión?

**Hoy:** va a **revisión**. Si el número que capturan es menor que el anterior, o si saltó más de tres veces lo que
el equipo usa al día, la lectura queda en una bandeja y **no mueve el medidor ni dispara mantenimientos** hasta que
el Despachador o el Admin prestador la apruebe o la rechace con razón. La única que se rechaza de entrada es la que
trae fecha futura, porque eso siempre es un error de captura.

**Por qué así:** una lectura que retrocede suele ser real —el marcador dio la vuelta o cambiaron el medidor— y eso
lo sabe la persona, no el sistema. Rechazarla de entrada obligaría a volver a capturarla.

**Si responde distinto:** se pueden rechazar automáticamente, y entonces el operador tendría que corregir en el
momento, pero se pierde el rastro de lo que se intentó capturar. El múltiplo (tres veces) se configura por tipo de
medidor y se puede subir o bajar sin tocar nada.

### 39. ¿Cada cuántos días sin lectura hay que avisar?

**Hoy:** **30 días**. Un medidor que no se estima y lleva más de un mes sin lectura avisa al Despachador y al Admin
prestador, porque mientras eso pasa los mantenimientos por uso de ese equipo están ciegos: nadie sabe si ya tocaba.

**Si responde distinto:** es un umbral configurable por cliente y por prestador, como el resto de las alertas. En
equipos de uso intenso puede convenir una semana.

### 40. El mantenimiento por un valor del medidor, ¿se repite?

**Hoy:** **no**. «Cambio de aceite a las 500 horas» es un hito: se atiende una vez y no vuelve a pedirse, por más
horas que acumule el equipo. Lo que se repite es el otro tipo, «cada 10,000 ciclos», que se cuenta desde el último
mantenimiento.

**Si responde distinto:** nada: si lo que querían era que se repitiera, el plan se configura con el tipo «cada N
unidades» y queda resuelto. Esta nota está aquí para que no se configure un hito esperando un ciclo.

### 41. Cuando el técnico no pudo leer el marcador, ¿qué valor queda como «último mantenimiento»?

**Hoy:** la **última lectura válida** del medidor. Al cerrar un preventivo, ACMA busca primero la lectura que se
registró en ese folio; si el técnico no pudo leer el marcador, usa la última que haya. Si nunca hubo lectura, no
mueve nada y el plan sigue esperando la primera.

**Si responde distinto:** se puede exigir la lectura dentro del folio para poder cerrarlo. Es más estricto y más
exacto, pero deja al técnico sin poder cerrar cuando el marcador está inaccesible o dañado.

### 42. ¿La llave de API del cliente la administra el cliente o el prestador?

**Hoy:** el **Admin empresa** del cliente (y el Superadmin). Es la llave con la que el SCADA o el ERP del cliente
manda lecturas a ACMA; solo sirve para eso, vive atada a ese cliente y se puede revocar en cualquier momento.

**Si responde distinto:** se le puede dar también al Admin prestador, que es quien suele hacer la integración
técnica. La contra es que entonces el prestador puede emitir llaves sobre los datos del cliente sin que el cliente
lo autorice.

## Criticidad de activos y riesgo (ISO 55000, F2-05)

Las cuatro primeras de esta sección son **una sola decisión repartida**: con qué números se clasifica el parque. El
Documento de Diseño fija los cuatro niveles (A, B, C, D) y las cuatro dimensiones de impacto, pero no los pesos ni
las fronteras. Los que están hoy son defendibles y están puestos para que se puedan mover sin tocar código: son
configuración por cliente. **La recomendación es revisarlos con seis a doce meses de operación real**, cuando se
pueda comparar lo que el cálculo dijo contra lo que de verdad falló.

### 43. ¿Con qué peso entra cada dimensión del impacto?

**Hoy:** seguridad 35 %, operacional 30 %, económico 25 %, imagen 10 %. Los cuatro tienen que sumar 100 %, y si no
suman, ACMA no guarda la configuración: en cuanto no suman, el índice deja de significar lo que dice.

**Si responde distinto:** se cambian en la pantalla del módulo, cada cliente los suyos. Subir seguridad empuja
hacia arriba los equipos que pueden lastimar a alguien; subir económico empuja los caros de reparar. Las
evaluaciones ya hechas no se recalculan solas: cambiar los pesos y volver a evaluar es una decisión explícita.

### 44. ¿Dónde están las fronteras entre A, B, C y D?

**Hoy:** el índice va de 4 a 100 y se corta en **A ≥ 80, B ≥ 50, C ≥ 20, D debajo de 20**. Con eso, en el parque
demo de doce equipos quedan 2 A, 2 B, 4 C y 4 D, que es una pirámide razonable: pocos críticos y una base amplia de
no críticos.

**Si responde distinto:** son rangos configurables. Bajar la frontera de A hace críticos a más equipos, y con ello
cuántos exigen plan obligatorio, respuesta en 4 horas y refacción en inventario. Conviene mirar primero cuántos
equipos caen de cada lado antes de moverla.

### 45. ¿Cuántas fallas al año hacen a un equipo «probable»?

**Hoy:** sin fallas en 12 meses es probabilidad 1; de 1 a 2 es 2; de 3 a 5 es 3; de 6 a 11 es 4; 12 o más es 5. Es
la escala con la que ACMA convierte el historial de correctivos cerrados en el número que multiplica al impacto.

**Si responde distinto:** se ajusta la escala del cliente. Esta es la que más conviene recalibrar con datos reales,
porque depende del tipo de parque: en equipos de uso intenso doce fallas al año puede ser normal y la escala
quedaría toda en 5, que es como no tener escala.

### 46. Cuando el activo no tiene historia en ACMA, ¿de dónde sale su probabilidad?

**Hoy:** del **promedio de los equipos del mismo tipo de ese cliente**; si ninguno tiene historia propia, del
promedio del mismo tipo **en toda la plataforma, como número anónimo** (nunca se dice de qué cliente ni de qué
equipo salió); y si tampoco hay, queda en 2.00. En los tres casos la evaluación se marca como **estimada** y la
ficha lo dice, para que nadie la lea como si fuera historial del equipo.

**Si responde distinto:** se puede apagar el promedio de plataforma y dejar solo el del cliente, o pedir que la
probabilidad la capture una persona cuando no hay historia. Lo primero es más conservador con el dato; lo segundo
es más exacto si quien evalúa conoce el equipo.

### 47. Las exigencias de cada nivel, ¿avisan o bloquean?

**Hoy:** **avisan**. §6.9.3 dice que un activo A tiene plan obligatorio, respuesta máxima de 4 horas, técnico
especialista y refacciones en inventario. ACMA lo aplica como alerta, y cada cliente puede volver restricción las
que quiera. La única que hoy bloquea de verdad cuando se activa es la del técnico: asignar a un activo A o B un
técnico sin la certificación queda bloqueado, y **la razón del permiso «asignar sin la habilidad» no la levanta**
(ese permiso dispensa la habilidad del tipo de falla, no la certificación que pide la criticidad). Solo el
Superadmin de la plataforma puede pasarla.

**Si responde distinto:** se activan como restricción desde la pantalla del módulo, una por una. La recomendación es
empezar avisando: un cálculo nuevo que bloquea la operación el primer día se termina apagando entero.

### 48. ¿La respuesta por criticidad cambia el SLA del contrato?

**Hoy:** **no**. El contrato puede prometer 24 horas en un equipo que por su criticidad debería atenderse en 4.
ACMA avisa cuando se consume el 80 % de las 4 horas, pero el cumplimiento y la penalización se siguen midiendo
contra el contrato. Son dos relojes distintos a propósito.

**Si responde distinto:** se puede hacer que la criticidad apriete el SLA del contrato, pero eso cambia números que
ya se le entregaron al cliente y habría que renegociarlo, no configurarlo.

### 49. ¿Cada cuánto se revisa la clasificación?

**Hoy:** **cada 12 meses**, y a los 30 días de vencida ACMA avisa. Una evaluación vieja deja de ser evidencia ante
un auditor.

**Si responde distinto:** es un número por cliente, de 1 a 60 meses. En parques que cambian mucho conviene seis.

### 50. ¿Con qué ventana se mide si una acción de mitigación sirvió?

**Hoy:** **seis meses antes contra seis meses después** de implementarla, en fallas y en MTBF, y **antes de 90 días
ACMA responde «sin datos suficientes»** en lugar de dar un veredicto: la diferencia sería ruido.

**Si responde distinto:** se puede acortar la ventana para tener respuesta antes, a costa de que el veredicto
cambie de signo con una sola falla.


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
