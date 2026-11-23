import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useMemo, useRef } from 'react'
import { CENTRO_POR_DEFECTO, ZOOM_POR_DEFECTO, proveedorActual } from '../../services/mapas'
import type { UsuarioRastreable } from '../../services/rastreoUsuarios'

type Props = {
  usuarios: UsuarioRastreable[]
  seleccionadoId: string | null
  alSeleccionar: (id: string) => void
}

/** Solo ubicaciones voluntarias de USUARIOS. Aquí no hay folios, jornadas ni rutas. */
export default function MapaRastreoUsuarios({ usuarios, seleccionadoId, alSeleccionar }: Props) {
  const contenedor = useRef<HTMLDivElement | null>(null)
  const mapa = useRef<L.Map | null>(null)
  const marcadores = useRef<Map<string, L.Marker>>(new Map())
  const primerAjuste = useRef(false)
  const proveedor = useMemo(() => proveedorActual(), [])

  useEffect(() => {
    if (mapa.current || !contenedor.current) return
    const m = L.map(contenedor.current, {
      center: CENTRO_POR_DEFECTO,
      zoom: ZOOM_POR_DEFECTO,
      preferCanvas: true,
    })
    L.tileLayer(proveedor.url, {
      attribution: proveedor.atribucion, maxZoom: proveedor.maxZoom,
    }).addTo(m)
    mapa.current = m
    return () => {
      try { m.remove() } catch { /* desmontaje después de HMR */ }
      mapa.current = null
      marcadores.current.clear()
      primerAjuste.current = false
    }
  }, [proveedor])

  useEffect(() => {
    const m = mapa.current
    if (!m) return
    const visibles = usuarios.filter(u => u.gps_activo && u.lat != null && u.lng != null)
    const ids = new Set(visibles.map(u => u.usuario_id))
    for (const u of visibles) {
      const coord: [number, number] = [u.lat!, u.lng!]
      const seleccionado = u.usuario_id === seleccionadoId
      const texto = document.createElement('span')
      texto.textContent = u.usuario_nombre + ' · GPS compartido · ' + (u.dispositivo ?? 'dispositivo')
      // Los iconos HTML evitan el canvas de Leaflet: también funcionan en
      // WebView, Safari y entornos de prueba sin API de lienzo.
      const icono = L.divIcon({
        className: 'acma-gps-persona',
        html: '<span aria-hidden="true" style="display:block;width:100%;height:100%;border-radius:50%;background:#10b981;border:3px solid #047857;box-shadow:0 2px 12px #065f4666"></span>',
        iconSize: seleccionado ? [27, 27] : [20, 20],
        iconAnchor: seleccionado ? [13, 13] : [10, 10],
      })
      const anterior = marcadores.current.get(u.usuario_id)
      if (anterior) {
        anterior.setLatLng(coord)
        anterior.setTooltipContent(texto)
        anterior.setIcon(icono)
      } else {
        const marcador = L.marker(coord, { icon: icono })
        marcador.bindTooltip(texto, { direction: 'top' })
        marcador.on('click', () => alSeleccionar(u.usuario_id))
        marcador.addTo(m)
        marcadores.current.set(u.usuario_id, marcador)
      }
    }
    for (const [id, marcador] of marcadores.current) {
      if (!ids.has(id)) { marcador.remove(); marcadores.current.delete(id) }
    }
    const elegido = visibles.find(u => u.usuario_id === seleccionadoId)
    if (elegido) {
      m.setView([elegido.lat!, elegido.lng!], 16, { animate: true })
    } else if (!primerAjuste.current && visibles.length > 0) {
      const limites = L.latLngBounds(visibles.map(u => [u.lat!, u.lng!] as [number, number]))
      m.fitBounds(limites.pad(0.25), { maxZoom: 14 })
      primerAjuste.current = true
    }
  }, [usuarios, seleccionadoId, alSeleccionar])

  return (
    <div className="relative h-[380px] w-full overflow-hidden rounded-2xl bg-slate-100 sm:h-[550px]">
      <div ref={contenedor} role="application" aria-label="Mapa de ubicación de usuarios autorizados"
        className="h-full w-full" />
      {usuarios.every(u => !u.gps_activo) && (
        <p className="pointer-events-none absolute left-3 top-3 z-[400] rounded-xl bg-white/95 p-3 text-xs text-slate-700 shadow">
          Sin ubicaciones compartidas. Los marcadores aparecen cuando cada usuario activa su GPS.
        </p>
      )}
    </div>
  )
}
