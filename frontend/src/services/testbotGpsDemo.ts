/**
 * Canal EXCLUSIVAMENTE LOCAL para probar el GPS con la cuenta Superadmin.
 * No usa el endpoint /operacion/posiciones, no suplanta a un Técnico,
 * no escribe coordenadas en BD, cookies ni localStorage.
 * El marcador se publica solo entre pestañas abiertas del mismo origen.
 */
export const CANAL_GPS_TESTBOT = 'acma.testbot.gps-personal.v1'

export interface PuntoGpsDemo {
  tipo: 'posicion'
  usuarioId: string
  folioId: string
  numero: string
  lat: number
  lng: number
  precisionM: number | null
  capturadaAt: string
}

export type EventoGpsDemo =
  | PuntoGpsDemo
  | { tipo: 'detener'; usuarioId: string }
  | { tipo: 'solicitud'; usuarioId: string }

export function abrirCanalGpsDemo(): BroadcastChannel | null {
  try {
    return typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel(CANAL_GPS_TESTBOT)
  } catch {
    return null
  }
}

export function validarPuntoGpsDemo(valor: unknown, usuarioId: string): PuntoGpsDemo | null {
  if (!valor || typeof valor !== 'object') return null
  const p = valor as Partial<PuntoGpsDemo>
  if (p.tipo !== 'posicion' || p.usuarioId !== usuarioId ||
      typeof p.folioId !== 'string' || !p.folioId ||
      typeof p.numero !== 'string' || !p.numero ||
      typeof p.lat !== 'number' || typeof p.lng !== 'number' ||
      !Number.isFinite(p.lat) || !Number.isFinite(p.lng) ||
      Math.abs(p.lat) > 90 || Math.abs(p.lng) > 180 ||
      typeof p.capturadaAt !== 'string' || !Number.isFinite(Date.parse(p.capturadaAt))) return null
  const precisionM = typeof p.precisionM === 'number' && Number.isFinite(p.precisionM) && p.precisionM >= 0
    ? p.precisionM : null
  return {
    tipo: 'posicion', usuarioId, folioId: p.folioId, numero: p.numero,
    lat: p.lat, lng: p.lng, precisionM, capturadaAt: p.capturadaAt,
  }
}
