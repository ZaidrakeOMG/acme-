/**
 * Buscador conversacional LOCAL, limitado al conocimiento documentado de ACMA.
 * No envía preguntas ni datos al servidor. No es un modelo generativo: responde
 * con artículos curados, etiquetas de campos visibles y guías por rol.
 */
import type { Modulo } from '../config/modulos'
import { responderDudaModulo, type CampoVisible } from './ayudaCampos'
import { resolverAyuda, type RespuestaGuia } from './ayudaModulos'
import { CONOCIMIENTO_ACMA, CONOCIMIENTO_POR_ID, type ArticuloConocimiento } from './ayudaConocimientoAcma'

export interface ContextoConversacion {
  ultimoArticuloId?: string
  ultimoModuloId?: string
}
export interface RespuestaConversacion {
  respuesta: RespuestaGuia
  origen: 'conocimiento' | 'campos' | 'guia' | 'general' | 'limite' | 'sin_permiso'
  moduloId: string | null
  articuloId: string | null
  relacionadas: string[]
}
export interface ConsultaConversacion {
  pregunta: string
  moduloActual: Modulo | null
  permitidos: Modulo[]
  campos?: CampoVisible[]
  contexto?: ContextoConversacion
}

export const normalizarConsulta = (texto: string): string => texto.normalize('NFD')
  .replace(/[\u0300-\u036f]/g, '').toLowerCase()
  .replace(/[^a-z0-9ñ\s]/g, ' ').replace(/\s+/g, ' ').trim()

const OMITIR = new Set(['el','la','los','las','un','una','unos','unas','de','del','al','en','para','por',
  'con','sin','que','como','cuando','donde','porque','porq','es','y','o','si','yo','mi','mis','tu',
  'me','no','se','lo','le','son','a','este','esta','ese','eso','ahi','puedo','quiero','tengo',
  'hago','hacer','acma','ayuda','favor','porfa','bro','bot','asistente','necesito','dime'])
function palabras(texto: string): string[] {
  return normalizarConsulta(texto).split(' ').filter(w => w.length >= 3 && !OMITIR.has(w))
}
function contieneFrase(pregunta: string, frase: string): boolean {
  const q = ' ' + normalizarConsulta(pregunta) + ' '
  const k = ' ' + normalizarConsulta(frase) + ' '
  return k.trim().length >= 3 && q.includes(k)
}
function similitud(pregunta: string, articulo: ArticuloConocimiento, moduloActual: string | null,
                   contexto: ContextoConversacion | undefined): number {
  const q = normalizarConsulta(pregunta)
  if (q === normalizarConsulta(articulo.titulo)) return 80
  const tokens = new Set(palabras(q))
  let puntuacion = 0
  for (const clave of articulo.claves) {
    const k = normalizarConsulta(clave)
    if (contieneFrase(q, k)) {
      puntuacion = Math.max(puntuacion, (q === k ? 40 : 24) + Math.min(12, k.length / 4))
    } else {
      const partes = [...new Set(palabras(k))]
      const coincidentes = partes.filter(p => tokens.has(p))
      if (coincidentes.length) {
        // No basta una sola palabra genérica para elegir un artículo al azar.
        const base = coincidentes.length * 3
        puntuacion = Math.max(puntuacion, partes.length > 1 && coincidentes.length === partes.length ? base + 10 : base)
      }
    }
  }
  const titulo = palabras(articulo.titulo)
  const acertadas = titulo.filter(p => tokens.has(p)).length
  if (acertadas >= 2) puntuacion += Math.min(10, acertadas * 2)
  if (articulo.moduloId === moduloActual && puntuacion > 0) puntuacion += 7
  if (articulo.id === contexto?.ultimoArticuloId && puntuacion > 0) puntuacion += 2
  return puntuacion
}

const SEGUIMIENTO = /\b(eso|ese|esa|ahi|luego|despues|ahora que|siguiente paso|entonces|y si|tampoco|sigue igual)\b/
const PREGUNTA_FUERA = /\b(receta|cocinar|futbol|partido de futbol|horoscopo|novia|pelicula|cancion|bitcoin|clima de hoy|presidente de|poema|chiste|guerra|carro|automovil|edad de)\b/
const SALUDO = /^(hola|buenas|buenos dias|buenas tardes|que onda|hey|saludos|gracias|muchas gracias)$/
const PREGUNTA_CAMPOS = /(llen|complet|que pongo|como escribir|que dato|campo|obligatorio|formulario|que selecciono)/
const PREGUNTA_ERROR = /(error|falla|no funciona|no me deja|no puedo|se queda|no aparece|bloquead|rechaz|no carga|no guarda|no llega)/

function relacionados(articulo: ArticuloConocimiento, permitidos: Set<string>): string[] {
  return CONOCIMIENTO_ACMA.filter(x => x.id !== articulo.id &&
    x.moduloId === articulo.moduloId && (x.moduloId === 'general' || permitidos.has(x.moduloId)))
    .slice(0, 3).map(x => x.titulo)
}

function resultadoArticulo(articulo: ArticuloConocimiento, permitidos: Modulo[]): RespuestaConversacion {
  const autorizado = new Set(permitidos.map(x => x.id))
  const modulo = permitidos.find(x => x.id === articulo.moduloId)
  return {
    respuesta: {
      titulo: articulo.titulo,
      introduccion: articulo.resumen,
      pasos: articulo.pasos,
      consejo: articulo.nota ?? 'Los controles dependen de tu rol y de la configuración real de ACMA. Confirma el resultado en el servidor.',
      ...(modulo ? { ruta: modulo.ruta } : {}),
    },
    origen: 'conocimiento',
    moduloId: articulo.moduloId === 'general' ? null : articulo.moduloId,
    articuloId: articulo.id,
    relacionadas: relacionados(articulo, autorizado),
  }
}

function seguimiento(articulo: ArticuloConocimiento, pregunta: string, permitidos: Modulo[]): RespuestaConversacion {
  const base = resultadoArticulo(articulo, permitidos)
  const q = normalizarConsulta(pregunta)
  if (PREGUNTA_ERROR.test(q)) return { ...base, respuesta: {
    ...base.respuesta,
    titulo: 'Si todavía no funciona: ' + articulo.titulo,
    introduccion: 'Sigamos con el mismo proceso. No puedo ver automáticamente tu error ni tus datos.',
    pasos: ['Comprueba de nuevo el paso donde se detiene: ' + (articulo.pasos[0] ?? 'abre el módulo.'),
      'Verifica la conexión, el rol, el cliente y los campos obligatorios.',
      articulo.pasos.at(-1) ?? 'Revisa el resultado de la operación.',
      'Copia el mensaje o código de error exacto sin contraseñas. Con eso puedo indicarte la revisión siguiente.'],
    consejo: 'No repitas escrituras que podrían haberse completado sin verificar primero el registro.',
  }}
  return { ...base, respuesta: {
    ...base.respuesta, titulo: 'Continuamos: ' + articulo.titulo,
    introduccion: 'Seguimos con el tema de tu pregunta anterior.',
    pasos: articulo.pasos.slice(-4),
  }}
}

function fueraDeAcma(): RespuestaConversacion {
  return {
    respuesta: {
      titulo: 'Puedo ayudarte con ACMA',
      introduccion: 'Este asistente está dedicado únicamente al funcionamiento y soporte de ACMA.',
      pasos: ['Pregúntame por folios, técnicos, GPS, inventario, contratos, preventivos, formularios, permisos o errores.',
        'Por ejemplo: «No aparece mi folio», «¿cómo registro una entrada?» o «no llega el WhatsApp».'],
      consejo: 'No tengo acceso a otras aplicaciones, noticias ni temas externos desde este asistente.',
    },
    origen: 'limite', moduloId: null, articuloId: null,
    relacionadas: ['Capturar una nueva solicitud de mantenimiento', 'No aparece la ubicación del técnico', 'No se guardan mis cambios'],
  }
}

export function responderConversacionAcma({
  pregunta, moduloActual, permitidos, campos = [], contexto,
}: ConsultaConversacion): RespuestaConversacion {
  const q = normalizarConsulta(pregunta).slice(0, 380)
  const accesibles = new Set(permitidos.map(m => m.id))
  const moduloNombrado = permitidos.find(m => {
    const nombre = normalizarConsulta(m.nombre)
    return nombre.length >= 5 && contieneFrase(q, nombre)
  }) ?? permitidos.find(m => m.id.length > 4 && contieneFrase(q, m.id.replaceAll('_', ' ')))
  const moduloContexto = permitidos.find(m => m.id === contexto?.ultimoModuloId) ?? moduloActual
  const modulo = moduloNombrado ?? moduloActual ?? moduloContexto ?? null

  if (SALUDO.test(q)) return {
    respuesta: {
      titulo: q.includes('gracias') ? '¡Con gusto!' : '¡Hola! Soy tu Asistente ACMA',
      introduccion: 'Puedo explicarte procedimientos y ayudarte a revisar incidencias dentro de ACMA.',
      pasos: ['Puedes escribir una pregunta normal, por ejemplo «¿por qué no puedo cerrar un folio?».',
        'También puedo explicar un campo visible si abres un formulario y preguntas «¿qué pongo aquí?».',
        'Si continuamos un tema, dime «¿y si no funciona?» para revisar los pasos siguientes.'],
      consejo: 'Respondo con documentación y reglas locales; no ejecuto cambios ni soy una IA generativa externa.',
    }, origen: 'general', moduloId: modulo?.id ?? null, articuloId: null,
    relacionadas: ['Capturar una nueva solicitud de mantenimiento', 'No aparece la ubicación del técnico'],
  }

  if (PREGUNTA_FUERA.test(q)) return fueraDeAcma()

  const artPrevio = contexto?.ultimoArticuloId
    ? CONOCIMIENTO_POR_ID.get(contexto.ultimoArticuloId) : undefined
  const esContinuacion = SEGUIMIENTO.test(q) && q.split(' ').length <= 12 && !!artPrevio
  if (esContinuacion && artPrevio && (artPrevio.moduloId === 'general' || accesibles.has(artPrevio.moduloId))) {
    return seguimiento(artPrevio, q, permitidos)
  }

  // Ayuda específica de los controles visibles: no leer jamás sus valores.
  if (PREGUNTA_CAMPOS.test(q) && campos.length && moduloActual) {
    const respuesta = responderDudaModulo(moduloActual, pregunta, campos)
    if (respuesta.titulo.includes('campo') || respuesta.titulo.includes('llenar') ||
      respuesta.titulo.includes('Qué poner') || respuesta.titulo.includes('Cómo llenar')) {
      return { respuesta, origen: 'campos', articuloId: null, moduloId: moduloActual.id,
        relacionadas: ['No se guardan mis cambios', 'Qué significan los errores del servidor'] }
    }
  }

  const puntajes = CONOCIMIENTO_ACMA.map(articulo => ({
    articulo, puntuacion: similitud(q, articulo, modulo?.id ?? null, contexto),
  })).sort((a, b) => b.puntuacion - a.puntuacion)
  const mejor = puntajes[0]
  if (mejor && mejor.puntuacion >= 11) {
    if (mejor.articulo.moduloId !== 'general' && !accesibles.has(mejor.articulo.moduloId)) {
      const nombre = mejor.articulo.moduloId.replaceAll('_', ' ')
      return {
        respuesta: { titulo: 'Este proceso requiere otro rol',
          introduccion: 'Tu cuenta no tiene acceso al módulo ' + nombre + ' desde el menú de ACMA.',
          pasos: ['Consulta tus opciones disponibles en el menú.',
            'Si esta tarea te corresponde, pide al administrador revisar tus permisos.',
            'No intentes entrar con la cuenta de otra persona ni usar un enlace directo para omitir las autorizaciones.'],
          consejo: 'El asistente respeta las mismas restricciones de visibilidad de módulos que tu cuenta.'],
        origen: 'sin_permiso', moduloId: null, articuloId: null, relacionadas: [],
      }
    }
    return resultadoArticulo(mejor.articulo, permitidos)
  }

  if (modulo) {
    const respuesta = responderDudaModulo(modulo, pregunta, modulo === moduloActual ? campos : [])
    return {
      respuesta,
      origen: 'guia',
      moduloId: modulo.id, articuloId: null,
      relacionadas: CONOCIMIENTO_ACMA.filter(a => a.moduloId === modulo.id).slice(0, 3).map(a => a.titulo),
    }
  }

  if (!q) return {
    respuesta: resolverAyuda(null),
    origen: 'guia', moduloId: null, articuloId: null,
    relacionadas: ['Capturar una nueva solicitud de mantenimiento', 'Cómo usar el Asistente ACMA'],
  }

  return fueraDeAcma()
}
