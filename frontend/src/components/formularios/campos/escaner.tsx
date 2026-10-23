import { useEffect, useRef, useState } from 'react'
import { api } from '../../../services/api'
import type { Equipo } from '../../../types/api'
import type { PropsCampo } from './basicos'

/** Escáner QR / código de barras con @zxing/browser (cámara) y captura manual opcional. */
export function Escaner({ campo, valor, onChange, soloLectura }: PropsCampo & { onEquipo?: (e: Equipo | null) => void }) {
  const cfg = campo.config
  const [activo, setActivo] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [equipo, setEquipo] = useState<Equipo | null>(null)
  const video = useRef<HTMLVideoElement>(null)
  const detener = useRef<(() => void) | null>(null)

  useEffect(() => () => detener.current?.(), [])

  useEffect(() => {
    if (!cfg.precargar_equipo || !valor) { setEquipo(null); return }
    api<Equipo[]>('/catalogos/equipos', { params: { q: String(valor) } }).then((l) => setEquipo(l.find((e) => e.codigo === valor || e.numero_serie === valor) ?? l[0] ?? null)).catch(() => setEquipo(null))
  }, [valor, cfg.precargar_equipo])

  async function iniciar() {
    setError(null)
    try {
      const { BrowserMultiFormatReader } = await import('@zxing/browser')
      const { BarcodeFormat, DecodeHintType } = await import('@zxing/library')
      const formatos = (cfg.formatos ?? ['qr']).flatMap((f) => ({ qr: [BarcodeFormat.QR_CODE], ean: [BarcodeFormat.EAN_13, BarcodeFormat.EAN_8], code128: [BarcodeFormat.CODE_128], datamatrix: [BarcodeFormat.DATA_MATRIX] })[f])
      const hints = new Map([[DecodeHintType.POSSIBLE_FORMATS, formatos]])
      const lector = new BrowserMultiFormatReader(hints)
      setActivo(true)
      const control = await lector.decodeFromVideoDevice(undefined, video.current!, (resultado) => {
        if (resultado) { onChange(resultado.getText()); control.stop(); setActivo(false) }
      })
      detener.current = () => control.stop()
    } catch {
      setError('No se pudo iniciar la cámara para escanear')
      setActivo(false)
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <input id={campo.clave} name={campo.clave} type="text" value={(valor as string) ?? ''} readOnly={!cfg.permitir_captura_manual || soloLectura} placeholder={cfg.permitir_captura_manual ? 'Escanea o escribe el código' : 'Escanea el código'}
               onChange={(e) => onChange(e.target.value)} className="flex-1 rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm" />
        {!soloLectura && (activo
          ? <button type="button" className="rounded-lg border px-3 py-2 text-sm" onClick={() => { detener.current?.(); setActivo(false) }}>Cancelar</button>
          : <button type="button" className="rounded-lg bg-primario px-3 py-2 text-sm text-white" onClick={() => void iniciar()}>Escanear</button>)}
      </div>
      {activo && <video ref={video} className="w-full max-w-sm rounded-lg bg-black" muted playsInline />}
      {equipo && (
        <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-700" data-testid="contexto-equipo">
          <strong>{equipo.codigo}</strong> · {equipo.nombre} · {[equipo.marca, equipo.modelo, equipo.numero_serie].filter(Boolean).join(' · ')}
          {equipo.con_contrato_activo ? ' · Con contrato' : ' · Sin contrato'}
        </div>
      )}
      {error && <p className="text-xs text-red-700" role="alert">{error}</p>}
      <p className="text-xs text-slate-500">Formatos: {(cfg.formatos ?? []).join(', ').toUpperCase()}</p>
    </div>
  )
}
