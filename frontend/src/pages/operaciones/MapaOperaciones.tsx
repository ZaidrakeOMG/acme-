import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useMemo, useRef } from 'react'
import { CENTRO_POR_DEFECTO, ZOOM_POR_DEFECTO, proveedorActual } from '../../services/mapas'
import { contenidoMarcadorFolio } from '../../services/marcadorFolio'
import type { PuntoGpsDemo } from '../../services/testbotGpsDemo'
import type { PuntoRecorrido, TecnicoEnTablero, UnidadEnTablero } from '../../types/operaciones'
import { MARCADOR_ESTATUS, NOMBRE_ESTATUS } from '../../types/operaciones'

interface Props {
  tecnicos: TecnicoEnTablero[]
  unidades: UnidadEnTablero[]
  recorrido: PuntoRecorrido[]
  folioDestacado?: { numero: string; lat: number; lng: number; origen: 'tecnico' | 'servicio' | 'usuario' } | null
  gpsPersonal?: PuntoGpsDemo | null
  rutaGpsPersonal?: Array<{ lat: number; lng: number }>
  seleccionado: string | null
  centrarEn: { lat: number; lng: number; zoom?: number } | null
  alElegirTecnico: (tecnicoId: string) => void
}

/**
 * Mapa en vivo (§6.8.4) con Leaflet y las teselas del proveedor configurado (OpenStreetMap por defecto).
 *
 * **Actualiza solo el marcador que cambió**: los marcadores se guardan por técnico y en cada render se mueve el que
 * trae otra posición, en lugar de volver a dibujar el mapa. Con 50 técnicos mandando cada 30 segundos, redibujar
 * todo haría parpadear la pantalla de la oficina.
 */
export default function MapaOperaciones({ tecnicos, unidades, recorrido, folioDestacado, gpsPersonal, rutaGpsPersonal,
                                          seleccionado, centrarEn,
                                          alElegirTecnico }: Props) {
  const contenedor = useRef<HTMLDivElement | null>(null)
  const mapa = useRef<L.Map | null>(null)
  const marcadores = useRef<Map<string, L.CircleMarker>>(new Map())
  const marcadoresUn = useRef<Map<string, L.Marker>>(new Map())
  const linea = useRef<L.Polyline | null>(null)
  const marcadorGpsDemo = useRef<L.Marker | null>(null)
  const marcadorFolio = useRef<L.Marker | null>(null)
  const lineaGpsDemo = useRef<L.Polyline | null>(null)
  const proveedor = useMemo(() => proveedorActual(), [])

  // Montaje: una sola vez. La capa de teselas viene del proveedor, así que cambiarlo no toca esta pantalla.
  useEffect(() => {
    if (mapa.current || !contenedor.current) return
    const m = L.map(contenedor.current, { center: CENTRO_POR_DEFECTO, zoom: ZOOM_POR_DEFECTO,
                                          preferCanvas: true })
    L.tileLayer(proveedor.url, { attribution: proveedor.atribucion, maxZoom: proveedor.maxZoom }).addTo(m)
    mapa.current = m
    return () => {
      // Al desmontar, Leaflet limpia sus capas; si una ya no está (recarga en caliente, pantalla sin layout) su
      // `remove()` lanza, y ese error subiría por el desmontaje de React y tumbaría la pantalla entera.
      try {
        m.remove()
      } catch (e) {
        console.debug('El mapa se desmontó con una capa a medias', e)
      }
      mapa.current = null
      marcadores.current.clear()
      marcadoresUn.current.clear()
      linea.current = null
      marcadorGpsDemo.current = null
      marcadorFolio.current = null
      lineaGpsDemo.current = null
    }
  }, [proveedor])

  // Técnicos: mover solo lo que cambió.
  useEffect(() => {
    const m = mapa.current
    if (!m) return
    const vistos = new Set<string>()
    for (const t of tecnicos) {
      if (t.lat == null || t.lng == null) continue
      vistos.add(t.tecnico_id)
      const color = MARCADOR_ESTATUS[t.estatus]
      const etiqueta = `${t.nombre} · ${NOMBRE_ESTATUS[t.estatus]} · ${t.folios_pendientes} folio(s)`
      const existente = marcadores.current.get(t.tecnico_id)
      if (existente) {
        existente.setLatLng([t.lat, t.lng])
        existente.setStyle({ color, fillColor: color,
                             weight: t.tecnico_id === seleccionado ? 4 : 2 })
        existente.setTooltipContent(etiqueta)
        continue
      }
      const marcador = L.circleMarker([t.lat, t.lng], {
        radius: 9, color, fillColor: color, fillOpacity: 0.85,
        weight: t.tecnico_id === seleccionado ? 4 : 2,
      })
      marcador.bindTooltip(etiqueta, { direction: 'top' })
      marcador.on('click', () => alElegirTecnico(t.tecnico_id))
      marcador.addTo(m)
      marcadores.current.set(t.tecnico_id, marcador)
    }
    for (const [id, marcador] of marcadores.current) {
      if (!vistos.has(id)) {
        marcador.remove()
        marcadores.current.delete(id)
      }
    }
  }, [tecnicos, seleccionado, alElegirTecnico])

  // Unidades con folios activos.
  useEffect(() => {
    const m = mapa.current
    if (!m) return
    const vistos = new Set<string>()
    for (const u of unidades) {
      vistos.add(u.un_id)
      const etiqueta = `${u.codigo} · ${u.nombre} · ${u.folios_activos} folio(s) activo(s)`
      const existente = marcadoresUn.current.get(u.un_id)
      if (existente) {
        existente.setTooltipContent(etiqueta)
        continue
      }
      const marcador = L.marker([u.lat, u.lng], {
        icon: L.divIcon({
          className: 'acma-un',
          html: `<span style="display:inline-block;width:14px;height:14px;transform:rotate(45deg);
                 background:#1C3D8F;border:2px solid white;box-shadow:0 0 2px rgba(0,0,0,.4)"></span>`,
          iconSize: [14, 14], iconAnchor: [7, 7],
        }),
      })
      marcador.bindTooltip(etiqueta, { direction: 'top' })
      marcador.addTo(m)
      marcadoresUn.current.set(u.un_id, marcador)
    }
    for (const [id, marcador] of marcadoresUn.current) {
      if (!vistos.has(id)) {
        marcador.remove()
        marcadoresUn.current.delete(id)
      }
    }
  }, [unidades])

  // Recorrido del técnico elegido (últimas horas).
  useEffect(() => {
    const m = mapa.current
    if (!m) return
    try {
      linea.current?.remove()
    } catch (e) {
      console.debug('El recorrido anterior ya no estaba en el mapa', e)
    }
    linea.current = null
    if (recorrido.length < 2) return
    linea.current = L.polyline(recorrido.map((p) => [p.lat, p.lng] as [number, number]),
                               { color: '#1C3D8F', weight: 3, opacity: 0.7, dashArray: '6 6' }).addTo(m)
  }, [recorrido])

  // Marcador del técnico con GPS o, si no lo hay, sucursal registrada del folio.
  // Los dos orígenes se identifican claramente; nunca se simula GPS en vivo.
  useEffect(() => {
    const m = mapa.current
    if (!m) return
    if (!folioDestacado) {
      marcadorFolio.current?.remove()
      marcadorFolio.current = null
      return
    }
    const coords: [number, number] = [folioDestacado.lat, folioDestacado.lng]
    const icono = L.divIcon({
      className: 'acma-folio-destacado',
      html: contenidoMarcadorFolio(folioDestacado.numero, folioDestacado.origen),
      iconSize: [80, 88],
      iconAnchor: [40, 70],
    })
    if (marcadorFolio.current) {
      marcadorFolio.current.setLatLng(coords)
      marcadorFolio.current.setIcon(icono)
    } else {
      marcadorFolio.current = L.marker(coords, {
        icon: icono, zIndexOffset: 900, keyboard: false,
      }).addTo(m)
    }
    m.panTo(coords, { animate: true, duration: 0.35 })
  }, [folioDestacado])

  // GPS personal TESTBOT DEMO: marcador grande, claramente distinto del técnico real.
  useEffect(() => {
    const m = mapa.current
    if (!m) return
    if (!gpsPersonal) {
      marcadorGpsDemo.current?.remove()
      marcadorGpsDemo.current = null
      return
    }
    const coords: [number, number] = [gpsPersonal.lat, gpsPersonal.lng]
    const icono = L.divIcon({
      className: 'acma-folio-destacado',
      html: contenidoMarcadorFolio(gpsPersonal.numero, 'demo'),
      iconSize: [80, 88],
      iconAnchor: [40, 70],
    })
    if (marcadorGpsDemo.current) {
      marcadorGpsDemo.current.setLatLng(coords)
      marcadorGpsDemo.current.setIcon(icono)
    } else {
      marcadorGpsDemo.current = L.marker(coords, {
        icon: icono, zIndexOffset: 1000, keyboard: false,
      }).addTo(m)
    }
    if (!folioDestacado) m.panTo(coords, { animate: true, duration: 0.35 })
  }, [gpsPersonal, folioDestacado])

  useEffect(() => {
    const m = mapa.current
    if (!m) return
    lineaGpsDemo.current?.remove()
    lineaGpsDemo.current = null
    if (!rutaGpsPersonal || rutaGpsPersonal.length < 2) return
    lineaGpsDemo.current = L.polyline(rutaGpsPersonal.map(p => [p.lat, p.lng] as [number, number]), {
      color: '#ef4444', weight: 4, opacity: 0.8,
    }).addTo(m)
  }, [rutaGpsPersonal])

  // Centrar: en un técnico, en una unidad o en todo el mercado.
  useEffect(() => {
    const m = mapa.current
    if (!m || !centrarEn) return
    m.setView([centrarEn.lat, centrarEn.lng], centrarEn.zoom ?? 15)
  }, [centrarEn])

  return <div ref={contenedor} className="h-[60vh] min-h-80 w-full rounded-xl border border-slate-200"
              data-testid="mapa-operaciones" role="application" aria-label="Mapa de técnicos en jornada" />
}
