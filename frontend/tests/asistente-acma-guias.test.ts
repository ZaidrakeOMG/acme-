import { describe, expect, it } from 'vitest'
import { MODULOS, modulosDe } from '../src/config/modulos'
import { CUBIERTOS_POR_GUIA, guiaPorId, identificarModuloPorRuta, resolverAyuda } from '../src/services/ayudaModulos'

describe('Asistente contextual ACMA', () => {
  it('documenta todos los módulos visibles, no solo los 31 del TestBot', () => {
    for (const m of MODULOS) {
      expect(CUBIERTOS_POR_GUIA, 'Falta la guía de ' + m.id).toContain(m.id)
      const guia = guiaPorId(m.id)
      expect(guia.objetivo.length).toBeGreaterThan(15)
      expect(guia.pasos.length).toBeGreaterThanOrEqual(3)
    }
  })

  it('encuentra la guía contextual de la pantalla actual y sus detalles', () => {
    const permisos = modulosDe('superadmin')
    const actual = identificarModuloPorRuta('/folios/folio-123', permisos)
    expect(actual?.id).toBe('folios')
    const respuesta = resolverAyuda(actual, '¿Cómo rastrear un folio?')
    expect(respuesta.titulo).toMatch(/rastrear/i)
    expect(respuesta.pasos.join(' ')).toMatch(/Operaciones en tiempo real/)
    expect(respuesta.pasos.join(' ')).toMatch(/GPS/)
    expect(respuesta.ruta).toBe('/folios')
  })

  it('contesta consultas según intención y no confunde registros con pruebas hechas', () => {
    const modulo = MODULOS.find(m => m.id === 'inventario')!
    const consulta = resolverAyuda(modulo, '¿Cómo consultar artículos?')
    expect(consulta.titulo).toMatch(/consultar/)
    expect(consulta.pasos.length).toBeGreaterThan(1)
    const alta = resolverAyuda(modulo, '¿Cómo registrar una entrada?')
    expect(alta.titulo).toMatch(/registrar/)
    expect(alta.pasos.join(' ')).toMatch(/cantidad/)
    expect(alta.consejo).toMatch(/almacén real/)
  })

  it('no propone instrucciones de otros roles sin acceso a sus apartados', () => {
    const permitidos = modulosDe('tecnico')
    const actual = identificarModuloPorRuta('/usuarios', permitidos)
    expect(actual).toBeNull()
    const ayuda = resolverAyuda(actual)
    expect(ayuda.pasos.join(' ')).toContain('Elige un módulo')
  })

  it('la guía de ayuda no hace peticiones ni modifica registros de prueba', () => {
    const respuesta = resolverAyuda(MODULOS.find(m => m.id === 'capacitacion')!, 'vencimientos')
    expect(respuesta.pasos.join(' ')).toContain('cuenta')
    expect(respuesta.consejo).toContain('Admin prestador')
  })
})
