/**
 * Proveedor de mapas detrás de una interfaz (F2-03, regla 3 de la segunda etapa).
 *
 * En desarrollo y en el piloto se usa **OpenStreetMap con Leaflet**: gratuito y sin cuenta. Google Maps queda
 * preparado para el paso final: con `VITE_MAPA_PROVEEDOR=google` y `VITE_MAPA_LLAVE` se cambia sin tocar la
 * pantalla, porque lo único que cambia es la capa de teselas.
 */
export interface ProveedorMapa {
  id: 'osm' | 'google'
  nombre: string
  url: string
  atribucion: string
  maxZoom: number
  requiereLlave: boolean
  disponible: boolean
}

export const OSM: ProveedorMapa = {
  id: 'osm',
  nombre: 'OpenStreetMap',
  url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  atribucion: '© colaboradores de OpenStreetMap',
  maxZoom: 19,
  requiereLlave: false,
  disponible: true,
}

function google(llave: string): ProveedorMapa {
  return {
    id: 'google',
    nombre: 'Google Maps',
    // Teselas de Google por su servicio de mapas estáticos en mosaico; la llave va en la URL de la capa.
    url: `https://maps.googleapis.com/maps/vt?pb=!1m5!1m4!1i{z}!2i{x}!3i{y}!4i256!2m3!1e0!2sm!3i0&key=${llave}`,
    atribucion: '© Google',
    maxZoom: 20,
    requiereLlave: true,
    disponible: Boolean(llave),
  }
}

/** El proveedor configurado. Sin llave de Google se queda en OpenStreetMap: el mapa nunca se queda en blanco. */
export function proveedorActual(): ProveedorMapa {
  const elegido = (import.meta.env.VITE_MAPA_PROVEEDOR as string | undefined)?.toLowerCase()
  const llave = (import.meta.env.VITE_MAPA_LLAVE as string | undefined) ?? ''
  if (elegido === 'google') {
    const g = google(llave)
    return g.disponible ? g : OSM
  }
  return OSM
}

/** Centro y zoom por defecto: la Ciudad de México, donde están las unidades del demo. */
export const CENTRO_POR_DEFECTO: [number, number] = [19.4326, -99.1332]
export const ZOOM_POR_DEFECTO = 12
