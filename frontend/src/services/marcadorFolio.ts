/** Marcador grande de seguimiento de folio. Solo dibuja coordenadas realmente recibidas.
 * Nunca interpreta la dirección del servicio como GPS del técnico.
 */
import type { FolioEnTablero, TecnicoEnTablero } from '../types/operaciones'

export type OrigenMarcadorFolio = 'tecnico' | 'demo'

export function posicionTecnicoDelFolio(
  folio: Pick<FolioEnTablero, 'tecnico_id'> | null,
  tecnicos: Array<Pick<TecnicoEnTablero, 'usuario_id' | 'tecnico_id' | 'en_jornada' | 'lat' | 'lng'>>,
): { tecnicoId: string; lat: number; lng: number } | null {
  if (!folio?.tecnico_id) return null
  // Folio.tecnico_id es Usuario.id; la ruta de operaciones trabaja con Tecnico.id.
  const t = tecnicos.find(x => x.usuario_id === folio.tecnico_id)
  if (!t?.en_jornada || t.lat == null || t.lng == null ||
      !Number.isFinite(t.lat) || !Number.isFinite(t.lng) ||
      Math.abs(t.lat) > 90 || Math.abs(t.lng) > 180) return null
  return { tecnicoId: t.tecnico_id, lat: t.lat, lng: t.lng }
}

/** DOM seguro: nunca inyectar el número de folio sin escapar en HTML del mapa. */
export function contenidoMarcadorFolio(numero: string, origen: OrigenMarcadorFolio): HTMLDivElement {
  const raiz = document.createElement('div')
  raiz.className = 'acma-folio-pin acma-folio-pin--' + origen
  raiz.setAttribute('aria-label', origen === 'demo'
    ? 'GPS personal de prueba, folio ' + numero
    : 'Última ubicación del técnico asignado al folio ' + numero)

  const pulso = document.createElement('div')
  pulso.className = 'acma-folio-pin__pulso'
  pulso.setAttribute('aria-hidden', 'true')

  const cuerpo = document.createElement('div')
  cuerpo.className = 'acma-folio-pin__cuerpo'
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  svg.setAttribute('viewBox', '0 0 24 24')
  svg.setAttribute('width', '30')
  svg.setAttribute('height', '30')
  svg.setAttribute('fill', 'none')
  svg.setAttribute('stroke', 'currentColor')
  svg.setAttribute('stroke-width', '2.2')
  svg.setAttribute('stroke-linecap', 'round')
  svg.setAttribute('stroke-linejoin', 'round')
  const marcador = document.createElementNS('http://www.w3.org/2000/svg', 'path')
  marcador.setAttribute('d', 'M20 10c0 5-8 12-8 12S4 15 4 10a8 8 0 1 1 16 0Z')
  const centro = document.createElementNS('http://www.w3.org/2000/svg', 'circle')
  centro.setAttribute('cx', '12')
  centro.setAttribute('cy', '10')
  centro.setAttribute('r', '3')
  svg.append(marcador, centro)
  cuerpo.append(svg)

  const etiqueta = document.createElement('div')
  etiqueta.className = 'acma-folio-pin__etiqueta'
  const titulo = document.createElement('strong')
  titulo.textContent = numero
  const origenTexto = document.createElement('span')
  origenTexto.textContent = origen === 'demo' ? 'GPS PERSONAL · DEMO' : 'UBICACIÓN DEL TÉCNICO'
  etiqueta.append(titulo, origenTexto)

  raiz.append(pulso, cuerpo, etiqueta)
  return raiz
}
