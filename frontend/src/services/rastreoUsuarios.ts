/** Geolocalización voluntaria del usuario conectado; sin relación con folios. */
import { api } from './api'

export interface EstadoMiUbicacion {
  compartiendo: boolean
  ultima_at: string | null
}
export interface UsuarioGps {
  usuario_id: string
  usuario_nombre: string
  dispositivo: 'pc' | 'android' | 'iphone' | 'navegador'
  lat: number
  lng: number
  precision_m: number | null
  ultima_at: string
}

export const consultarMiUbicacion = () => api<EstadoMiUbicacion>('/mi-ubicacion')
export const iniciarMiUbicacion = (dispositivo: string) =>
  api<EstadoMiUbicacion>('/mi-ubicacion/iniciar', {
    metodo: 'POST', cuerpo: { acepto: true, dispositivo },
  })
export const enviarMiUbicacion = (lat: number, lng: number, precision_m: number | null) =>
  api<EstadoMiUbicacion>('/mi-ubicacion', { metodo: 'PUT', cuerpo: { lat, lng, precision_m } })
export const detenerMiUbicacion = () =>
  api<EstadoMiUbicacion>('/mi-ubicacion/detener', { metodo: 'POST' })
export const usuariosCompartiendo = () =>
  api<UsuarioGps[]>('/operacion/usuarios-compartiendo')
