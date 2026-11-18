import { beforeEach, describe, expect, it, vi } from 'vitest'

const { fakeApi } = vi.hoisted(() => ({ fakeApi: vi.fn() }))
vi.mock('../src/services/api', () => ({ api: fakeApi }))

import { ejecutarEscrituraDemo, MODULOS_CON_ALTAS_DEMO } from '../src/services/testbotEscriturasDemo'

const tenant = 't-demo'
const prestador = 'p-demo'
const unidad = {
  id: 'un-demo', tenant_id: tenant, codigo: 'TESTBOT-DEMO-UN',
  nombre: 'TESTBOT DEMO - Unidad de pruebas', direccion: 'Ubicación ficticia - validada por TestBot',
}
const grupo = {
  id: 'g-demo', tenant_id: tenant, nombre: 'TESTBOT DEMO - Grupo de unidades',
  descripcion: 'Validado por TESTBOT DEMO', unidad_ids: [unidad.id],
}

describe('TestBot escrituras DEMO', () => {
  beforeEach(() => {
    fakeApi.mockReset()
  })

  it('no escribe sin cliente y prestador DEMO activos exactamente identificados', async () => {
    fakeApi.mockImplementation((ruta: string) => {
      if (ruta === '/tenants') return Promise.resolve([{ id: 'real', razon_social: 'CLIENTE REAL', estado: 'activo' }])
      if (ruta === '/prestadores') {
        return Promise.resolve([{ id: prestador, razon_social: 'MANTENIMIENTO DEMO ACMA SA DE CV', estado: 'activo' }])
      }
      throw Error('No debería consultar ' + ruta)
    })
    await expect(ejecutarEscrituraDemo('unidades')).rejects.toThrow('Falta el cliente')
    expect(fakeApi.mock.calls.filter(([, o]) => o?.metodo && o.metodo !== 'GET')).toHaveLength(0)
  })

  it('frena escrituras si el tenant DEMO tiene varios prestadores activos', async () => {
    fakeApi.mockImplementation((ruta: string) => {
      if (ruta === '/tenants') return Promise.resolve([{ id: tenant, razon_social: 'EMPRESA DEMO ACMA SA DE CV', estado: 'activo' }])
      if (ruta === '/prestadores') return Promise.resolve([{ id: prestador, razon_social: 'MANTENIMIENTO DEMO ACMA SA DE CV', estado: 'activo' }])
      if (ruta === '/tenants/' + tenant + '/prestadores') {
        return Promise.resolve([
          { id: 'v1', prestador_id: prestador, estado: 'activo' },
          { id: 'v2', prestador_id: 'otro', estado: 'activo' },
        ])
      }
      throw Error('Ruta imprevista: ' + ruta)
    })
    await expect(ejecutarEscrituraDemo('inventario')).rejects.toThrow('únicamente al prestador DEMO')
    expect(fakeApi.mock.calls.some(([, o]) => o?.metodo === 'POST')).toBe(false)
  })

  it('reutiliza una UN y grupo DEMO y comprueba su persistencia sin duplicarlos', async () => {
    fakeApi.mockImplementation((ruta: string, o?: { metodo?: string }) => {
      if (ruta === '/tenants') return Promise.resolve([{ id: tenant, razon_social: 'EMPRESA DEMO ACMA SA DE CV', estado: 'activo' }])
      if (ruta === '/prestadores') return Promise.resolve([{ id: prestador, razon_social: 'MANTENIMIENTO DEMO ACMA SA DE CV', estado: 'activo' }])
      if (ruta === '/tenants/' + tenant + '/prestadores') return Promise.resolve([
        { id: 'v-demo', prestador_id: prestador, estado: 'activo' },
      ])
      if (ruta === '/unidades-negocio') return Promise.resolve([unidad])
      if (ruta === '/grupos-un') return Promise.resolve([grupo])
      if (ruta === '/unidades-negocio/' + unidad.id) return Promise.resolve(unidad)
      if (ruta === '/grupos-un/' + grupo.id) return Promise.resolve(grupo)
      throw Error('Ruta imprevista: ' + ruta + ' ' + (o?.metodo ?? 'GET'))
    })
    const prueba = await ejecutarEscrituraDemo('unidades')
    expect(prueba?.estado).toBe('alta_cambio_demo_verificados')
    expect(fakeApi.mock.calls.some(([, o]) => o?.metodo === 'POST')).toBe(false)
    expect(fakeApi.mock.calls.some(([, o]) => o?.metodo === 'PATCH')).toBe(false)
    expect(fakeApi.mock.calls.some(([, o]) => o?.metodo === 'PUT')).toBe(false)
  })

  it('no considera los módulos derivados como altas ficticias', async () => {
    expect(MODULOS_CON_ALTAS_DEMO).not.toContain('erp')
    expect(MODULOS_CON_ALTAS_DEMO).not.toContain('mensajeria')
    expect(MODULOS_CON_ALTAS_DEMO).not.toContain('usuarios')
    expect(await ejecutarEscrituraDemo('erp')).toBeNull()
    expect(await ejecutarEscrituraDemo('app_campo')).toBeNull()
    expect(fakeApi).not.toHaveBeenCalled()
  })
})
