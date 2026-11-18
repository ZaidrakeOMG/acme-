import { beforeEach, describe, expect, it, vi } from 'vitest'
import { probarModuloLectura } from '../src/services/testbotSecuencia'

const { fakeApi } = vi.hoisted(() => ({ fakeApi: vi.fn() }))
vi.mock('../src/services/api', () => ({ api: fakeApi }))

type Llamada = [string, { params?: Record<string, string>; metodo?: string } | undefined]
const CLIENTE = { id: 'tenant-demo', razon_social: 'EMPRESA DEMO ACMA SA DE CV', estado: 'activo' }
const PRESTADOR = { id: 'prestador-demo', razon_social: 'MANTENIMIENTO DEMO ACMA SA DE CV', estado: 'activo' }

function configurar() {
  fakeApi.mockImplementation(async (ruta: string) => {
    if (ruta === '/tenants') return [CLIENTE]
    if (ruta === '/prestadores') return [PRESTADOR]
    if (ruta === '/seguimiento/periodos-presupuestales' || ruta === '/mensajeria/configuracion') return null
    if (ruta === '/mensajeria/consumo') return { total: 0 }
    if (ruta === '/capacitacion/vencimientos') throw new Error('Superadmin no pertenece a un prestador')
    return []
  })
}
function llamada(ruta: string) {
  const x = (fakeApi.mock.calls as Llamada[]).find(([p]) => p === ruta)
  expect(x, 'Se debe consultar el endpoint ' + ruta).toBeDefined()
  return x?.[1]?.params
}

describe('TestBot: scopes explícitos y errores de la bitácora real de Superadmin', () => {
  beforeEach(() => { vi.clearAllMocks(); configurar() })

  it('Preventivos añade prestador_id y limita el calendario al cliente DEMO', async () => {
    const r = await probarModuloLectura('preventivos')
    expect(r.estado).toBe('consulta_verificada')
    expect(llamada('/planes')?.prestador_id).toBe(PRESTADOR.id)
    expect(llamada('/preventivos/calendario')?.tenant_id).toBe(CLIENTE.id)
  })

  it('Seguimiento conserva null como período no configurado, no como fallo 500', async () => {
    const r = await probarModuloLectura('seguimiento')
    expect(r.estado).toBe('pendiente_funcional')
    expect(llamada('/seguimiento/periodos-presupuestales')?.tenant_id).toBe(CLIENTE.id)
    expect(r.detalles.join(' ')).toMatch(/no configurado/)
  })

  it('Rutas usa prestador_id sin crear configuración nueva', async () => {
    const r = await probarModuloLectura('rutas')
    expect(r.estado).toBe('consulta_verificada')
    expect(llamada('/rutas/mercados')?.prestador_id).toBe(PRESTADOR.id)
    expect(llamada('/rutas/tiempos-servicio')?.prestador_id).toBe(PRESTADOR.id)
    expect((fakeApi.mock.calls as Llamada[]).some(([p]) => p === '/rutas/configuracion')).toBe(false)
  })

  it('ISO 55000 delimita el resumen al cliente DEMO sin crear configuración', async () => {
    const r = await probarModuloLectura('iso55000')
    expect(r.estado).toBe('consulta_verificada')
    expect(llamada('/criticidad/resumen')?.tenant_id).toBe(CLIENTE.id)
    expect((fakeApi.mock.calls as Llamada[]).some(([p]) => p === '/criticidad/configuracion')).toBe(false)
  })

  it('ERP solo lee eventos/exportaciones, sin crear configuración ni usar credenciales', async () => {
    const r = await probarModuloLectura('erp')
    expect(r.estado).toBe('consulta_verificada')
    const rutas = (fakeApi.mock.calls as Llamada[]).map(([p]) => p)
    expect(rutas).toEqual(['/erp/exportaciones', '/erp/eventos'])
  })

  it('Mensajería admite configuración nula sin enviar mensajes ni alterar la configuración', async () => {
    const r = await probarModuloLectura('mensajeria')
    expect(r.estado).toBe('pendiente_funcional')
    expect(llamada('/mensajeria/configuracion')?.prestador_id).toBe(PRESTADOR.id)
    expect(llamada('/mensajeria/consumo')?.prestador_id).toBe(PRESTADOR.id)
  })

  it('Alertas elige solo prestador_id, nunca tenant_id simultáneamente', async () => {
    const r = await probarModuloLectura('alertas')
    expect(r.estado).toBe('consulta_verificada')
    const params = llamada('/alertas/configuracion')
    expect(params?.prestador_id).toBe(PRESTADOR.id)
    expect(params?.tenant_id).toBeUndefined()
  })

  it('Capacitación no finge vencimientos de otro rol; sí comprueba cursos', async () => {
    const r = await probarModuloLectura('capacitacion')
    expect(r.estado).toBe('requiere_otro_rol')
    expect((fakeApi.mock.calls as Llamada[]).map(([p]) => p)).toEqual(['/capacitacion/cursos'])
  })

  it('No escoge el primer registro que no sea exactamente el cliente DEMO', async () => {
    fakeApi.mockImplementation(async (ruta: string) => {
      if (ruta === '/tenants') return [{ id: 'real', razon_social: 'OTRA EMPRESA', estado: 'activo' }]
      if (ruta === '/prestadores') return [PRESTADOR]
      return []
    })
    const r = await probarModuloLectura('seguimiento')
    expect(r.estado).toBe('error')
    expect(r.detalles.join(' ')).toMatch(/exactamente un registro DEMO activo/)
    expect((fakeApi.mock.calls as Llamada[]).some(([p]) => p === '/seguimiento/periodos-presupuestales')).toBe(false)
  })

  it('Todas las pruebas nuevas usan GET sin métodos de escritura', async () => {
    for (const id of ['preventivos','seguimiento','rutas','iso55000','erp','mensajeria','alertas','capacitacion']) {
      await probarModuloLectura(id)
    }
    expect((fakeApi.mock.calls as Llamada[]).every(([,opts]) => !opts?.metodo || opts.metodo === 'GET')).toBe(true)
  })
})
