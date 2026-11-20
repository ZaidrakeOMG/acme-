/**
 * Ayuda contextual de ACMA, sin modificaciones a datos.
 * Contiene instrucciones de uso por apartado; no es una IA generativa ni una prueba
 * de que el flujo ya haya sido verificado con todos los roles en producción.
 */
import { MODULOS, type Modulo } from '../config/modulos'

export interface GuiaModulo {
  id: string
  objetivo: string
  pasos: string[]
  consejo?: string
  acciones?: Record<string, string[]>
}
export interface RespuestaGuia {
  titulo: string
  introduccion: string
  pasos: string[]
  consejo: string
  ruta?: string
}

const GUIAS: Record<string, Omit<GuiaModulo, 'id'>> = {
  usuarios: {
    objetivo: 'Administrar accesos y permisos de las personas que usan ACMA.',
    pasos: ['Abre Usuarios desde Administración.', 'Busca a la persona por nombre o datos disponibles.', 'Revisa su rol y su estado antes de realizar un cambio.', 'Para altas o modificaciones, utiliza las acciones habilitadas para tu rol y confirma el resultado en la lista.'],
    consejo: 'Solo asigna los permisos necesarios; nunca compartas contraseñas.',
  },
  tenants: {
    objetivo: 'Consultar empresas cliente y sus relaciones con prestadores.',
    pasos: ['En Administración, abre Clientes (tenants).', 'Busca o selecciona la empresa cliente.', 'Consulta sus datos y vínculos con prestadores.', 'Si tienes permisos de administración, realiza los cambios correspondientes y vuelve a verificar el registro.'],
  },
  prestadores: {
    objetivo: 'Gestionar la información del prestador de mantenimiento.',
    pasos: ['Abre Prestadores.', 'Selecciona el prestador que necesitas revisar.', 'Verifica sus datos fiscales, identificación y configuración visual.', 'Guarda los cambios solo si tienes permiso y comprueba cómo quedaron.'],
  },
  unidades: {
    objetivo: 'Ubicar y organizar sucursales o unidades de negocio.',
    pasos: ['Abre Unidades de negocio.', 'Selecciona primero la empresa cliente cuando se solicite.', 'Busca la unidad por nombre o código.', 'Revisa su ubicación y los grupos a los que pertenece.', 'Al crear o editar, verifica que quede asociada al cliente correcto.'],
  },
  contratos: {
    objetivo: 'Consultar vigencias, modalidades de servicio y tiempos SLA.',
    pasos: ['Abre Contratos y SLAs.', 'Selecciona el cliente y el prestador involucrados.', 'Consulta las fechas de vigencia y la modalidad contratada.', 'Revisa los objetivos de respuesta y resolución por severidad.', 'Si editas el contrato, verifica que no se traslape con otro contrato activo.'],
  },
  alertas: {
    objetivo: 'Revisar umbrales, canales y reglas de notificación.',
    pasos: ['En Administración, abre Configuración de alertas.', 'Selecciona el ámbito que corresponda a tu rol.', 'Revisa las alertas existentes, los umbrales y los canales.', 'Modifica únicamente las reglas autorizadas y verifica el resultado en la pantalla.'],
  },
  capacitacion: {
    objetivo: 'Consultar cursos, certificaciones y fechas de vencimiento.',
    pasos: ['Abre Capacitación y certificaciones.', 'Consulta el catálogo de cursos disponibles.', 'Si tu cuenta pertenece a un prestador, revisa las certificaciones y vencimientos de su personal.', 'Actualiza evidencias o fechas solo con el rol autorizado.'],
    consejo: 'Algunos vencimientos requieren una cuenta Admin prestador; Superadmin no sustituye ese rol.',
  },
  auditoria: {
    objetivo: 'Revisar la bitácora de eventos y acciones registradas.',
    pasos: ['Abre Auditoría desde Administración.', 'Utiliza filtros o fechas cuando estén disponibles.', 'Localiza el evento que necesitas investigar.', 'Revisa usuario, operación y momento del evento.', 'Conserva la referencia del evento si necesitas reportar un incidente.'],
  },
  catalogos: {
    objetivo: 'Administrar catálogos de equipos, fallas y datos maestros.',
    pasos: ['Abre Catálogos maestros.', 'Escoge la sección del catálogo que necesitas revisar.', 'Busca el equipo, familia o tipo de falla existente antes de crear otro.', 'Comprueba a qué empresa o prestador pertenece el registro.', 'Guarda los cambios autorizados y verifica que no se crearan duplicados.'],
  },
  formularios: {
    objetivo: 'Diseñar y publicar formularios dinámicos para captura de información.',
    pasos: ['Abre Formularios dinámicos y localiza el constructor.', 'Crea un formulario o abre uno que ya exista.', 'Agrega campos y configura cuáles son obligatorios.', 'Guarda un borrador y comprueba las validaciones.', 'Publica la versión cuando esté lista y revisa que aparezca en Mis formularios.'],
    consejo: 'Una versión publicada puede tener restricciones de edición; comprueba el efecto antes de publicar.',
  },
  mis_formularios: {
    objetivo: 'Llenar, guardar y enviar formularios a los que tengas acceso.',
    pasos: ['Abre Mis formularios.', 'Selecciona el formulario que te corresponda.', 'Completa los campos obligatorios y adjunta evidencias cuando las solicite.', 'Guarda el avance si necesitas continuarlo después.', 'Revisa las respuestas y envía cuando estés seguro.'],
  },
  biblioteca: {
    objetivo: 'Consultar manuales, fichas y contenido técnico de mantenimiento.',
    pasos: ['Abre Biblioteca técnica.', 'Busca el tipo de equipo o documento que necesitas.', 'Selecciona la ficha, el manual o el contenido de servicio.', 'Verifica que corresponda al equipo y a la versión correctos.', 'Utiliza esa referencia para atender el trabajo.'],
  },
  operaciones: {
    objetivo: 'Ver jornadas, técnicos, folios, alertas y posiciones GPS disponibles.',
    pasos: ['Abre Operaciones en tiempo real.', 'Comprueba el estado de conexión y los técnicos en jornada.', 'Consulta Folios abiertos y del día.', 'Pulsa Rastrear sobre el folio que deseas seguir.', 'Si hay técnico asignado con jornada y GPS activos, el mapa centra un marcador grande en su última ubicación.'],
    consejo: 'Si un folio no tiene técnico o ubicación GPS real, ACMA lo indica y no inventa coordenadas.',
    acciones: {
      rastrear: ['Abre Operaciones en tiempo real.', 'Busca el número de folio en la tabla.', 'Pulsa Rastrear y revisa el mensaje de disponibilidad GPS.', 'Con técnico en jornada, aparecerá un indicador azul con el número del folio; puedes volver a centrarlo.', 'Con GPS personal TESTBOT DEMO, el indicador rojo corresponde solo a una prueba de tu navegador.'],
    },
  },
  folios: {
    objetivo: 'Capturar, consultar y dar seguimiento a solicitudes de mantenimiento.',
    pasos: ['Abre Folios.', 'Consulta los folios existentes o selecciona la captura de uno nuevo.', 'Elige la empresa, unidad y equipo que correspondan, si tu rol puede hacerlo.', 'Indica el tipo de falla, prioridad y descripción del servicio.', 'Guarda y confirma el número de folio.', 'Abre su detalle para consultar el estado y las acciones permitidas.'],
    consejo: 'Crear un folio no asigna automáticamente un técnico ni genera una ubicación GPS.',
    acciones: {
      rastrear: ['Localiza el folio en Folios y comprueba que tenga número y estado.', 'Abre Operaciones en tiempo real.', 'Localízalo en Folios abiertos y del día y pulsa Rastrear.', 'Si existe un técnico asignado y comparte GPS durante su jornada, se mostrará la ubicación; en caso contrario se informará qué falta.'],
    },
  },
  app_campo: {
    objetivo: 'Atender servicios desde las cuentas de Técnico u Operador.',
    pasos: ['Entra con la cuenta que tenga el rol Técnico u Operador.', 'Abre App de campo y chat.', 'Revisa los folios o tareas que te hayan asignado.', 'Consulta instrucciones y registra el trabajo o evidencias solicitadas.', 'Antes de cerrar o enviar, verifica el estado de la conexión y la sincronización.'],
    consejo: 'Superadmin no sustituye el flujo operativo de Técnico u Operador.',
  },
  preventivos: {
    objetivo: 'Planificar mantenimientos periódicos y revisar su calendario.',
    pasos: ['Abre Preventivos y planes.', 'Selecciona Calendario o Planes según lo que necesites.', 'Consulta el mes, prestador y ámbito correspondientes.', 'Para un plan nuevo, define el tipo de equipo, tareas, periodicidad y materiales.', 'Guarda el plan y comprueba que aparezca en el calendario cuando corresponda.'],
  },
  reasignaciones: {
    objetivo: 'Revisar el historial de cambios de técnico responsable.',
    pasos: ['Abre Reasignaciones.', 'Consulta las reasignaciones registradas.', 'Localiza el folio y los técnicos involucrados.', 'Revisa el motivo y los datos disponibles de cada cambio.'],
  },
  notificaciones: {
    objetivo: 'Ver avisos, acciones pendientes y preferencias de notificación.',
    pasos: ['Abre Notificaciones.', 'Revisa la bandeja de avisos.', 'Abre el aviso que necesite atención.', 'Consulta el folio o apartado relacionado.', 'Ajusta tus preferencias de notificación cuando tu rol lo permita.'],
  },
  minuta: {
    objetivo: 'Consultar las minutas de jornada y dar seguimiento a acuerdos.',
    pasos: ['Abre Minuta del día.', 'Selecciona la jornada o minuta que necesitas.', 'Lee los hechos, pendientes y responsables.', 'Si tienes permiso, registra o responde acuerdos y verifica su actualización.'],
  },
  seguimiento: {
    objetivo: 'Consultar períodos presupuestales y seguimiento de actividad.',
    pasos: ['Abre Seguimiento.', 'Selecciona la empresa cliente.', 'Comprueba el período presupuestal configurado.', 'Revisa los registros e indicadores disponibles del período.', 'Si no hay configuración, solicita establecerla con el rol correspondiente.'],
  },
  clasificacion: {
    objetivo: 'Revisar folios no críticos y pendientes de clasificación.',
    pasos: ['Abre Folios no críticos.', 'Consulta los folios pendientes.', 'Selecciona un folio para revisar su información.', 'Si tu rol puede clasificarlo, aplica la categoría adecuada y verifica el resultado.'],
  },
  mensajeria: {
    objetivo: 'Revisar la configuración de mensajería, canales WhatsApp/SMS y su consumo.',
    pasos: ['Abre Mensajería (WhatsApp y SMS).', 'Selecciona el prestador para el que tengas permisos.', 'Comprueba si el proveedor de mensajes y los canales están configurados.', 'Consulta el consumo y la actividad registrada.', 'Antes de habilitar envíos reales, valida destinatarios, consentimiento y costos de la integración.'],
    consejo: 'Una configuración que aparece como pendiente no indica un fallo del servidor. No envíes mensajes de prueba a números reales sin autorización.',
  },
  trabajos_especiales: {
    objetivo: 'Registrar y consultar trabajos fuera del mantenimiento ordinario.',
    pasos: ['Abre Trabajos especiales.', 'Busca primero si el trabajo ya está registrado.', 'Selecciona el cliente y la unidad correctos.', 'Describe alcance y presupuesto del trabajo, si corresponde.', 'Guarda y consulta su estado de autorización antes de iniciar la ejecución.'],
  },
  oc_activos: {
    objetivo: 'Consultar órdenes de compra relacionadas con activos.',
    pasos: ['Abre OC de activos.', 'Revisa órdenes pendientes y su información.', 'Selecciona la orden que necesitas validar.', 'Confirma estado y autorizaciones antes de continuar el proceso de compra.'],
  },
  inventario: {
    objetivo: 'Controlar artículos, almacenes, existencias y movimientos.',
    pasos: ['Abre Inventario.', 'Selecciona artículos, ubicaciones o movimientos según tu tarea.', 'Busca por código y comprueba que el artículo pertenezca al prestador correcto.', 'Para una entrada o salida, selecciona artículo y ubicación, registra la cantidad y confirma.', 'Consulta las existencias después del movimiento.'],
    consejo: 'No registres una entrada ficticia en un almacén real.',
  },
  caja_chica: {
    objetivo: 'Consultar y controlar los fondos y movimientos de caja chica.',
    pasos: ['Abre Caja chica.', 'Localiza el fondo que necesitas revisar.', 'Consulta saldo y movimientos disponibles.', 'Registra un movimiento solo con comprobante y permisos adecuados.', 'Vuelve a consultar el resultado.'],
  },
  presupuestos: {
    objetivo: 'Registrar y controlar presupuestos por período y unidad.',
    pasos: ['Abre Presupuestos.', 'Elige cliente, unidad y período.', 'Consulta el presupuesto existente antes de crear otro.', 'Registra nombre, importe y fechas cuando tengas permisos.', 'Guarda y verifica que el monto y período sean correctos.'],
  },
  activos: {
    objetivo: 'Consultar equipos y activos de cada unidad.',
    pasos: ['Abre Equipos y activos.', 'Selecciona la empresa y unidad.', 'Busca el activo por código o nombre.', 'Revisa familia, tipo de equipo y datos asociados.', 'Si tu rol permite crear o editar, guarda y confirma que pertenezca a la unidad correcta.'],
  },
  medidores: {
    objetivo: 'Consultar medidores de equipos y sus lecturas.',
    pasos: ['Abre Medidores de activos.', 'Localiza el equipo y su tipo de medidor.', 'Consulta lecturas y posibles anomalías.', 'Registra una lectura solo desde una cuenta autorizada y comprueba su validación.', 'Revisa si hay lecturas pendientes de aprobación.'],
  },
  rutas: {
    objetivo: 'Consultar las rutas asignadas, paradas y tiempos de servicio.',
    pasos: ['Abre Rutas del día.', 'Selecciona el prestador y la jornada.', 'Revisa los mercados, las paradas y los tiempos previstos.', 'Comprueba los cambios o propuestas de ruta antes de aceptarlos.', 'Consulta Operaciones para verificar la ubicación del técnico cuando tenga jornada y GPS.'],
  },
  iso55000: {
    objetivo: 'Consultar criticidad y datos de gestión de activos.',
    pasos: ['Abre Gestión de activos ISO 55000.', 'Selecciona la empresa cliente.', 'Consulta la guía de criticidad.', 'Revisa el resumen por activo y la criticidad registrada.', 'Si modificas una clasificación, documenta el motivo y verifica el cambio.'],
  },
  erp: {
    objetivo: 'Revisar las exportaciones y los eventos de integración ERP.',
    pasos: ['Abre Integración ERP.', 'Consulta las exportaciones existentes.', 'Revisa los eventos de intercambio y sus resultados.', 'Si hay errores, identifica el evento y su mensaje antes de reintentar.', 'No generes nuevas exportaciones sin confirmar el destino de los datos.'],
  },
  sla: {
    objetivo: 'Consultar plazos de respuesta y resolución de los folios.',
    pasos: ['Abre Contador de SLA.', 'Consulta los contratos y sus niveles de severidad.', 'Localiza el folio que necesites evaluar.', 'Revisa el tiempo restante, el nivel de riesgo y posibles incumplimientos.', 'Si un plazo no aparece, verifica vigencia del contrato y datos del folio.'],
  },
  bi: {
    objetivo: 'Consultar los indicadores y reportes de mantenimiento.',
    pasos: ['Abre Inteligencia de negocio.', 'Selecciona los filtros y períodos disponibles.', 'Revisa indicadores, comparativos y tendencias.', 'Comprueba el alcance de los datos antes de compartir un reporte.'],
  },
}

export function guiaPorId(id: string): GuiaModulo {
  const definicion = GUIAS[id]
  const modulo = MODULOS.find(m => m.id === id)
  if (!definicion) {
    return {
      id,
      objetivo: modulo?.descripcion ?? 'Consulta la información disponible en ACMA.',
      pasos: ['Abre el apartado.', 'Revisa las opciones disponibles para tu rol.', 'Selecciona el registro o acción que necesitas.', 'Confirma los datos antes de guardar algún cambio.'],
    }
  }
  return { ...definicion, id }
}

export function identificarModuloPorRuta(pathname: string, permitidos: Modulo[]): Modulo | null {
  if (pathname === '/' || pathname === '/seguridad') return null
  const coincidencias = permitidos.filter(m => {
    const ruta = m.ruta.split('?')[0]
    return pathname === ruta || pathname.startsWith(ruta + '/')
  })
  coincidencias.sort((a, b) => b.ruta.length - a.ruta.length)
  return coincidencias[0] ?? null
}

function normalizar(texto: string): string {
  return texto.normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .toLowerCase().replace(/\s+/g, ' ').trim()
}

export function resolverAyuda(modulo: Modulo | null, pregunta = ''): RespuestaGuia {
  if (!modulo) return {
    titulo: 'Cómo comenzar en ACMA',
    introduccion: 'Te explico cada apartado según la pantalla donde estés. Selecciona un módulo del menú o del buscador de ayuda.',
    pasos: ['Abre el menú de ACMA.', 'Elige un módulo al que tengas acceso.', 'Abre el asistente y pulsa Explicar este módulo.', 'Para un proceso específico, escribe qué quieres hacer.'],
    consejo: 'Los pasos son una guía de uso; no ejecutan cambios ni reemplazan permisos.',
  }
  const guia = guiaPorId(modulo.id)
  const q = normalizar(pregunta)
  let pasos = guia.pasos
  let titulo = 'Cómo utilizar ' + modulo.nombre
  if (/(rastre|ubicaci[oó]n|gps)/.test(q) && guia.acciones?.rastrear) {
    pasos = guia.acciones.rastrear
    titulo = 'Cómo rastrear un folio en ACMA'
  } else if (/(busc|consult|ver|encontr|localiz)/.test(q)) {
    titulo = 'Cómo consultar en ' + modulo.nombre
    pasos = [guia.pasos[0]!, ...guia.pasos.slice(1).filter(p =>
      /(consult|revis|busc|seleccion|comprueb|localiz|lee |abre |elige |filtr)/i.test(p))]
    if (pasos.length < 2) pasos = guia.pasos
  } else if (/(crear|registr|agregar|alta|nuevo|captur|insert)/.test(q)) {
    titulo = 'Cómo registrar información en ' + modulo.nombre
  } else if (/(edit|cambi|modific|actualiz)/.test(q)) {
    titulo = 'Cómo revisar cambios en ' + modulo.nombre
  } else if (/(que es|para que sirve|funcion)/.test(q)) {
    titulo = 'Para qué sirve ' + modulo.nombre
  }
  return {
    titulo,
    introduccion: guia.objetivo,
    pasos,
    consejo: guia.consejo ?? 'Las acciones disponibles dependen de tu rol. Si no aparece una opción, comprueba tus permisos con el administrador.',
    ruta: modulo.ruta,
  }
}

export const CUBIERTOS_POR_GUIA = Object.keys(GUIAS)
