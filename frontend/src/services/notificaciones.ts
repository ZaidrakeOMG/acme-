/**
 * Notificaciones push de aprobación (stub de P04). El canal real (push con botones APROBAR/RECHAZAR en la pantalla
 * de bloqueo, minuta) llega en P07; aquí solo se registra en consola y se guarda en memoria.
 */
export interface Notificacion {
  titulo: string
  cuerpo?: string
  datos?: Record<string, unknown>
  fecha: Date
}

export const enviadas: Notificacion[] = []

export function notificar(titulo: string, cuerpo = '', datos: Record<string, unknown> = {}): Notificacion {
  const n: Notificacion = { titulo, cuerpo, datos, fecha: new Date() }
  enviadas.push(n)
  if (typeof console !== 'undefined') console.info(`[notificación] ${titulo}${cuerpo ? ` — ${cuerpo}` : ''}`, datos)
  return n
}
