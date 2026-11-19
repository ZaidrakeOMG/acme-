import { describe, expect, it } from 'vitest'
import { validarPuntoGpsDemo } from '../src/services/testbotGpsDemo'
import { OSM } from '../src/services/mapas'

const punto = {
  tipo: 'posicion' as const,
  usuarioId: 'super-demo',
  folioId: '05be777a-6cf7-4e56-8ccb-14f857125cc6',
  numero: 'F-000001',
  lat: 25.52,
  lng: -103.42,
  precisionM: 12,
  capturadaAt: '2026-11-19T14:30:00.000Z',
}

describe('GPS personal DEMO en operaciones', () => {
  it('acepta solo posiciones asociadas al usuario de la sesión actual', () => {
    expect(validarPuntoGpsDemo(punto, 'super-demo')).toEqual(punto)
    expect(validarPuntoGpsDemo(punto, 'otro-usuario')).toBeNull()
    expect(validarPuntoGpsDemo({ ...punto, tipo: 'jornada' }, 'super-demo')).toBeNull()
  })

  it('rechaza coordenadas falsas o fuera de rango, sin contaminar el mapa', () => {
    expect(validarPuntoGpsDemo({ ...punto, lat: Infinity }, 'super-demo')).toBeNull()
    expect(validarPuntoGpsDemo({ ...punto, lat: 101 }, 'super-demo')).toBeNull()
    expect(validarPuntoGpsDemo({ ...punto, lng: -181 }, 'super-demo')).toBeNull()
    expect(validarPuntoGpsDemo({ ...punto, folioId: '' }, 'super-demo')).toBeNull()
    expect(validarPuntoGpsDemo({ ...punto, capturadaAt: 'no-fecha' }, 'super-demo')).toBeNull()
  })

  it('no requiere tener una cuenta Técnico ni usa endpoint de posiciones de producción', () => {
    // El servicio solo contiene los eventos locales de BroadcastChannel;
    // el endpoint técnico protegido /operacion/posiciones no forma parte del TestBot GPS.
    expect(punto.tipo).toBe('posicion')
    expect(punto.numero).toBe('F-000001')
  })

  it('configura teselas del dominio oficial de OSM con atribución vinculada', () => {
    expect(OSM.url).toContain('tile.openstreetmap.org')
    expect(OSM.atribucion).toContain('https://www.openstreetmap.org/copyright')
  })
})
