/**
 * Flujo real de prueba DEMO. Las operaciones usan las mismas rutas que el producto,
 * no simulan resultados: cada transición queda confirmada por el servidor.
 * Ningún registro ajeno al cliente/prestador DEMO puede modificarse desde este motor.
 */
import { api } from './api'
import { crearRespuesta, enviarRespuesta, guardarRespuesta, obtenerFormulario, obtenerRespuesta } from './formularios/respuestas'
import { validar } from './formularios/validacion'
import type { Prestador, Tenant } from '../types/api'
import { CONFIG_DEFECTO, camposDe, type Campo, type EsquemaFormulario, type Formulario, type Respuesta, type TipoCampo } from '../types/formularios'

export interface ProgresoDemo {
  paso: number
  formularioId: string | null
  respuestaId: string | null
}
export const PASOS_DEMO = [
  'Recuperar o construir los cuatro campos y guardar formulario DEMO',
  'Probar campos obligatorios con datos vacíos y ficticios',
  'Publicar la versión DEMO',
  'Comprobar que aparezca en Mis formularios',
  'Capturar y guardar una respuesta ficticia',
  'Enviar la respuesta de prueba',
  'Confirmar persistencia, envío e inmutabilidad',
] as const

export const INICIAL_DEMO: ProgresoDemo = { paso: 0, formularioId: null, respuestaId: null }
export const NOMBRE_FORMULARIO_DEMO = 'Inspección de mantenimiento DEMO'
const CLIENTE = 'EMPRESA DEMO ACMA SA DE CV'
const PRESTADOR = 'MANTENIMIENTO DEMO ACMA SA DE CV'
const DESCRIPCION = 'Inspección ficticia para probar ACMA TestBot; no corresponde a una intervención real.'
const MARCA = 'TESTBOT DEMO'

const limpio = (texto: string) => texto.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase().replace(/\s+/g, ' ').trim()
const igual = (a: string, b: string) => limpio(a) === limpio(b)
function exigir(condicion: unknown, mensaje: string): asserts condicion {
  if (!condicion) throw new Error(mensaje)
}
const tipoEsperado: TipoCampo[] = ['si_no', 'texto_amplio', 'texto_amplio', 'texto']
const etiquetas = ['¿El equipo funciona correctamente?', 'Descripción de la falla', 'Observaciones del mantenimiento', 'Nombre del equipo']
const claves = ['equipo_funciona', 'descripcion_falla', 'observaciones_mantenimiento', 'nombre_equipo']

function crearEsquema(): EsquemaFormulario {
  return {
    version_contrato: 1,
    secciones: [{
      clave: 'seccion_1',
      titulo: 'Inspección de equipo DEMO',
      campos: tipoEsperado.map((tipo, i): Campo => ({
        clave: claves[i]!,
        tipo,
        etiqueta: etiquetas[i]!,
        obligatorio: i === 0 || i === 3,
        config: structuredClone(CONFIG_DEFECTO[tipo]),
        condiciones: [],
      })),
    }],
  }
}

function revisarCampos(esquema: EsquemaFormulario) {
  exigir(esquema.secciones.length === 1, 'El formulario existente tiene secciones adicionales; no las alteraré.')
  const campos = camposDe(esquema)
  exigir(campos.length === 0 || (campos.length === 4 && campos.every((c, i) => c.tipo === tipoEsperado[i])),
    'El formulario existente tiene campos diferentes. No se borró ni sobrescribió nada.')
  return campos
}

function esquemaConfigurado(esquema: EsquemaFormulario): EsquemaFormulario {
  const existentes = revisarCampos(esquema)
  if (!existentes.length) return crearEsquema()
  return {
    ...esquema,
    secciones: esquema.secciones.map((s) => ({
      ...s,
      titulo: s.titulo === 'Sección 1' ? 'Inspección de equipo DEMO' : s.titulo,
      campos: s.campos.map((campo, i) => ({
        ...campo, etiqueta: etiquetas[i]!, obligatorio: i === 0 || i === 3,
      })),
    })),
  }
}

function valoresFicticios(formulario: Formulario): Record<string, unknown> {
  const campos = revisarCampos(formulario.esquema_json)
  exigir(campos.length === 4, 'El formulario no tiene los cuatro campos de prueba.')
  return {
    [campos[0]!.clave]: false,
    [campos[1]!.clave]: MARCA + ': el minisplit no enfría durante la inspección.',
    [campos[2]!.clave]: MARCA + ': mantenimiento ficticio. Sin orden real ni intervención en sitio.',
    [campos[3]!.clave]: 'Aire acondicionado tipo minisplit DEMO',
  }
}

function comprobarFormulario(f: Formulario, tenant: Tenant, prestador: Prestador) {
  exigir(f.tenant_id === tenant.id && f.prestador_id === prestador.id &&
    igual(f.nombre, NOMBRE_FORMULARIO_DEMO) && !f.es_plantilla_base && f.estado !== 'archivado',
    'Seguridad: el formulario recuperado no pertenece exactamente al cliente y prestador DEMO.')
}

async function obtenerContexto() {
  const [clientes, prestadores] = await Promise.all([
    api<Tenant[]>('/tenants'),
    api<Prestador[]>('/prestadores'),
  ])
  const coincidentesCliente = clientes.filter((x) => igual(x.razon_social, CLIENTE) && x.estado === 'activo')
  const coincidentesPrestador = prestadores.filter((x) => igual(x.razon_social, PRESTADOR) && x.estado === 'activo')
  exigir(coincidentesCliente.length === 1, 'Debe existir exactamente un cliente activo EMPRESA DEMO ACMA.')
  exigir(coincidentesPrestador.length === 1, 'Debe existir exactamente un prestador activo MANTENIMIENTO DEMO ACMA.')
  return { tenant: coincidentesCliente[0]!, prestador: coincidentesPrestador[0]! }
}

async function recuperarFormulario(progreso: ProgresoDemo, tenant: Tenant, prestador: Prestador) {
  if (progreso.formularioId) {
    const guardado = await obtenerFormulario(progreso.formularioId)
    comprobarFormulario(guardado, tenant, prestador)
    return guardado
  }
  const lista = await api<Formulario[]>('/formularios', { params: { plantillas: 'false' } })
  const propios = lista.filter((f) => igual(f.nombre, NOMBRE_FORMULARIO_DEMO) &&
    f.tenant_id === tenant.id && f.prestador_id === prestador.id && f.estado !== 'archivado')
  exigir(propios.length <= 1, 'Encontré varios formularios DEMO iguales. Debes revisar los duplicados antes de continuar.')
  return propios[0] ? obtenerFormulario(propios[0].id) : null
}

function confirmarValores(esperados: Record<string, unknown>, respuesta: Respuesta) {
  for (const [k, valor] of Object.entries(esperados)) {
    exigir(respuesta.respuestas_json[k] === valor, 'El valor ' + k + ' no se conservó en la base de datos.')
  }
}

async function formularioVerificado(progreso: ProgresoDemo) {
  exigir(progreso.formularioId, 'Falta ID del formulario. Primero hay que guardarlo.')
  const ctx = await obtenerContexto()
  const f = await obtenerFormulario(progreso.formularioId)
  comprobarFormulario(f, ctx.tenant, ctx.prestador)
  return { ...ctx, f }
}

/** Un solo paso; recibe el progreso persistido por el usuario y devuelve un nuevo checkpoint. */
export async function ejecutarPasoDemo(
  progreso: ProgresoDemo,
  guardarCheckpoint: (p: ProgresoDemo) => void,
): Promise<{ progreso: ProgresoDemo; mensaje: string }> {
  const paso = progreso.paso
  exigir(paso >= 0 && paso < PASOS_DEMO.length, 'Las pruebas de Formularios ya finalizaron.')

  if (paso === 0) {
    const { tenant, prestador } = await obtenerContexto()
    let f = await recuperarFormulario(progreso, tenant, prestador)
    const esquema = esquemaConfigurado(f?.esquema_json ?? crearEsquema())
    const roles = ['superadmin', 'tecnico'] as const
    let mensaje = ''
    if (!f) {
      // El backend exige prestador_id explícito al Superadmin cuando hay tenant_id.
      f = await api<Formulario>('/formularios', {
        metodo: 'POST',
        cuerpo: { nombre: NOMBRE_FORMULARIO_DEMO, descripcion: DESCRIPCION, tipo: 'libre',
          rol_destino: roles, tenant_id: tenant.id, prestador_id: prestador.id,
          es_plantilla_base: false, esquema },
      })
      guardarCheckpoint({ ...progreso, formularioId: f.id })
      mensaje = 'Creé un único formulario DEMO con cuatro campos.'
    } else {
      comprobarFormulario(f, tenant, prestador)
      const actualizar = JSON.stringify(esquema) !== JSON.stringify(f.esquema_json) ||
        !f.rol_destino.includes('superadmin') || !f.rol_destino.includes('tecnico')
      if (actualizar) {
        f = await api<Formulario>('/formularios/' + f.id, {
          metodo: 'PUT',
          cuerpo: { esquema, rol_destino: Array.from(new Set([...f.rol_destino, ...roles])),
            nombre: NOMBRE_FORMULARIO_DEMO, descripcion: f.descripcion || DESCRIPCION,
            tenant_id: tenant.id, tipo: 'libre' },
        })
      }
      mensaje = actualizar ? 'Recuperé y completé el formulario DEMO existente.' : 'Reutilicé el formulario DEMO; no lo dupliqué.'
    }
    const verificado = await obtenerFormulario(f.id)
    comprobarFormulario(verificado, tenant, prestador)
    exigir(camposDe(verificado.esquema_json).length === 4, 'El servidor no devolvió los cuatro campos esperados.')
    return { progreso: { ...progreso, formularioId: f.id, paso: 1 }, mensaje }
  }

  if (paso === 1) {
    const { f } = await formularioVerificado(progreso)
    const campos = revisarCampos(f.esquema_json)
    exigir(campos.length === 4 && campos[0]!.obligatorio && campos[3]!.obligatorio,
      'No se guardaron las validaciones obligatorias.')
    const faltantes = validar(f.esquema_json, {}, {}, true)
    exigir(faltantes.errores.some((e) => e.campo === campos[0]!.clave) &&
      faltantes.errores.some((e) => e.campo === campos[3]!.clave),
      'La validación no rechazó los campos obligatorios vacíos.')
    const valores = valoresFicticios(f)
    const correctos = validar(f.esquema_json, valores, {}, true)
    exigir(correctos.errores.length === 0, 'Datos ficticios rechazados: ' +
      correctos.errores.map((e) => e.mensaje).join('; '))
    return { progreso: { ...progreso, paso: 2 }, mensaje: 'Validación correcta: rechazó vacíos y aceptó datos ficticios.' }
  }

  if (paso === 2) {
    const { f } = await formularioVerificado(progreso)
    const yaPublicada = f.estado === 'publicado' && f.numero_version_publicada === f.version_actual
    if (!yaPublicada) {
      await api<Formulario>('/formularios/' + f.id + '/publicar', {
        metodo: 'POST', cuerpo: { notas_version: MARCA + ': prueba automática autorizada' },
      })
    }
    const publicado = await obtenerFormulario(f.id)
    exigir(publicado.estado === 'publicado' && publicado.numero_version_publicada === publicado.version_actual,
      'No se confirmó la publicación del formulario.')
    return { progreso: { ...progreso, paso: 3 }, mensaje: yaPublicada
      ? 'La versión DEMO ya estaba publicada; no se republicó.' : 'Formulario DEMO publicado y verificado.' }
  }

  if (paso === 3) {
    const { f } = await formularioVerificado(progreso)
    const lista = await api<Array<{ formulario: Formulario }>>('/formularios/mis-formularios')
    exigir(lista.some((m) => m.formulario.id === f.id && m.formulario.estado === 'publicado'),
      'El formulario publicado no aparece en Mis formularios.')
    return { progreso: { ...progreso, paso: 4 }, mensaje: 'Confirmé que aparece en Mis formularios para Superadmin.' }
  }

  if (paso === 4) {
    const { f, tenant } = await formularioVerificado(progreso)
    exigir(f.estado === 'publicado' && f.version_publicada_id,
      'La respuesta ficticia solo se puede crear con formulario publicado.')
    const valores = valoresFicticios(f)
    const revision = validar(f.esquema_json, valores, {}, true)
    exigir(revision.errores.length === 0, 'Los datos ficticios no pasan la validación.')
    let r: Respuesta | null = progreso.respuestaId ? await obtenerRespuesta(progreso.respuestaId) : null
    if (!r) {
      const anteriores = await api<Respuesta[]>('/formularios/respuestas', {
        params: { formulario_id: f.id, mias: 'true', limite: 100 },
      })
      const testBot = anteriores.filter((item) => item.tenant_id === tenant.id &&
        String(Object.values(item.respuestas_json ?? {}).join(' ')).includes(MARCA))
      exigir(testBot.length <= 1, 'Encontré varias respuestas previas del TestBot; no crearé otra automáticamente.')
      r = testBot[0] ?? null
    }
    if (!r) {
      r = await crearRespuesta(f.id, 'independiente', { tenant_id: tenant.id })
      // Evita perder el ID si falla el guardado o se cierra la aplicación.
      guardarCheckpoint({ ...progreso, respuestaId: r.id })
    }
    exigir(r.formulario_id === f.id && r.tenant_id === tenant.id, 'La respuesta no pertenece al formulario y cliente DEMO.')
    if (r.estado === 'en_progreso') {
      r = await guardarRespuesta(r.id, valores)
      const leido = await obtenerRespuesta(r.id)
      confirmarValores(valores, leido)
    } else {
      confirmarValores(valores, r)
    }
    return { progreso: { ...progreso, respuestaId: r.id, paso: 5 }, mensaje: 'Guardé y volví a consultar la captura ficticia.' }
  }

  if (paso === 5) {
    const { f, tenant } = await formularioVerificado(progreso)
    exigir(progreso.respuestaId, 'No existe una respuesta ficticia guardada.')
    let r = await obtenerRespuesta(progreso.respuestaId)
    exigir(r.formulario_id === f.id && r.tenant_id === tenant.id, 'La respuesta guardada no corresponde al cliente DEMO.')
    confirmarValores(valoresFicticios(f), r)
    if (r.estado !== 'enviado') r = await enviarRespuesta(r.id)
    exigir(r.estado === 'enviado', 'El servidor no confirmó el envío.')
    return { progreso: { ...progreso, paso: 6 }, mensaje: 'Envío de respuesta ficticia confirmado.' }
  }

  const { f, tenant } = await formularioVerificado(progreso)
  exigir(progreso.respuestaId, 'Falta el identificador de respuesta para verificar.')
  const r = await obtenerRespuesta(progreso.respuestaId)
  exigir(r.formulario_id === f.id && r.tenant_id === tenant.id, 'La respuesta pertenece a otro cliente.')
  exigir(r.estado === 'enviado' && r.inmutable, 'La respuesta no quedó enviada e inmutable.')
  confirmarValores(valoresFicticios(f), r)
  return { progreso: { ...progreso, paso: 7 }, mensaje: 'Prueba aprobada: persistencia, envío e inmutabilidad verificados.' }
}
