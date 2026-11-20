/**
 * Ayuda contextual de formularios: solamente inspecciona etiquetas, tipos y required.
 * NUNCA consulta .value, sessionStorage, cookies ni datos capturados por el usuario.
 */
import type { Modulo } from '../config/modulos'
import { resolverAyuda, type RespuestaGuia } from './ayudaModulos'

export interface CampoVisible {
  etiqueta: string
  tipo: 'texto' | 'fecha' | 'numero' | 'seleccion' | 'archivo' | 'casilla'
  requerido: boolean
}
type ControlFormulario = HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
const tipos = (el: ControlFormulario): CampoVisible['tipo'] => {
  if (el instanceof HTMLSelectElement) return 'seleccion'
  if (el instanceof HTMLTextAreaElement) return 'texto'
  if (el.type === 'file') return 'archivo'
  if (el.type === 'checkbox' || el.type === 'radio') return 'casilla'
  if (el.type === 'date' || el.type === 'datetime-local' || el.type === 'time') return 'fecha'
  if (el.type === 'number' || el.type === 'range') return 'numero'
  return 'texto'
}
const limpiar = (valor: string): string => valor.replace(/\s+/g, ' ').replace(/[*:]+$/, '').trim().slice(0, 85)
const normalizar = (s: string) => s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()

export function camposVisiblesPantalla(raiz: ParentNode | null | undefined): CampoVisible[] {
  if (!raiz) return []
  const controles = Array.from(raiz.querySelectorAll<ControlFormulario>('input, textarea, select'))
  const encontrados = new Set<string>()
  const campos: CampoVisible[] = []
  for (const el of controles) {
    if (el.disabled || el instanceof HTMLInputElement && ['hidden', 'submit', 'button', 'reset', 'password'].includes(el.type)) continue
    if (el.closest('[hidden], [aria-hidden="true"]')) continue
    if (el instanceof HTMLElement && el.getClientRects().length === 0) continue
    // Nunca leer valores escritos ni opciones seleccionadas.
    const textoLabel = el.labels?.[0]?.textContent ?? el.getAttribute('aria-label') ??
      el.closest('label')?.textContent ?? el.getAttribute('placeholder') ?? ''
    const etiqueta = limpiar(textoLabel)
    if (!etiqueta || encontrados.has(normalizar(etiqueta))) continue
    encontrados.add(normalizar(etiqueta))
    campos.push({ etiqueta, requerido: el.required || el.getAttribute('aria-required') === 'true',
      tipo: tipos(el) })
    if (campos.length >= 24) break
  }
  return campos
}

const consejos: Array<[RegExp, string]> = [
  [/\brfc\b/, 'Introduce un RFC válido de la empresa o persona correspondiente.'],
  [/razon social|nombre fiscal/, 'Escribe la denominación que corresponda al registro.'],
  [/correo|e-mail|email/, 'Utiliza una dirección de correo electrónico válida y comprobable.'],
  [/telefono|celular/, 'Escribe el número de contacto del registro correspondiente.'],
  [/fecha|vigencia|vencimiento/, 'Selecciona la fecha correcta; comprueba el período antes de guardar.'],
  [/cantidad|existencia|unidades|piezas/, 'Introduce la cantidad real en la unidad indicada; verifica el almacén antes de registrar un movimiento.'],
  [/importe|presupuesto|monto|costo|precio/, 'Escribe el importe numérico que corresponda al registro y revisa la moneda.'],
  [/unidad de negocio|sucursal/, 'Selecciona la unidad perteneciente a la empresa cliente correcta.'],
  [/prestador/, 'Selecciona el prestador autorizado para atender a ese cliente.'],
  [/tipo de equipo|familia/, 'Selecciona el catálogo que corresponda al activo; evita crear duplicados.'],
  [/severidad|prioridad/, 'Elige la clasificación que corresponda según las reglas del servicio.'],
  [/descripcion|observaciones|comentarios|notas/, 'Describe el hecho o trabajo con suficiente detalle para que otro usuario lo comprenda.'],
  [/tecnico|responsable/, 'Selecciona una persona autorizada para esa tarea; no asignes personal sin verificar disponibilidad.'],
  [/archivo|evidencia|foto|documento/, 'Adjunta un archivo pertinente, legible y permitido por el formulario.'],
]
function explicacionCampo(c: CampoVisible): string {
  const base = consejos.find(([patron]) => patron.test(normalizar(c.etiqueta)))?.[1]
  const modo = c.tipo === 'seleccion' ? 'Selecciona una opción del listado.' :
    c.tipo === 'archivo' ? 'Adjunta el documento solicitado.' :
    c.tipo === 'fecha' ? 'Utiliza el selector de fecha.' :
    c.tipo === 'casilla' ? 'Marca la opción solo si corresponde.' :
    c.tipo === 'numero' ? 'Introduce un valor numérico válido.' : 'Completa el dato solicitado.'
  return c.etiqueta + (c.requerido ? ' (obligatorio)' : ' (opcional)') + ': ' + (base ?? modo)
}

export function responderDudaModulo(
  modulo: Modulo | null, pregunta: string, campos: CampoVisible[] = [],
): RespuestaGuia {
  const base = resolverAyuda(modulo, pregunta)
  const q = normalizar(pregunta.trim())
  if (!modulo || !q) return base

  // Primero responder al campo concreto preguntado (cuando esté en pantalla).
  const encontrados = campos.filter(c => {
    const etiqueta = normalizar(c.etiqueta)
    return etiqueta.length > 2 && (q.includes(etiqueta) || etiqueta.split(' ')
      .filter(w => w.length > 4).some(w => q.includes(w)))
  })
  if (encontrados.length && /(llen|que pongo|como|sirve|obligator|campo|seleccion|dato|valor|escrib)/.test(q)) {
    return { ...base,
      titulo: 'Qué poner en ' + encontrados[0]!.etiqueta,
      introduccion: 'Te explico el campo de esta pantalla, sin acceder a su contenido.',
      pasos: encontrados.slice(0, 5).map(explicacionCampo).concat(['Revisa que los datos sean correctos y guarda únicamente cuando estés listo.']),
    }
  }
  if (/(llen|complet|captur|formulario|campos|que pongo|paso a paso|como se llena)/.test(q)) {
    if (campos.length) {
      return { ...base,
        titulo: 'Cómo llenar ' + modulo.nombre + ' campo por campo',
        introduccion: 'Detecté las etiquetas de los campos visibles en esta pantalla; no he leído las respuestas que escribiste.',
        pasos: campos.slice(0, 16).map(explicacionCampo).concat([
          'Revisa los campos obligatorios, guarda y comprueba que aparezca el registro. Si quieres ayuda con un campo concreto, escribe su nombre.',
        ]),
        consejo: 'Estas orientaciones se basan en los campos visibles, no en la validación interna del servidor. No se enviaron datos del formulario.',
      }
    }
    return { ...base,
      titulo: 'Cómo llenar el formulario en ' + modulo.nombre,
      introduccion: 'No veo campos editables en la pantalla abierta.',
      pasos: [base.pasos[0] ?? 'Abre el módulo.', 'Pulsa Nuevo, Crear o Editar si la opción está habilitada para tu rol.',
        'Cuando aparezca el formulario, vuelve a preguntar «¿Cómo lleno estos campos?» y te explicaré los que se muestran.'],
    }
  }
  if (/(error|falla|no funciona|no me deja|no puedo|rechaz|bloquead)/.test(q)) {
    const motivo = /(guardar|registr|crear)/.test(q) ? 'guardar cambios' :
      /(rastre|gps|ubicaci)/.test(q) ? 'obtener ubicación GPS' : 'realizar la operación'
    return { ...base,
      titulo: 'Qué revisar si no puedes ' + motivo,
      introduccion: 'No tengo el registro de error de tu pantalla; revisa estas causas frecuentes.',
      pasos: ['Comprueba tu sesión, conexión a Internet y permisos del rol.',
        campos.length ? 'Revisa que los campos marcados como obligatorios estén completos y tengan el formato correcto.'
          : 'Abre el registro o formulario y verifica sus datos obligatorios.',
        /(gps|ubicaci|rastre)/.test(q) ? 'Comprueba que exista un técnico asignado, jornada abierta y permiso de GPS.'
          : 'Revisa el mensaje exacto que aparece en ACMA después de intentar la operación.',
        'Si persiste, comparte el texto del error con soporte sin enviar contraseñas ni datos privados.'],
    }
  }
  if (/(permiso|rol|quien puede|acceso|autoriz)/.test(q)) {
    return { ...base, titulo: 'Permisos para utilizar ' + modulo.nombre,
      introduccion: 'Los controles visibles y la validación del servidor dependen del rol de la cuenta.',
      pasos: ['Consulta qué opciones aparecen en tu pantalla.',
        'Si un botón no está disponible, no significa necesariamente que el módulo esté fallando.',
        'Solicita al administrador revisar tu rol; no se deben suplantar cuentas para ejecutar acciones restringidas.'],
    }
  }
  if (/(guardar|enviar|publicar|confirmar)/.test(q)) {
    return { ...base, titulo: 'Cómo confirmar los cambios en ' + modulo.nombre,
      pasos: [...base.pasos, 'Antes de pulsar Guardar o Enviar, revisa que los datos y el ámbito sean correctos.',
        'Vuelve a consultar el registro para confirmar que el servidor guardó el cambio.'],
    }
  }

  // Evitar aparentar que entendimos preguntas arbitrarias sin evidencia.
  const conocida = /(para que|sirve|como|consult|busc|crea|registr|alta|nuev|edit|modific|actualiz|rastre|gps|ubicaci|ver|encontr|localiz|captur|insert|funcion)/.test(q)
  if (!conocida) return {
    ...base,
    titulo: 'Necesito un poco más de detalle',
    introduccion: 'No encontré una respuesta específica para esa pregunta en la guía de ' + modulo.nombre + '.',
    pasos: ['Indica qué botón, campo o proceso necesitas usar.', 'Puedes escribir «cómo llenar», «cómo consultar», «no me deja guardar» o el nombre del campo.',
      'También puedes abrir el formulario y preguntarme por sus campos visibles.'],
    consejo: 'No inventaré funciones, permisos ni datos que no estén documentados en ACMA.',
  }
  return base
}
