/** Cliente de /api/mensajeria y del teléfono del propio usuario (F2-02). */
import type {
  CanalMensajeria, ConfiguracionMensajeria, Consumo, Envio, MiTelefono, Modos, Plantilla, VistaPrevia,
} from '../types/mensajeria'
import { api } from './api'

type Params = Record<string, string | number | boolean | null | undefined>

// ------------------------------------------------------------------ configuración y consumo
export const configuracionMensajeria = (params: Params = {}) =>
  api<ConfiguracionMensajeria | null>('/mensajeria/configuracion', { params })
export const guardarConfiguracionMensajeria = (cambios: Partial<ConfiguracionMensajeria>, params: Params = {}) =>
  api<ConfiguracionMensajeria>('/mensajeria/configuracion', { metodo: 'PUT', cuerpo: cambios, params })
export const consumoMensajeria = (params: Params = {}) => api<Consumo>('/mensajeria/consumo', { params })
export const modosMensajeria = () => api<Modos>('/mensajeria/modos')

// ------------------------------------------------------------------ plantillas
export const listarPlantillas = (params: Params = {}) => api<Plantilla[]>('/mensajeria/plantillas', { params })
export const editarPlantilla = (id: string, cambios: Partial<Plantilla>) =>
  api<Plantilla>(`/mensajeria/plantillas/${id}`, { metodo: 'PUT', cuerpo: cambios })
export const vistaPreviaPlantilla = (id: string) => api<VistaPrevia>(`/mensajeria/plantillas/${id}/vista-previa`)
export const exportarPlantilla = (id: string) => api<Record<string, unknown>>(`/mensajeria/plantillas/${id}/exportar`)

// ------------------------------------------------------------------ bitácora
export const listarEnvios = (params: Params = {}) => api<Envio[]>('/mensajeria/envios', { params })
export const enviosDelFolio = (folioId: string) => api<Envio[]>('/mensajeria/envios', { params: { folio_id: folioId, limite: 20 } })
export const pruebaDeEnvio = (canal: CanalMensajeria, telefono?: string, clave?: string) =>
  api<{ estado: string; modo: string; proveedor: string; cuerpo: string; detalle: string; codigo_error: string }>(
    '/mensajeria/prueba', { metodo: 'POST', cuerpo: { canal, telefono: telefono || null, clave: clave || 'notificacion_generica' } })
export const simularWebhook = (cuerpo: Record<string, unknown>) =>
  api<Record<string, unknown>>('/mensajeria/webhook/simular', { metodo: 'POST', cuerpo })
export const mensajesSimulados = () =>
  api<{ modo_whatsapp: string; modo_sms: string; mensajes: Record<string, unknown>[] }>('/mensajeria/simulados')

/** Destino de un enlace corto `/l/{codigo}`: lo abre quien recibió el mensaje, sin sesión. */
export const destinoDeEnlace = (codigo: string) =>
  api<{ destino: string; canal: string; evento: string }>(`/mensajeria/enlaces/${codigo}`, { sinAuth: true })

// ------------------------------------------------------------------ mi teléfono
export const miTelefono = () => api<MiTelefono>('/usuarios/me/telefono')
export const guardarMiTelefono = (telefono: string) =>
  api<MiTelefono>('/usuarios/me/telefono', { metodo: 'PUT', cuerpo: { telefono } })
export const borrarMiTelefono = () => api<MiTelefono>('/usuarios/me/telefono', { metodo: 'DELETE' })
export const pedirCodigo = (canal: CanalMensajeria) =>
  api<{ enviado: boolean; canal: string; minutos: number; modo: string }>(
    '/usuarios/me/telefono/codigo', { metodo: 'POST', params: { canal } })
export const verificarTelefono = (codigo: string) =>
  api<MiTelefono>('/usuarios/me/telefono/verificar', { metodo: 'POST', cuerpo: { codigo } })
export const fijarConsentimiento = (canal: CanalMensajeria, acepta: boolean) =>
  api<MiTelefono>('/usuarios/me/consentimiento', { metodo: 'PUT', cuerpo: { canal, acepta } })
