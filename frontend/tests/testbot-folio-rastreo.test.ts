import { beforeEach, describe, expect, it, vi } from 'vitest'

const { fakeApi } = vi.hoisted(() => ({ fakeApi: vi.fn() }))
vi.mock('../src/services/api', () => ({ api: fakeApi }))

import { consultarSeguimientoFolioDemo, crearYSeguirFolioDemo, ejecutarEscrituraDemo } from '../src/services/testbotEscriturasDemo'
import { reporteTestBotTXT } from '../src/services/testbotReporte'
import { INICIAL_RECORRIDO } from '../src/services/testbotSecuencia'

const tenant = 'id-cliente-demo'
const prestador = 'id-prestador-demo'
const unidad = {
  id: 'un-demo', tenant_id: tenant, codigo: 'TESTBOT-DEMO-UN',
  nombre: 'TESTBOT DEMO - Unidad de pruebas', direccion: 'Ubicación ficticia - validada por TestBot',
}

describe('TestBot folio y rastreo: cliente DEMO aislado', () => {
  let familias: Record<string, unknown>[]
  let tipos: Record<string, unknown>[]
  let fallas: Record<string, unknown>[]
  let equipos: Record<string, unknown>[]
  let folios: Record<string, unknown>[]
  let tiposMedidor: Record<string, unknown>[]
  let medidores: Record<string, unknown>[]

  beforeEach(() => {
    fakeApi.mockReset()
    familias = []
    tipos = []
    fallas = []
    equipos = []
    folios = []
    tiposMedidor = []
    medidores = []
    fakeApi.mockImplementation((ruta: string, opciones?: { metodo?: string; cuerpo?: Record<string, unknown> }) => {
      const m = opciones?.metodo ?? 'GET'
      const b = opciones?.cuerpo ?? {}
      if (ruta === '/tenants') return Promise.resolve([
        { id: tenant, razon_social: 'EMPRESA DEMO ACMA SA DE CV', estado: 'activo' },
      ])
      if (ruta === '/prestadores') return Promise.resolve([
        { id: prestador, razon_social: 'MANTENIMIENTO DEMO ACMA SA DE CV', estado: 'activo' },
      ])
      if (ruta === '/tenants/' + tenant + '/prestadores') return Promise.resolve([
        { id: 'v-demo', prestador_id: prestador, estado: 'activo' },
      ])
      if (ruta === '/unidades-negocio') return Promise.resolve([unidad])
      if (ruta === '/unidades-negocio/' + unidad.id) return Promise.resolve(unidad)
      if (ruta === '/catalogos/familias-equipo') {
        if (m === 'POST') {
          const f = { ...b, id: 'fam-demo', tenant_id: null, es_global: true }
          familias.push(f)
          return Promise.resolve(f)
        }
        return Promise.resolve(familias)
      }
      if (ruta === '/catalogos/tipos-equipo') {
        if (m === 'POST') {
          const t = { ...b, id: 'tipo-demo', tenant_id: null, es_global: true }
          tipos.push(t)
          return Promise.resolve(t)
        }
        return Promise.resolve(tipos)
      }
      if (ruta === '/catalogos/tipos-falla') {
        if (m === 'POST') {
          const falla = { ...b, id: 'falla-demo', prestador_id: prestador, activa: true }
          fallas.push(falla)
          return Promise.resolve(falla)
        }
        return Promise.resolve(fallas)
      }
      if (ruta === '/catalogos/equipos') {
        if (m === 'POST') {
          const equipo = { ...b, id: 'eq-demo', tenant_id: tenant, estado: 'activo' }
          equipos.push(equipo)
          return Promise.resolve(equipo)
        }
        return Promise.resolve(equipos)
      }
      if (ruta === '/catalogos/equipos/eq-demo') return Promise.resolve(equipos[0])
      if (ruta === '/medidores/tipos') {
        if (m === 'POST') {
          const tipo = { ...b, id: 'tipo-med-demo', tenant_id: null, prestador_id: null, activo: true }
          tiposMedidor.push(tipo)
          return Promise.resolve(tipo)
        }
        return Promise.resolve(tiposMedidor)
      }
      if (ruta === '/medidores/equipos/eq-demo') {
        if (m === 'POST') {
          const medidor = { ...b, id: 'med-demo', equipo_id: 'eq-demo', tenant_id: tenant, valor_maximo: null }
          medidores.push(medidor)
          return Promise.resolve(medidor)
        }
        return Promise.resolve(medidores)
      }
      if (ruta === '/medidores/med-demo' && m === 'PUT') {
        Object.assign(medidores[0]!, b)
        return Promise.resolve(medidores[0])
      }
      if (ruta === '/folios') {
        if (m === 'POST') {
          const folio = { ...b, id: 'folio-demo', tenant_id: tenant, estado: 'capturado',
            numero_folio: 'DEMO-0001', tecnico_id: null }
          folios.push(folio)
          return Promise.resolve(folio)
        }
        return Promise.resolve(folios)
      }
      if (ruta === '/folios/folio-demo') return Promise.resolve({ folio: folios[0] })
      if (ruta === '/operacion/tablero') {
        return Promise.resolve({ tecnicos: [{
          tecnico_id: 'id-tecnico', usuario_id: 'id-usuario-tecnico', nombre: 'Técnico DEMO',
          en_jornada: true, lat: 25.5, lng: -103.4,
          ultima_posicion_at: '2026-11-18T12:00:00Z',
        }] })
      }
      throw Error('Ruta inesperada: ' + m + ' ' + ruta)
    })
  })

  it('crea familia, tipo, falla y folio DEMO una sola vez, luego reutiliza los datos', async () => {
    const seguimiento = await crearYSeguirFolioDemo()
    expect(seguimiento.numero).toBe('DEMO-0001')
    expect(seguimiento.estado).toBe('capturado')
    expect(seguimiento.lat).toBeNull()
    expect(seguimiento.diagnosticoGPS).toContain('Sin técnico')
    expect(familias).toHaveLength(1)
    expect(tipos).toHaveLength(1)
    expect(fallas).toHaveLength(1)
    expect(equipos).toHaveLength(1)
    expect(folios).toHaveLength(1)
    expect(familias[0]?.nombre).toMatch(/^TESTBOT DEMO/)
    const segundo = await crearYSeguirFolioDemo()
    expect(segundo.id).toBe(seguimiento.id)
    expect(familias).toHaveLength(1)
    expect(tipos).toHaveLength(1)
    expect(fallas).toHaveLength(1)
    expect(equipos).toHaveLength(1)
    expect(folios).toHaveLength(1)
  })

  it('crea un tipo de medidor TESTBOT global si catálogo está vacío, y reutiliza medidor sin duplicados', async () => {
    const primero = await ejecutarEscrituraDemo('medidores')
    expect(primero?.estado).toBe('alta_cambio_demo_verificados')
    expect(tiposMedidor).toHaveLength(1)
    expect(tiposMedidor[0]?.global).toBe(true)
    expect(tiposMedidor[0]?.nombre).toMatch(/^TESTBOT DEMO/)
    expect(medidores).toHaveLength(1)
    expect(medidores[0]?.numero_serie_medidor).toBe('TESTBOT-DEMO-MED')
    expect(medidores[0]?.valor_maximo).toBe(99999)
    const segundo = await ejecutarEscrituraDemo('medidores')
    expect(segundo?.estado).toBe('alta_cambio_demo_verificados')
    expect(tiposMedidor).toHaveLength(1)
    expect(medidores).toHaveLength(1)
    expect(fakeApi.mock.calls.filter(([ruta, opciones]) => ruta === '/medidores/tipos' &&
      opciones?.metodo === 'POST')).toHaveLength(1)
    expect(fakeApi.mock.calls.filter(([ruta, opciones]) => ruta === '/medidores/equipos/eq-demo' &&
      opciones?.metodo === 'POST')).toHaveLength(1)
  })

  it('bloquea tipos de medidor no DEMO aunque coincidan en nombre', async () => {
    tiposMedidor.push({ id: 'no-demo', nombre: 'TESTBOT DEMO - Horómetro de laboratorio ficticio',
      tenant_id: 'otra-empresa', prestador_id: null, activo: true })
    await expect(ejecutarEscrituraDemo('medidores')).rejects.toThrow('Tipo de medidor no global')
    expect(medidores).toHaveLength(0)
    expect(fakeApi.mock.calls.filter(([, opciones]) => opciones?.metodo === 'POST' &&
      opciones?.cuerpo?.tipo_medidor_id)).toHaveLength(0)
  })

  it('relaciona folio.usuario técnico con tablero.usuario_id y no con tablero.tecnico_id', async () => {
    await crearYSeguirFolioDemo()
    folios[0]!.tecnico_id = 'id-usuario-tecnico'
    const resultado = await consultarSeguimientoFolioDemo()
    expect(resultado?.tecnicoNombre).toBe('Técnico DEMO')
    expect(resultado?.enJornada).toBe(true)
    expect(resultado?.ultimaPosicion).toBe('2026-11-18T12:00:00Z')
    expect(resultado?.lat).toBe(25.5)
  })

  it('genera TXT con estado, errores e IDs ficticios sin información de autenticación', () => {
    const doc = reporteTestBotTXT({
      ...INICIAL_RECORRIDO,
      indice: 1,
      resultados: [{
        id: 'biblioteca', nombre: 'Biblioteca técnica', estado: 'error',
        mensaje: 'Fallo HTTP', comprobadoEn: '2026-11-18T18:00:00Z',
        detalles: ['ERROR funcional: GET /api/biblioteca/manuales → HTTP 422 · VALIDACION'],
      }],
    }, 7, ['Comienza prueba'], null, new Date('2026-11-18T18:00:00Z'))
    expect(doc).toContain('GET /api/biblioteca/manuales')
    expect(doc).toContain('Errores: 1')
    expect(doc).toContain('Módulos evaluados: 1/')
    expect(doc).not.toContain('access_token')
    expect(doc).not.toContain('cookie=')
  })
})
