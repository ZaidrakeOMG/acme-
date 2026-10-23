import { useRef, useState } from 'react'
import { haversineM } from '../../../services/formularios/validacion'
import type { PropsCampo } from './basicos'

interface Geo { lat: number; lng: number; lat_original: number; lng_original: number; ajustada: boolean; precision_m?: number | null }

/** Captura GPS con ajuste manual dentro del radio configurado (registro dual original/ajustada). */
export function Geolocalizacion({ campo, valor, onChange, soloLectura }: PropsCampo) {
  const cfg = campo.config
  const radio = cfg.radio_ajuste_m ?? 50
  const geo = (valor as Geo | null) ?? null
  const [error, setError] = useState<string | null>(null)
  const [ajustando, setAjustando] = useState(false)
  const [cargando, setCargando] = useState(false)
  const svg = useRef<SVGSVGElement>(null)

  function capturar() {
    setError(null)
    if (!navigator.geolocation) { setError('Este dispositivo no tiene geolocalización'); return }
    setCargando(true)
    navigator.geolocation.getCurrentPosition(
      (p) => { onChange({ lat: p.coords.latitude, lng: p.coords.longitude, lat_original: p.coords.latitude, lng_original: p.coords.longitude, ajustada: false, precision_m: p.coords.accuracy }); setCargando(false) },
      () => { setError('No se pudo obtener la ubicación; revisa los permisos'); setCargando(false) },
      { enableHighAccuracy: true, timeout: 15000 },
    )
  }

  // Mapa simple: el centro es la coordenada original; el círculo es el radio de ajuste. 1 px = radio/100 m.
  const escala = radio / 100
  const desplazamiento = geo ? haversineM(geo.lat_original, geo.lng_original, geo.lat, geo.lng) : 0
  const metrosAGrados = (dx: number, dy: number) => {
    const lat = geo!.lat_original - (dy * escala) / 111320
    const lng = geo!.lng_original + (dx * escala) / (111320 * Math.cos((geo!.lat_original * Math.PI) / 180))
    return { lat, lng }
  }
  const puntoActual = geo ? {
    x: 120 + ((geo.lng - geo.lng_original) * 111320 * Math.cos((geo.lat_original * Math.PI) / 180)) / escala,
    y: 120 - ((geo.lat - geo.lat_original) * 111320) / escala,
  } : { x: 120, y: 120 }

  function mover(e: React.PointerEvent<SVGSVGElement>) {
    if (!geo || !svg.current || e.buttons !== 1) return
    const r = svg.current.getBoundingClientRect()
    let dx = ((e.clientX - r.left) / r.width) * 240 - 120
    let dy = ((e.clientY - r.top) / r.height) * 240 - 120
    const d = Math.hypot(dx, dy)
    if (d > 100) { dx = (dx / d) * 100; dy = (dy / d) * 100 }
    const { lat, lng } = metrosAGrados(dx, dy)
    onChange({ ...geo, lat, lng, ajustada: Math.hypot(dx, dy) > 0.5 })
  }

  return (
    <div className="space-y-2 text-sm">
      {geo ? (
        <div className="rounded-lg bg-slate-50 px-3 py-2" data-testid="geo-valor">
          <p className="font-mono text-xs">{geo.lat.toFixed(6)}, {geo.lng.toFixed(6)}{geo.precision_m ? ` · ±${Math.round(geo.precision_m)} m` : ''}</p>
          {geo.ajustada && <p className="text-xs text-amber-700">Ajustada manualmente {Math.round(desplazamiento)} m desde la posición GPS ({geo.lat_original.toFixed(5)}, {geo.lng_original.toFixed(5)}). Queda registrado en auditoría.</p>}
        </div>
      ) : <p className="text-xs text-slate-500">Sin ubicación capturada</p>}
      {!soloLectura && (
        <div className="flex flex-wrap gap-2">
          <button type="button" disabled={cargando} className="rounded-lg bg-primario px-4 py-2 text-white disabled:opacity-50" onClick={capturar}>{cargando ? 'Obteniendo…' : geo ? 'Volver a capturar' : '📍 Capturar ubicación'}</button>
          {geo && radio > 0 && <button type="button" className="rounded-lg border px-4 py-2" onClick={() => setAjustando((v) => !v)}>{ajustando ? 'Listo' : `Ajustar (hasta ${radio} m)`}</button>}
        </div>
      )}
      {geo && ajustando && (
        <svg ref={svg} viewBox="0 0 240 240" className="h-60 w-60 touch-none rounded-lg border bg-white" style={{ touchAction: 'none' }} onPointerDown={mover} onPointerMove={mover} aria-label="Mapa de ajuste">
          <circle cx={120} cy={120} r={100} fill="#1C3D8F11" stroke="#1C3D8F" strokeDasharray="4 3" />
          <circle cx={120} cy={120} r={4} fill="#64748b" />
          <text x={120} y={232} textAnchor="middle" fontSize={10} fill="#64748b">radio {radio} m · arrastra el punto</text>
          <circle cx={puntoActual.x} cy={puntoActual.y} r={8} fill="#A2C62B" stroke="#1C3D8F" strokeWidth={2} />
        </svg>
      )}
      {error && <p className="text-xs text-red-700" role="alert">{error}</p>}
    </div>
  )
}
