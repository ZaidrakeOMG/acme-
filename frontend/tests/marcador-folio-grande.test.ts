import { describe, expect, it } from 'vitest'
import { contenidoMarcadorFolio, posicionServicioDelFolio, posicionTecnicoDelFolio } from '../src/services/marcadorFolio'

const tecnico = {
  tecnico_id: 't-001',
  usuario_id: 'u-001',
  en_jornada: true,
  lat: 25.54,
  lng: -103.42,
}

describe('Marcador grande y seguimiento GPS del folio en Operaciones', () => {
  it('ubica el técnico por Usuario.id y no por Tecnico.id', () => {
    expect(posicionTecnicoDelFolio({ tecnico_id: 'u-001' }, [tecnico]))
      .toEqual({ tecnicoId: 't-001', lat: 25.54, lng: -103.42 })
    expect(posicionTecnicoDelFolio({ tecnico_id: 't-001' }, [tecnico])).toBeNull()
  })

  it('no dibuja ubicación cuando no existe técnico, jornada o coordenadas válidas', () => {
    expect(posicionTecnicoDelFolio({ tecnico_id: null }, [tecnico])).toBeNull()
    expect(posicionTecnicoDelFolio({ tecnico_id: 'u-001' }, [{ ...tecnico, en_jornada: false }])).toBeNull()
    expect(posicionTecnicoDelFolio({ tecnico_id: 'u-001' }, [{ ...tecnico, lat: null }])).toBeNull()
    expect(posicionTecnicoDelFolio({ tecnico_id: 'u-001' }, [{ ...tecnico, lng: 181 }])).toBeNull()
    expect(posicionTecnicoDelFolio({ tecnico_id: 'u-001' }, [{ ...tecnico, lat: Infinity }])).toBeNull()
  })

  it('muestra las coordenadas registradas de la sucursal sin atribuirlas al técnico', () => {
    const unidad = { un_id: 'un-001', lat: 25.54, lng: -103.42 }
    expect(posicionServicioDelFolio({ un_id: 'un-001' }, [unidad]))
      .toEqual({ lat: 25.54, lng: -103.42 })
    expect(posicionServicioDelFolio({ un_id: 'otra' }, [unidad])).toBeNull()
    expect(posicionServicioDelFolio({ un_id: 'un-001' }, [{ ...unidad, lat: 0, lng: 0 }])).toBeNull()
    expect(posicionServicioDelFolio({ un_id: 'un-001' }, [{ ...unidad, lat: Infinity }])).toBeNull()
  })

  it('distingue visiblemente la sucursal del GPS en vivo', () => {
    const marcador = contenidoMarcadorFolio('F-000123', 'servicio')
    expect(marcador.className).toContain('acma-folio-pin--servicio')
    expect(marcador.textContent).toContain('SUCURSAL · SIN GPS EN VIVO')
    expect(marcador.getAttribute('aria-label')).toContain('sin GPS en vivo')
  })

  it('dibuja un pin accesible y destacado con número visible para GPS del técnico', () => {
    const marcador = contenidoMarcadorFolio('F-000001', 'tecnico')
    expect(marcador.className).toContain('acma-folio-pin--tecnico')
    expect(marcador.textContent).toContain('F-000001')
    expect(marcador.textContent).toContain('UBICACIÓN DEL TÉCNICO')
    expect(marcador.getAttribute('aria-label')).toContain('F-000001')
    expect(marcador.querySelector('svg path')).toBeTruthy()
    expect(marcador.querySelector('.acma-folio-pin__pulso')).toBeTruthy()
  })

  it('distingue el GPS personal DEMO y no permite inyección de HTML por folio', () => {
    const numero = '<img src=x onerror=alert(1)>'
    const marcador = contenidoMarcadorFolio(numero, 'demo')
    expect(marcador.className).toContain('acma-folio-pin--demo')
    expect(marcador.querySelector('strong')?.textContent).toBe(numero)
    expect(marcador.querySelector('img')).toBeNull()
    expect(marcador.textContent).toContain('GPS PERSONAL · DEMO')
  })
})
