/** Posición del asistente flotante en píxeles CSS para Web, Android WebView y iOS.
 * La burbuja se mueve con Pointer Events (ratón, toque y stylus) y teclado.
 * No se almacenan coordenadas GPS; son coordenadas de la interfaz.
 */
export type PuntoBurbuja = { x: number; y: number }
export type VistaBurbuja = { ancho: number; alto: number }
export const TAMANO_BURBUJA = 56
const MARGEN = 12

export function ajustarBurbuja(p: PuntoBurbuja, vista: VistaBurbuja): PuntoBurbuja {
  return {
    x: Math.max(MARGEN, Math.min(Math.max(MARGEN, vista.ancho - TAMANO_BURBUJA - MARGEN), p.x)),
    y: Math.max(MARGEN, Math.min(Math.max(MARGEN, vista.alto - TAMANO_BURBUJA - MARGEN), p.y)),
  }
}

export function inicioBurbuja(vista: VistaBurbuja): PuntoBurbuja {
  const margenInferior = vista.ancho < 1024 ? 118 : 28
  return ajustarBurbuja({
    x: vista.ancho - TAMANO_BURBUJA - 20,
    y: vista.alto - TAMANO_BURBUJA - margenInferior,
  }, vista)
}

export function posicionPanel(
  p: PuntoBurbuja, vista: VistaBurbuja,
): { left: number; top: number; ancho: number; alto: number } {
  const ancho = Math.max(1, Math.min(390, vista.ancho - 2 * MARGEN))
  const alto = Math.max(1, Math.min(620, Math.max(170, Math.floor(vista.alto * .74)), vista.alto - 2 * MARGEN))
  const left = Math.max(MARGEN, Math.min(Math.max(MARGEN, vista.ancho - ancho - MARGEN), p.x + TAMANO_BURBUJA - ancho))
  const espacioArriba = p.y - MARGEN
  const espacioAbajo = vista.alto - (p.y + TAMANO_BURBUJA) - MARGEN
  const deseado = espacioArriba >= alto + 12 || espacioArriba >= espacioAbajo
    ? p.y - alto - 12
    : p.y + TAMANO_BURBUJA + 12
  const top = Math.max(MARGEN, Math.min(Math.max(MARGEN, vista.alto - alto - MARGEN), deseado))
  return { left, top, ancho, alto }
}

export function leerBurbuja(usuarioId: string, vista: VistaBurbuja): PuntoBurbuja {
  const inicial = inicioBurbuja(vista)
  if (!usuarioId) return inicial
  try {
    const valor = JSON.parse(localStorage.getItem('acma.asistente.burbuja.v1.' + usuarioId) || 'null') as Partial<PuntoBurbuja> | null
    if (typeof valor?.x === 'number' && typeof valor?.y === 'number' &&
      Number.isFinite(valor.x) && Number.isFinite(valor.y)) {
      return ajustarBurbuja({ x: valor.x, y: valor.y }, vista)
    }
  } catch { /* almacenamiento deshabilitado: la burbuja funciona sin persistencia */ }
  return inicial
}

export function guardarBurbuja(usuarioId: string, p: PuntoBurbuja) {
  if (!usuarioId) return
  try {
    localStorage.setItem('acma.asistente.burbuja.v1.' + usuarioId, JSON.stringify(p))
  } catch { /* almacenamiento opcional */ }
}
