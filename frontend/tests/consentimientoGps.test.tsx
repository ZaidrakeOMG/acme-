import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { claveConsentimientoGps } from '../src/contexts/RastreoUsuarioContext'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const ID = '00000000-0000-0000-0000-000000000001'

function simularGps() {
  Object.defineProperty(window, 'isSecureContext', { configurable: true, value: true })
  Object.defineProperty(navigator, 'permissions', {
    configurable: true,
    value: { query: vi.fn().mockResolvedValue({ state: 'granted' }) },
  })
  const getCurrentPosition = vi.fn((correcto: PositionCallback) => correcto({
    coords: {
      latitude: 25.54, longitude: -103.42, accuracy: 15,
      altitude: null, altitudeAccuracy: null, heading: null, speed: null,
    },
    timestamp: Date.now(),
    toJSON: () => ({}),
  } as GeolocationPosition))
  let errorGps: PositionErrorCallback | null = null
  Object.defineProperty(navigator, 'geolocation', {
    configurable: true, value: {
      getCurrentPosition,
      watchPosition: vi.fn((_ok: PositionCallback, error: PositionErrorCallback) => { errorGps = error; return 4 }),
      clearWatch: vi.fn(),
    },
  })
  const requestPermission = vi.fn()
  vi.stubGlobal('Notification', { permission: 'granted', requestPermission })
  return { getCurrentPosition, requestPermission, apagarGps: () => errorGps?.({ code: 2, message: 'GPS apagado' } as GeolocationPositionError) }
}

function entrar(ruta: string) {
  localStorage.setItem('acma.sesion', '1')
  const llamadas = simularApi({
    'POST /api/auth/refresh': () => ({ json: TOKENS }),
    'GET /api/auth/yo': () => ({ json: perfil('tecnico') }),
    'GET /api/notificaciones/no-leidas': () => ({ json: { no_leidas: 0 } }),
    'GET /api/configuracion/mis-permisos': () => ({ json: [] }),
    'GET /api/folios': () => ({ json: [] }),
    'GET /api/operacion/mi-jornada': () => ({ json: { estatus: 'fuera_de_jornada', jornada: null, aviso_aceptado: false } }),
    'GET /api/operacion/mis-alertas': () => ({ json: [] }),
    'GET /api/mi-ubicacion': () => ({ json: { compartiendo: false, ultima_at: null } }),
    'POST /api/mi-ubicacion/iniciar': () => ({ json: { compartiendo: true, ultima_at: null } }),
    'PUT /api/mi-ubicacion': () => ({ json: { compartiendo: true, ultima_at: new Date().toISOString() } }),
    'POST /api/mi-ubicacion/detener': () => ({ json: { compartiendo: false, ultima_at: null } }),
  })
  renderApp(ruta)
  return llamadas
}

afterEach(() => {
  vi.unstubAllGlobals()
  // Restaurar interfaces de geolocalización para no contaminar otras pruebas.
  Reflect.deleteProperty(navigator, 'geolocation')
  Reflect.deleteProperty(navigator, 'permissions')
})

describe('ACMA 0.1.7 · permiso persistente y privacidad de ubicación', () => {
  it('guarda cada elección por usuario y no la comparte con otra cuenta', () => {
    expect(claveConsentimientoGps('usuario-a')).not.toBe(claveConsentimientoGps('usuario-b'))
  })

  it('si el usuario autorizó antes, restaura GPS sin nuevos avisos de permisos', async () => {
    localStorage.setItem(claveConsentimientoGps(ID), '1')
    const { getCurrentPosition, requestPermission } = simularGps()
    const llamadas = entrar('/mi-ubicacion')
    await waitFor(() => expect(llamadas.some(x => x.clave === 'POST /api/mi-ubicacion/iniciar')).toBe(true))
    expect(getCurrentPosition).toHaveBeenCalled()
    expect(requestPermission).not.toHaveBeenCalled()
    await waitFor(() => expect(screen.queryByTestId('solicitud-ubicacion-inicio')).not.toBeInTheDocument())
    expect(localStorage.getItem(claveConsentimientoGps(ID))).toBe('1')
  })

  it('el técnico no puede detener GPS y seguir trabajando; si se apaga conserva autorización', async () => {
    localStorage.setItem(claveConsentimientoGps(ID), '1')
    const { apagarGps } = simularGps()
    const llamadas = entrar('/mi-ubicacion')
    await waitFor(() => expect(screen.queryByTestId('solicitud-ubicacion-inicio')).not.toBeInTheDocument())
    await screen.findByText('GPS activo · autorización guardada')
    expect(screen.queryByRole('button', { name: 'Dejar de compartir mi ubicación' })).not.toBeInTheDocument()
    act(() => apagarGps())
    const aviso = await screen.findByTestId('solicitud-ubicacion-inicio')
    expect(within(aviso).getByRole('button', { name: 'Reintentar GPS' })).toBeInTheDocument()
    expect(within(aviso).getByRole('button', { name: 'Cerrar sesión' })).toBeInTheDocument()
    expect(document.querySelector('.acma-shell')).toHaveAttribute('inert')
    expect(localStorage.getItem(claveConsentimientoGps(ID))).toBe('1')
    await waitFor(() => expect(llamadas.some(x => x.clave === 'POST /api/mi-ubicacion/detener')).toBe(true))
    await userEvent.setup().click(within(aviso).getByRole('button', { name: 'Reintentar GPS' }))
    await waitFor(() => expect(screen.queryByTestId('solicitud-ubicacion-inicio')).not.toBeInTheDocument())
    expect(llamadas.filter(x => x.clave === 'POST /api/mi-ubicacion/iniciar')).toHaveLength(2)
  })

  it('bloquea si Android reporta que su interruptor de ubicación está apagado', async () => {
    localStorage.setItem(claveConsentimientoGps(ID), '1')
    simularGps()
    entrar('/mi-ubicacion')
    await waitFor(() => expect(screen.queryByTestId('solicitud-ubicacion-inicio')).not.toBeInTheDocument())
    act(() => window.dispatchEvent(new CustomEvent('acma:estado-gps', { detail: { autorizado: true, servicioActivo: false } })))
    const aviso = await screen.findByTestId('solicitud-ubicacion-inicio')
    expect(within(aviso).getByText(/GPS desactivado/)).toBeInTheDocument()
    expect(localStorage.getItem(claveConsentimientoGps(ID))).toBe('1')
  })
})
