import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ejecutarPasoDemo, INICIAL_DEMO, PASOS_DEMO, NOMBRE_FORMULARIO_DEMO } from '../src/services/testbotFlujoDemo'
import type { Formulario, Respuesta } from '../src/types/formularios'

const m = vi.hoisted(() => ({
  api: vi.fn(),
  crearRespuesta: vi.fn(),
  guardarRespuesta: vi.fn(),
  enviarRespuesta: vi.fn(),
  obtenerFormulario: vi.fn(),
  obtenerRespuesta: vi.fn(),
}))
vi.mock('../src/services/api', () => ({ api: m.api }))
vi.mock('../src/services/formularios/respuestas', () => ({
  crearRespuesta: m.crearRespuesta, guardarRespuesta: m.guardarRespuesta,
  enviarRespuesta: m.enviarRespuesta, obtenerFormulario: m.obtenerFormulario,
  obtenerRespuesta: m.obtenerRespuesta,
}))

function maqueta() {
  const cliente = { id: 't-demo', razon_social: 'EMPRESA DEMO ACMA SA DE CV', estado: 'activo' }
  const prestador = { id: 'p-demo', razon_social: 'MANTENIMIENTO DEMO ACMA SA DE CV', estado: 'activo' }
  let formulario: Formulario | null = null
  let respuesta: Respuesta | null = null
  const pruebas: string[] = []

  m.api.mockImplementation(async (ruta: string, opts?: { metodo?: string; cuerpo?: Record<string, unknown> }) => {
    pruebas.push((opts?.metodo ?? 'GET') + ' ' + ruta)
    if (ruta === '/tenants') return [cliente]
    if (ruta === '/prestadores') return [prestador]
    if (ruta === '/formularios' && !opts?.metodo) return formulario ? [formulario] : []
    if (ruta === '/formularios' && opts?.metodo === 'POST') {
      expect(opts.cuerpo?.prestador_id).toBe(prestador.id)
      expect(opts.cuerpo?.tenant_id).toBe(cliente.id)
      formulario = {
        id: 'form-1', tenant_id: cliente.id, prestador_id: prestador.id,
        nombre: String(opts.cuerpo?.nombre), descripcion: String(opts.cuerpo?.descripcion),
        tipo: 'libre', rol_destino: opts.cuerpo?.rol_destino as string[],
        esquema_json: opts.cuerpo?.esquema as Formulario['esquema_json'],
        estado: 'borrador', numero_version_publicada: null, version_actual: 1,
        version_publicada_id: null, puede_editar: true, es_plantilla_base: false,
      } as Formulario
      return formulario
    }
    if (ruta === '/formularios/form-1' && opts?.metodo === 'PUT') {
      formulario = { ...formulario!, esquema_json: opts.cuerpo?.esquema as Formulario['esquema_json'] }
      return formulario
    }
    if (ruta === '/formularios/form-1/publicar' && opts?.metodo === 'POST') {
      formulario = { ...formulario!, estado: 'publicado', numero_version_publicada: 1, version_publicada_id: 'v1' }
      return formulario
    }
    if (ruta === '/formularios/mis-formularios') return formulario ? [{ formulario }] : []
    if (ruta === '/formularios/respuestas') return respuesta ? [respuesta] : []
    throw new Error('API no simulada: ' + ruta)
  })
  m.obtenerFormulario.mockImplementation(async () => formulario)
  m.obtenerRespuesta.mockImplementation(async () => respuesta)
  m.crearRespuesta.mockImplementation(async () => {
    respuesta = { id: 'r-1', formulario_id: 'form-1', tenant_id: cliente.id,
      estado: 'en_progreso', inmutable: false, respuestas_json: {} } as Respuesta
    return respuesta
  })
  m.guardarRespuesta.mockImplementation(async (_id: string, valores: Record<string, unknown>) => {
    respuesta = { ...respuesta!, respuestas_json: valores }
    return respuesta
  })
  m.enviarRespuesta.mockImplementation(async () => {
    respuesta = { ...respuesta!, estado: 'enviado', inmutable: true }
    return respuesta
  })
  return { cliente, prestador, pruebas, actual: () => formulario, respuesta: () => respuesta,
    cambiarFormulario: (x: Formulario) => { formulario = x } }
}

describe('ACMA TestBot — pruebas DEMO sin duplicados', () => {
  beforeEach(() => vi.clearAllMocks())

  it('desde el constructor vacío crea 4 campos, valida, publica, envía y comprueba una sola respuesta', async () => {
    const serv = maqueta()
    let p = { ...INICIAL_DEMO }
    for (const paso of PASOS_DEMO) {
      const r = await ejecutarPasoDemo(p, (parcial) => { p = parcial })
      p = r.progreso
      expect(r.mensaje).not.toMatch(/error/i)
      expect(p.paso).toBe(PASOS_DEMO.indexOf(paso) + 1)
    }
    expect(p.formularioId).toBe('form-1')
    expect(p.respuestaId).toBe('r-1')
    expect(serv.actual()?.nombre).toBe(NOMBRE_FORMULARIO_DEMO)
    expect(serv.actual()?.esquema_json.secciones[0]?.campos).toHaveLength(4)
    expect(serv.respuesta()?.estado).toBe('enviado')
    expect(serv.respuesta()?.inmutable).toBe(true)
    expect(serv.pruebas.filter((x) => x === 'POST /formularios')).toHaveLength(1)
    expect(m.crearRespuesta).toHaveBeenCalledTimes(1)
    expect(m.enviarRespuesta).toHaveBeenCalledTimes(1)
    // Una segunda ejecución del primer paso debe recuperar el mismo formulario.
    const otra = await ejecutarPasoDemo({ ...INICIAL_DEMO }, () => undefined)
    expect(otra.progreso.formularioId).toBe('form-1')
    expect(serv.pruebas.filter((x) => x === 'POST /formularios')).toHaveLength(1)
  })

  it('detiene la prueba si no encuentra al cliente DEMO en vez de cambiar registros reales', async () => {
    maqueta()
    m.api.mockImplementation(async (ruta: string) => ruta === '/tenants' ? [] : ruta === '/prestadores' ? [
      { id: 'p-demo', razon_social: 'MANTENIMIENTO DEMO ACMA SA DE CV', estado: 'activo' },
    ] : [])
    await expect(ejecutarPasoDemo({ ...INICIAL_DEMO }, () => undefined)).rejects.toThrow(/un cliente activo/i)
    expect(m.api).not.toHaveBeenCalledWith('/formularios', expect.objectContaining({ metodo: 'POST' }))
  })

  it('rechaza modificar un formulario con un esquema distinto en lugar de destruirlo', async () => {
    const serv = maqueta()
    serv.cambiarFormulario({
      id: 'form-1', nombre: NOMBRE_FORMULARIO_DEMO, prestador_id: serv.prestador.id, tenant_id: serv.cliente.id,
      estado: 'borrador', tipo: 'libre', es_plantilla_base: false,
      rol_destino: ['superadmin'], esquema_json: { version_contrato: 1, secciones: [
        { clave: 'seccion_1', titulo: 'Sección 1', campos: [{
          clave: 'otro_campo', etiqueta: 'No modificar', tipo: 'texto',
          obligatorio: false, config: {}, condiciones: [],
        }] },
      ] },
    } as Formulario)
    await expect(ejecutarPasoDemo({ ...INICIAL_DEMO }, () => undefined)).rejects.toThrow(/campos diferentes/)
    expect(serv.pruebas).not.toContain('PUT /formularios/form-1')
  })
})
