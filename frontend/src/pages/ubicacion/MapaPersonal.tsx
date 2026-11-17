import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useMemo, useRef } from 'react'
import { CENTRO_POR_DEFECTO, ZOOM_POR_DEFECTO, proveedorActual } from '../../services/mapas'

export interface PersonaGPS {
  usuario_id: string
  nombre: string
  rol: string
  lat: number
  lng: number
  precision_m: number | null
  ultima_ubicacion_at: string
}

interface Props {
  personas: PersonaGPS[]
  seleccionado: string | null
  alSeleccionar: (id: string) => void
}

/** Mapa OSM interactivo, equivalente en navegación a Google Maps, sin clave
 *  comercial: no incluye recorridos ni posiciones anteriores del personal.
 */
export default function MapaPersonal({ personas, seleccionado, alSeleccionar }: Props) {
  const contenedor = useRef<HTMLDivElement | null>(null)
  const mapa = useRef<L.Map | null>(null)
  const puntos = useRef<L.LayerGroup | null>(null)
  const encuadrado = useRef(false)
  const proveedor = useMemo(() => proveedorActual(), [])

  useEffect(() => {
    if (!contenedor.current || mapa.current) return
    const instancia = L.map(contenedor.current, {
      center: CENTRO_POR_DEFECTO, zoom: ZOOM_POR_DEFECTO,
      zoomControl: true, preferCanvas: true,
    })
    L.tileLayer(proveedor.url, {
      attribution: proveedor.atribucion, maxZoom: proveedor.maxZoom,
    }).addTo(instancia)
    const grupo = L.layerGroup().addTo(instancia)
    mapa.current = instancia
    puntos.current = grupo
    const ajustar = () => instancia.invalidateSize()
    const t = window.setTimeout(ajustar, 100)
    return () => {
      window.clearTimeout(t)
      instancia.remove()
      mapa.current = null
      puntos.current = null
      encuadrado.current = false
    }
  }, [proveedor])

  useEffect(() => {
    const instancia = mapa.current
    const grupo = puntos.current
    if (!instancia || !grupo) return
    grupo.clearLayers()
    for (const persona of personas) {
      if (!Number.isFinite(persona.lat) || !Number.isFinite(persona.lng)) continue
      const elegido = persona.usuario_id === seleccionado
      const marca = L.circleMarker([persona.lat, persona.lng], {
        radius: elegido ? 12 : 9,
        weight: elegido ? 4 : 2,
        color: elegido ? '#581027' : '#a30b30',
        fillColor: '#bf2249',
        fillOpacity: 0.85,
      })
      // Evita insertar HTML proporcionado por usuarios en el mapa.
      const etiqueta = document.createElement('span')
      etiqueta.textContent = persona.nombre
      marca.bindTooltip(etiqueta)
      marca.on('click', () => alSeleccionar(persona.usuario_id))
      marca.addTo(grupo)
    }
    if (!encuadrado.current && personas.length) {
      const ubicaciones = personas
        .filter(p => Number.isFinite(p.lat) && Number.isFinite(p.lng))
        .map(p => L.latLng(p.lat, p.lng))
      if (ubicaciones.length) {
        instancia.fitBounds(L.latLngBounds(ubicaciones), { padding: [35, 35], maxZoom: 15 })
        encuadrado.current = true
      }
    }
  }, [personas, seleccionado, alSeleccionar])

  useEffect(() => {
    const persona = personas.find(p => p.usuario_id === seleccionado)
    if (persona && mapa.current) mapa.current.setView([persona.lat, persona.lng], 16)
  }, [seleccionado, personas])

  return (
    <div ref={contenedor} role="application" aria-label="Mapa de ubicaciones consentidas de personal"
      data-testid="mapa-personal-android"
      className="h-[55vh] min-h-80 w-full rounded-2xl border border-slate-200" />
  )
}
