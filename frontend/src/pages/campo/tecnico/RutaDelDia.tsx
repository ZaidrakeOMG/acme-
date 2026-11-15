/** Ruta del día del técnico y reporte de incidencia (§6.8.2, §6.8.4). F2-06.
 *
 * Lo que el técnico necesita en la calle: en qué orden va, a qué hora se espera que llegue a cada unidad, y un
 * botón para abrir la navegación. Los enlaces a **Waze** y **Google Maps** son enlaces normales, sin API ni
 * llave: funcionan en cualquier teléfono con la app instalada y en el navegador si no la tiene.
 *
 * El botón de incidencia es el disparador de §6.8.2 que faltaba: cuando el técnico no puede seguir (vehículo,
 * salud, otra causa), el sistema recalcula sus folios pendientes y el despachador recibe la propuesta.
 */
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router'
import { Aviso, Boton, Campo, Insignia, Modal, Selector } from '../../../components/ui'
import { mensajeDeError } from '../../../services/api'
import { CENTRO_POR_DEFECTO, ZOOM_POR_DEFECTO, proveedorActual } from '../../../services/mapas'
import { miRuta, reportarIncidencia } from '../../../services/rutas'
import type { MiRuta, ParadaDelTecnico, TipoIncidencia } from '../../../types/rutas'
import { NOMBRE_INCIDENCIA, enlaceGoogleMaps, enlaceWaze, hora } from '../../../types/rutas'

/** Su recorrido en el mapa, con las mismas teselas del mapa en vivo de F2-03 (sin proveedor de pago). */
function MapaDeMiRuta({ paradas }: { paradas: ParadaDelTecnico[] }) {
  const contenedor = useRef<HTMLDivElement | null>(null)
  const mapa = useRef<L.Map | null>(null)
  const proveedor = useMemo(() => proveedorActual(), [])
  const puntos = useMemo(
    () => paradas.filter((p) => p.lat != null && p.lng != null).map((p) => [p.lat!, p.lng!] as [number, number]),
    [paradas],
  )

  useEffect(() => {
    if (!contenedor.current || puntos.length === 0) return
    // Sin `preferCanvas`, como el mapa del plan: el lienzo necesita un contexto 2D que no existe sin pantalla.
    const m = L.map(contenedor.current, { center: CENTRO_POR_DEFECTO, zoom: ZOOM_POR_DEFECTO })
    L.tileLayer(proveedor.url, { attribution: proveedor.atribucion, maxZoom: proveedor.maxZoom }).addTo(m)
    if (puntos.length > 1) L.polyline(puntos, { color: '#1d4ed8', weight: 4, opacity: 0.8 }).addTo(m)
    puntos.forEach((punto, k) => {
      L.marker(punto, {
        icon: L.divIcon({
          className: 'acma-mi-parada',
          html: '<span style="background:#1d4ed8;color:#fff;border-radius:9999px;width:1.5rem;height:1.5rem;'
            + `display:flex;align-items:center;justify-content:center;font-size:.7rem;font-weight:600">${k + 1}</span>`,
          iconSize: [24, 24], iconAnchor: [12, 12],
        }),
      }).addTo(m)
    })
    m.fitBounds(L.latLngBounds(puntos).pad(0.2))
    mapa.current = m
    return () => {
      // Igual que el mapa en vivo: si una capa ya no está, su `remove()` lanza y tumbaría la pantalla.
      try { m.remove() } catch (e) { console.debug('El mapa se desmontó con una capa a medias', e) }
      mapa.current = null
    }
  }, [proveedor, puntos])

  if (puntos.length === 0) return null
  return (
    <div ref={contenedor} role="img" aria-label="Mapa de mi recorrido de hoy"
      className="h-56 w-full rounded-xl border border-slate-200" data-testid="mapa-mi-ruta" />
  )
}

export function RutaDelDia() {
  const [ruta, setRuta] = useState<MiRuta | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [modal, setModal] = useState(false)
  const [tipo, setTipo] = useState<TipoIncidencia>('vehiculo')
  const [detalle, setDetalle] = useState('')
  const [enviando, setEnviando] = useState(false)

  const cargar = useCallback(async () => {
    try { setRuta(await miRuta()) } catch (e) { setError(mensajeDeError(e)) }
  }, [])
  useEffect(() => { void cargar() }, [cargar])

  async function enviar() {
    setError(null)
    setEnviando(true)
    try {
      const r = await reportarIncidencia(tipo, detalle)
      setModal(false)
      setDetalle('')
      setAviso(r.mensaje)
      await cargar()
    } catch (e) { setError(mensajeDeError(e)) } finally { setEnviando(false) }
  }

  return (
    <section className="space-y-3" data-testid="ruta-del-dia">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Mi ruta de hoy{ruta?.paradas.length ? ` · ${ruta.paradas.length} paradas` : ''}
          {ruta?.km ? ` · ${ruta.km.toFixed(1)} km` : ''}
        </h2>
        <Boton variante="secundario" onClick={() => setModal(true)}>Reportar incidencia</Boton>
      </div>
      {error && <Aviso>{error}</Aviso>}
      {aviso && <Aviso tipo="exito">{aviso}</Aviso>}

      {ruta && !ruta.tiene_ruta && <p className="text-sm text-slate-500">{ruta.mensaje}</p>}

      {ruta?.paradas.length ? <MapaDeMiRuta paradas={ruta.paradas} /> : null}

      <ol className="space-y-3">
        {(ruta?.paradas ?? []).map((p) => (
          <li key={p.folio_id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-2">
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primario text-xs font-semibold text-white">
                  {p.orden + 1}
                </span>
                <Link to={`/campo/folio/${p.folio_id}`} className="font-mono text-sm font-semibold text-primario underline">
                  {p.numero_folio}
                </Link>
              </span>
              <Insignia>{hora(p.llegada_estimada)}</Insignia>
            </div>
            <p className="mt-1 text-base text-slate-800">{p.un_codigo} · {p.un_nombre}</p>
            {p.direccion && <p className="text-xs text-slate-500">{p.direccion}</p>}
            <p className="mt-1 text-xs text-slate-500">
              {`${p.km_desde_anterior.toFixed(1)} km y ${p.minutos_desde_anterior} min de traslado · `}
              {`${p.minutos_servicio} min de trabajo`}
            </p>
            {p.lat != null && p.lng != null ? (
              <div className="mt-2 flex gap-2">
                <a className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm active:bg-slate-50"
                  href={enlaceWaze(p.lat, p.lng)} target="_blank" rel="noreferrer">Abrir en Waze</a>
                <a className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm active:bg-slate-50"
                  href={enlaceGoogleMaps(p.lat, p.lng)} target="_blank" rel="noreferrer">Abrir en Google Maps</a>
              </div>
            ) : (
              <p className="mt-2 text-xs text-slate-400">La unidad no tiene coordenadas registradas.</p>
            )}
          </li>
        ))}
      </ol>

      <Modal titulo="Reportar una incidencia" abierto={modal} alCerrar={() => setModal(false)}>
        <div className="space-y-3">
          <p className="text-sm text-slate-600">
            Avisa si no puedes seguir con tu ruta. El despachador lo ve de inmediato y el sistema propone cómo
            repartir tus folios pendientes.
          </p>
          <Selector name="tipo" etiqueta="¿Qué pasó?" value={tipo}
            onChange={(e) => setTipo(e.target.value as TipoIncidencia)}
            opciones={Object.entries(NOMBRE_INCIDENCIA).map(([valor, texto]) => ({ valor, texto }))} />
          <Campo name="detalle" etiqueta="Detalle (opcional)" value={detalle}
            onChange={(e) => setDetalle(e.target.value)} />
          <Boton disabled={enviando} onClick={() => void enviar()}>
            {enviando ? 'Enviando…' : 'Enviar el reporte'}
          </Boton>
        </div>
      </Modal>
    </section>
  )
}
