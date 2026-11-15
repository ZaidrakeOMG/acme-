/** Mapa del plan de rutas (§4.1). F2-06.
 *
 * Una polilínea y una numeración por técnico, con **color y también texto**: la paleta sola no sirve para quien no
 * distingue colores, así que cada parada lleva su número y cada ruta su nombre en la leyenda (la misma regla que
 * el tablero de P10).
 *
 * Usa Leaflet con las teselas del proveedor configurado, igual que el mapa en vivo de F2-03: no se agrega ninguna
 * dependencia ni se llama a ningún servicio de pago.
 */
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useMemo, useRef } from 'react'
import { CENTRO_POR_DEFECTO, ZOOM_POR_DEFECTO, proveedorActual } from '../../services/mapas'
import type { RutaTecnico, TrazoRuta } from '../../types/rutas'

/** Paleta accesible (la de los tableros de P10), con el nombre del técnico siempre visible al lado. */
const COLORES: readonly string[] = ['#1d4ed8', '#b45309', '#047857', '#9d174d', '#4338ca', '#0f766e', '#a16207', '#7c2d12']

interface Props {
  rutas: RutaTecnico[]
  trazos: TrazoRuta[]
}

export function MapaRutas({ rutas, trazos }: Props) {
  const contenedor = useRef<HTMLDivElement | null>(null)
  const mapa = useRef<L.Map | null>(null)
  const capa = useRef<L.LayerGroup | null>(null)
  const proveedor = useMemo(() => proveedorActual(), [])
  const color = useMemo(() => {
    const m = new Map<string, string>()
    rutas.forEach((r, i) => m.set(r.tecnico_id, COLORES[i % COLORES.length] ?? COLORES[0]!))
    return m
  }, [rutas])

  useEffect(() => {
    if (mapa.current || !contenedor.current) return
    // Sin `preferCanvas`: el lienzo necesita un contexto 2D que no existe sin pantalla (en las pruebas, por
    // ejemplo) y ahí Leaflet truena al dibujar. Aquí hay pocas polilíneas, así que el SVG alcanza.
    const m = L.map(contenedor.current, { center: CENTRO_POR_DEFECTO, zoom: ZOOM_POR_DEFECTO })
    L.tileLayer(proveedor.url, { attribution: proveedor.atribucion, maxZoom: proveedor.maxZoom }).addTo(m)
    capa.current = L.layerGroup().addTo(m)
    mapa.current = m
    return () => {
      // Igual que el mapa en vivo: si una capa ya no está, su `remove()` lanza y tumbaría la pantalla.
      try { m.remove() } catch (e) { console.debug('El mapa se desmontó con una capa a medias', e) }
      mapa.current = null
      capa.current = null
    }
  }, [proveedor])

  // El plan cambia pocas veces (al calcular, al mover una parada, al publicar), así que aquí sí se redibuja todo:
  // no es el caso del mapa en vivo, que recibe posiciones cada 30 segundos.
  useEffect(() => {
    const m = mapa.current
    const grupo = capa.current
    if (!m || !grupo) return
    grupo.clearLayers()
    const puntos: L.LatLngExpression[] = []
    for (const trazo of trazos) {
      if (trazo.puntos.length < 2) continue
      const linea = L.polyline(trazo.puntos as L.LatLngExpression[], {
        color: color.get(trazo.tecnico_id) ?? COLORES[0], weight: 4, opacity: 0.75,
      })
      linea.bindTooltip(trazo.tecnico, { sticky: true })
      linea.addTo(grupo)
      puntos.push(...(trazo.puntos as L.LatLngExpression[]))
    }
    for (const ruta of rutas) {
      const trazo = trazos.find((t) => t.tecnico_id === ruta.tecnico_id)
      if (!trazo) continue
      // El trazo arranca en la posición del técnico, así que la parada k va en el vértice k+1.
      ruta.paradas.forEach((parada, k) => {
        const vertice = trazo.puntos[k + 1]
        if (!vertice) return
        const marca = L.marker(vertice as L.LatLngExpression, {
          icon: L.divIcon({
            className: 'acma-parada',
            html: `<span style="background:${color.get(ruta.tecnico_id) ?? COLORES[0]};color:#fff;`
              + 'border-radius:9999px;width:1.5rem;height:1.5rem;display:flex;align-items:center;'
              + `justify-content:center;font-size:.7rem;font-weight:600">${parada.orden + 1}</span>`,
            iconSize: [24, 24], iconAnchor: [12, 12],
          }),
        })
        marca.bindTooltip(`${ruta.tecnico} · ${parada.orden + 1}. ${parada.numero_folio} · ${parada.un_codigo}`,
                          { direction: 'top' })
        marca.addTo(grupo)
      })
    }
    if (puntos.length) m.fitBounds(L.latLngBounds(puntos).pad(0.15))
  }, [rutas, trazos, color])

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <div className="mb-2 flex flex-wrap gap-3 text-xs">
        {rutas.map((r) => (
          <span key={r.tecnico_id} className="flex items-center gap-1">
            <span aria-hidden className="inline-block h-3 w-3 rounded-full"
              style={{ background: color.get(r.tecnico_id) }} />
            {`${r.tecnico} · ${r.paradas.length} paradas · ${r.km.toFixed(1)} km`}
          </span>
        ))}
      </div>
      <div ref={contenedor} role="img" aria-label="Mapa del plan de rutas por técnico"
        className="h-80 w-full rounded-lg" data-testid="mapa-rutas" />
      {trazos.length === 0 && (
        <p className="mt-2 text-xs text-slate-500">
          El plan todavía no tiene trazos dibujables: se generan al calcular las rutas.
        </p>
      )}
    </div>
  )
}
