import { act, render, renderHook, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { IndicadorEstadoTestBot } from '../src/components/IndicadorEstadoTestBot'
import {
  estadoDePrueba, EVENTO_FORMULARIOS_TESTBOT, EVENTO_RECORRIDO_TESTBOT,
  useIndicadoresTestBot,
} from '../src/services/testbotEstadoVisual'

describe('Iconos del estado real de ACMA TestBot', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => localStorage.clear())

  it('distingue altas, ediciones, consultas, pendientes, errores y ausencia de prueba', () => {
    expect(estadoDePrueba('alta_cambio_demo_verificados').tipo).toBe('edicion')
    expect(estadoDePrueba('alta_demo_verificada').tipo).toBe('alta')
    expect(estadoDePrueba('consulta_verificada').tipo).toBe('consulta')
    expect(estadoDePrueba('pendiente_funcional').tipo).toBe('pendiente')
    expect(estadoDePrueba('requiere_otro_rol').tipo).toBe('pendiente')
    expect(estadoDePrueba('error').tipo).toBe('error')
    expect(estadoDePrueba().tipo).toBe('sin_prueba')
    expect(estadoDePrueba('consulta_verificada').explicacion).toMatch(/no están verificados/i)
  })

  it('muestra color e icono con explicación accesible (no solo color)', () => {
    render(<IndicadorEstadoTestBot estado={estadoDePrueba('consulta_verificada', '2026-11-19T17:03:16Z')} />)
    const icono = screen.getByRole('img', { name: /Solo consulta/ })
    expect(icono.getAttribute('data-testid')).toBe('estado-testbot-consulta')
    expect(icono.getAttribute('title')).toContain('Última prueba: ')
    expect(screen.getByText('Solo consulta')).toBeTruthy()
  })

  it('sin pruebas no debe mostrar éxito verde', () => {
    render(<IndicadorEstadoTestBot compacto />)
    const icono = screen.getByRole('img', { name: /Sin probar/ })
    expect(icono.getAttribute('data-testid')).toBe('estado-testbot-sin_prueba')
    expect(icono.className).toContain('slate')
  })

  it('actualiza el indicador en la misma pestaña y lo asocia solo al Superadmin autenticado', () => {
    const { result } = renderHook(() => useIndicadoresTestBot('super-1', true))
    expect(result.current.modulos.folios).toBeUndefined()
    act(() => {
      localStorage.setItem('acma.testbot.secuencia.v1.super-1', JSON.stringify({
        indice: 31, resultados: [{
          id: 'folios', estado: 'alta_demo_verificada',
          comprobadoEn: '2026-11-18T22:05:31Z', mensaje: '', nombre: 'Folios', detalles: [],
        }, {
          id: 'app_campo', estado: 'requiere_otro_rol', comprobadoEn: '', nombre: '',
          mensaje: '', detalles: [],
        }],
      }))
      window.dispatchEvent(new Event(EVENTO_RECORRIDO_TESTBOT))
    })
    expect(result.current.modulos.folios.tipo).toBe('alta')
    expect(result.current.modulos.app_campo.tipo).toBe('pendiente')
    expect(result.current.formularios.tipo).toBe('sin_prueba')
    act(() => {
      localStorage.setItem('acma.testbot.formularios.v2.super-1', JSON.stringify({ paso: 7 }))
      window.dispatchEvent(new Event(EVENTO_FORMULARIOS_TESTBOT))
    })
    expect(result.current.formularios.etiqueta).toContain('7/7')
  })

  it('no expone indicadores de Superadmin a otros roles', () => {
    localStorage.setItem('acma.testbot.secuencia.v1.super-1', JSON.stringify({
      indice: 1, resultados: [{ id: 'folios', estado: 'alta_demo_verificada' }],
    }))
    const { result } = renderHook(() => useIndicadoresTestBot('super-1', false))
    expect(result.current.modulos.folios).toBeUndefined()
    expect(result.current.tieneResultados).toBe(false)
  })
})
