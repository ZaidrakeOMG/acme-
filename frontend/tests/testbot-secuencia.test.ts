import { beforeEach, describe, expect, it, vi } from 'vitest'
import { guardarResultado, INICIAL_RECORRIDO, probarModuloLectura, SECUENCIA_ACMA, siguienteModulo } from '../src/services/testbotSecuencia'

const { fakeApi } = vi.hoisted(() => ({ fakeApi: vi.fn() }))
vi.mock('../src/services/api', () => ({ api: fakeApi }))

describe('TestBot: continuación de módulo en módulo', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    fakeApi.mockResolvedValue([])
  })
  it('continúa con Biblioteca tras terminar Formularios y nunca regresa al principio', () => {
    expect(SECUENCIA_ACMA[0]?.id).toBe('biblioteca')
    expect(SECUENCIA_ACMA[1]?.id).toBe('operaciones')
    expect(SECUENCIA_ACMA[2]?.id).toBe('folios')
    expect(SECUENCIA_ACMA.some((m) => m.id === 'formularios')).toBe(false)
    expect(SECUENCIA_ACMA.some((m) => m.id === 'catalogos')).toBe(false)
    expect(SECUENCIA_ACMA.length).toBeGreaterThan(20)
  })
  it('Siguiente comprueba las tres consultas de Biblioteca, registra y avanza a Operaciones', async () => {
    let progreso = { ...INICIAL_RECORRIDO }
    const resultado = await probarModuloLectura('biblioteca')
    expect(resultado.estado).toBe('consulta_verificada')
    progreso = guardarResultado(progreso, resultado)
    expect(progreso.indice).toBe(1)
    expect(siguienteModulo(progreso)?.id).toBe('operaciones')
    expect(fakeApi).toHaveBeenCalledTimes(3)
    expect(fakeApi.mock.calls.map((x) => x[0])).toEqual([
      '/catalogos/tipos-equipo', '/biblioteca/manuales', '/biblioteca/contenido',
    ])
    expect(fakeApi.mock.calls.every(([, opciones]) => !opciones?.metodo || opciones.metodo === 'GET')).toBe(true)
    expect(resultado.mensaje).toMatch(/funcional.*pendiente/i)
  })
  it('un fallo real se registra, pero no bloquea continuar con Siguiente', async () => {
    fakeApi.mockRejectedValueOnce(new Error('503: backend no disponible'))
    const resultado = await probarModuloLectura('biblioteca')
    expect(resultado.estado).toBe('error')
    expect(resultado.detalles.join(' ')).toContain('503')
    const progreso = guardarResultado({ ...INICIAL_RECORRIDO }, resultado)
    expect(siguienteModulo(progreso)?.id).toBe('operaciones')
  })
  it('no simula pruebas de operador con el rol de Superadmin', async () => {
    const resultado = await probarModuloLectura('app_campo')
    expect(resultado.estado).toBe('requiere_otro_rol')
    expect(resultado.mensaje).toMatch(/Técnico y Operador/)
    expect(fakeApi).not.toHaveBeenCalled()
  })
  it('no permite insertar resultados fuera de la secuencia', () => {
    expect(() => guardarResultado({ ...INICIAL_RECORRIDO }, {
      id: 'folios', nombre: 'Folios', estado: 'consulta_verificada',
      mensaje: 'Mal orden', detalles: [], comprobadoEn: '2026-11-18',
    })).toThrow(/fuera de secuencia/)
  })
  it('reconoce problemas de contrato de respuesta y no los presenta como aprobados', async () => {
    fakeApi.mockResolvedValueOnce({ wrong: true })
    const resultado = await probarModuloLectura('biblioteca')
    expect(resultado.estado).toBe('error')
    expect(resultado.mensaje).toMatch(/Error real/)
  })
})
