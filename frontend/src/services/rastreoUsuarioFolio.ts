/** GPS voluntario del usuario que participa en un folio. Solo en primer plano. */
import { api } from './api'

export interface EstadoCompartirFolio {
  compartiendo: boolean
  ultima_at: string | null
}

export interface UsuarioCompartiendoFolio {
  folio_id: string
  usuario_id: string
  usuario_nombre: string
  lat: number
  lng: number
  precision_m: number | null
  ultima_at: string
}

export const miRastreoFolio = (folioId: string) =>
  api<EstadoCompartirFolio>(`/folios/${folioId}/mi-rastreo`)
export const comenzarRastreoFolio = (folioId: string) =>
  api<EstadoCompartirFolio>(`/folios/${folioId}/compartir-ubicacion`, {
    metodo: 'POST', cuerpo: { acepto: true },
  })
export const actualizarRastreoFolio = (folioId: string, lat: number, lng: number,
                                      precision_m: number | null) =>
  api<EstadoCompartirFolio>(`/folios/${folioId}/compartir-ubicacion`, {
    metodo: 'PUT', cuerpo: { lat, lng, precision_m },
  })
export const detenerRastreoFolio = (folioId: string) =>
  api<EstadoCompartirFolio>(`/folios/${folioId}/detener-ubicacion`, { metodo: 'POST' })
export const usuariosCompartiendoFolios = () =>
  api<UsuarioCompartiendoFolio[]>('/operacion/usuarios-compartiendo')
