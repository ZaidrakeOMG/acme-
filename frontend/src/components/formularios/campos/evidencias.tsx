import { useEffect, useRef, useState } from 'react'
import { mensajeDeError } from '../../../services/api'
import { descargarEvidencia, eliminarEvidencia, subirEvidencia } from '../../../services/formularios/respuestas'
import type { Campo, Evidencia } from '../../../types/formularios'
import type { PropsCampo } from './basicos'

export interface PropsEvidencia extends PropsCampo {
  respuestaId: string | null
  evidencias: Evidencia[]
  onEvidencias: (lista: Evidencia[]) => void
  calidadDefaults?: { tamano_minimo_kb: number; resolucion_minima_ancho: number; resolucion_minima_alto: number; compresion_maxima_pct: number } | null
  /** evidencias de otros campos (para la imagen de referencia del dibujo) */
  todas?: Record<string, Evidencia[]>
}

function SinRespuesta() {
  return <p className="rounded-lg border border-dashed border-slate-300 px-3 py-2 text-xs text-slate-500">Vista previa: las evidencias se suben al llenar el formulario.</p>
}

async function blobDeCanvas(canvas: HTMLCanvasElement, tipo = 'image/png', calidad?: number): Promise<Blob> {
  return new Promise((res, rej) => canvas.toBlob((b) => (b ? res(b) : rej(new Error('No se pudo generar la imagen'))), tipo, calidad))
}

function dimensiones(archivo: Blob): Promise<{ ancho: number; alto: number }> {
  return new Promise((res, rej) => {
    const url = URL.createObjectURL(archivo)
    const img = new Image()
    img.onload = () => { res({ ancho: img.naturalWidth, alto: img.naturalHeight }); URL.revokeObjectURL(url) }
    img.onerror = () => { rej(new Error('Imagen inválida')); URL.revokeObjectURL(url) }
    img.src = url
  })
}

// ---------------------------------------------------------------- Fotografía

export function Fotografia({ campo, respuestaId, evidencias, onEvidencias, soloLectura, calidadDefaults }: PropsEvidencia) {
  const cfg = campo.config
  const [error, setError] = useState<string | null>(null)
  const [pendiente, setPendiente] = useState<{ blob: Blob; url: string; ancho: number; alto: number; ok: boolean; problemas: string[] } | null>(null)
  const [anotando, setAnotando] = useState(false)
  const [subiendo, setSubiendo] = useState(false)
  const [camara, setCamara] = useState<MediaStream | null>(null)
  const video = useRef<HTMLVideoElement>(null)
  const fotos = evidencias.filter((e) => e.tipo === 'foto')
  const minimos = {
    tamano_minimo_kb: cfg.calidad?.tamano_minimo_kb ?? calidadDefaults?.tamano_minimo_kb ?? 0,
    resolucion_minima_ancho: cfg.calidad?.resolucion_minima_ancho ?? calidadDefaults?.resolucion_minima_ancho ?? 0,
    resolucion_minima_alto: cfg.calidad?.resolucion_minima_alto ?? calidadDefaults?.resolucion_minima_alto ?? 0,
  }
  const etiquetaSiguiente = cfg.etiquetas_secuencia?.[fotos.length] ?? null
  const llena = fotos.length >= (cfg.cantidad_max ?? 5)

  useEffect(() => () => camara?.getTracks().forEach((t) => t.stop()), [camara])

  async function abrirCamara() {
    setError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false })
      setCamara(stream)
      setTimeout(() => { if (video.current) { video.current.srcObject = stream; void video.current.play() } }, 0)
    } catch {
      setError('No se pudo abrir la cámara; usa el botón de tomar foto del dispositivo.')
    }
  }

  async function capturar() {
    const v = video.current
    if (!v) return
    const canvas = document.createElement('canvas')
    canvas.width = v.videoWidth
    canvas.height = v.videoHeight
    canvas.getContext('2d')!.drawImage(v, 0, 0)
    const blob = await blobDeCanvas(canvas, 'image/jpeg', 0.92)
    camara?.getTracks().forEach((t) => t.stop())
    setCamara(null)
    await evaluar(blob)
  }

  async function evaluar(blob: Blob) {
    setError(null)
    try {
      const { ancho, alto } = await dimensiones(blob)
      const problemas: string[] = []
      if (blob.size < minimos.tamano_minimo_kb * 1024) problemas.push(`Pesa ${Math.round(blob.size / 1024)} KB; mínimo ${minimos.tamano_minimo_kb} KB`)
      if (ancho < minimos.resolucion_minima_ancho || alto < minimos.resolucion_minima_alto) problemas.push(`${ancho}×${alto} px; mínimo ${minimos.resolucion_minima_ancho}×${minimos.resolucion_minima_alto}`)
      const candidata = { blob, url: URL.createObjectURL(blob), ancho, alto, ok: problemas.length === 0, problemas }
      if (cfg.vista_previa_confirmacion === false && candidata.ok) await subir(candidata.blob, null, null)
      else setPendiente(candidata)
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  async function subir(blob: Blob, anotaciones: Record<string, unknown> | null, anotada: Blob | null) {
    if (!respuestaId) return
    setSubiendo(true)
    setError(null)
    try {
      const e = await subirEvidencia(respuestaId, { archivo: blob, nombre: `foto-${fotos.length + 1}.jpg`, campoClave: campo.clave, etiqueta: etiquetaSiguiente,
                                                    orden: fotos.length, anotaciones: anotaciones ?? undefined, imagenAnotada: anotada })
      onEvidencias([...evidencias, e])
      setPendiente(null)
      setAnotando(false)
    } catch (err) {
      setError(mensajeDeError(err))
    } finally {
      setSubiendo(false)
    }
  }

  if (!respuestaId) return <SinRespuesta />
  return (
    <div className="space-y-3">
      <ul className="flex flex-wrap gap-2">
        {fotos.map((f) => (
          <li key={f.id} className="relative">
            <MiniaturaEvidencia evidencia={f} respuestaId={respuestaId} />
            {f.etiqueta && <span className="absolute bottom-1 left-1 rounded bg-black/60 px-1 text-[10px] text-white">{f.etiqueta}</span>}
            {!soloLectura && <button type="button" aria-label={`Quitar ${f.etiqueta ?? f.nombre_original}`} className="absolute -right-1 -top-1 h-5 w-5 rounded-full bg-red-600 text-xs text-white"
                                     onClick={() => void eliminarEvidencia(respuestaId, f.id).then(() => onEvidencias(evidencias.filter((x) => x.id !== f.id))).catch((e) => setError(mensajeDeError(e)))}>✕</button>}
          </li>
        ))}
      </ul>
      <p className="text-xs text-slate-500">{fotos.length} de {cfg.cantidad_min}–{cfg.cantidad_max} foto(s){etiquetaSiguiente && !llena ? ` · siguiente: ${etiquetaSiguiente}` : ''}</p>
      {!soloLectura && !llena && !pendiente && (
        camara ? (
          <div className="space-y-2">
            <video ref={video} playsInline muted className="w-full max-w-md rounded-lg bg-black" />
            <div className="flex gap-2">
              <button type="button" className="rounded-lg bg-primario px-4 py-2 text-sm font-medium text-white" onClick={() => void capturar()}>Capturar</button>
              <button type="button" className="rounded-lg border px-4 py-2 text-sm" onClick={() => { camara.getTracks().forEach((t) => t.stop()); setCamara(null) }}>Cancelar</button>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap gap-2">
            <button type="button" className="rounded-lg bg-primario px-4 py-2 text-sm font-medium text-white" onClick={() => void abrirCamara()}>📷 Tomar foto</button>
            <label className="cursor-pointer rounded-lg border border-slate-300 px-4 py-2 text-sm">
              {cfg.origen === 'camara_galeria' ? 'Elegir de la galería' : 'Cámara del dispositivo'}
              <input type="file" accept="image/*" capture={cfg.origen === 'camara' ? 'environment' : undefined} className="sr-only" aria-label={`Archivo de ${campo.etiqueta}`}
                     onChange={(e) => { const f = e.target.files?.[0]; if (f) void evaluar(f); e.target.value = '' }} />
            </label>
          </div>
        )
      )}
      {pendiente && (
        <div className={`rounded-lg border-2 p-3 ${pendiente.ok ? 'border-green-500 bg-green-50' : 'border-red-500 bg-red-50'}`} data-testid="vista-previa-foto">
          <div className="flex items-start gap-3">
            <img src={pendiente.url} alt="Vista previa" className="h-28 w-28 rounded object-cover" />
            <div className="flex-1 text-sm">
              <p className={`font-semibold ${pendiente.ok ? 'text-green-800' : 'text-red-800'}`}>{pendiente.ok ? '● Calidad correcta' : '● Calidad insuficiente'}</p>
              <p className="text-xs text-slate-600">{pendiente.ancho}×{pendiente.alto} px · {Math.round(pendiente.blob.size / 1024)} KB</p>
              {pendiente.problemas.map((p) => <p key={p} className="text-xs text-red-700">{p}</p>)}
            </div>
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            {pendiente.ok && !anotando && <button type="button" disabled={subiendo} className="rounded-lg bg-primario px-3 py-1.5 text-sm text-white" onClick={() => void subir(pendiente.blob, null, null)}>Aceptar</button>}
            {pendiente.ok && cfg.permitir_anotacion && !anotando && <button type="button" className="rounded-lg border px-3 py-1.5 text-sm" onClick={() => setAnotando(true)}>Anotar</button>}
            <button type="button" className="rounded-lg border px-3 py-1.5 text-sm" onClick={() => { setPendiente(null); setAnotando(false) }}>{pendiente.ok ? 'Descartar' : 'Volver a tomar'}</button>
          </div>
          {anotando && <Anotador imagen={pendiente.url} alGuardar={(anot, blob) => void subir(pendiente.blob, anot, blob)} alCancelar={() => setAnotando(false)} />}
        </div>
      )}
      {error && <p className="text-xs text-red-700" role="alert">{error}</p>}
    </div>
  )
}

function MiniaturaEvidencia({ evidencia, respuestaId }: { evidencia: Evidencia; respuestaId: string }) {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    let activo = true
    let objeto: string | null = null
    descargarEvidencia(respuestaId, evidencia.id).then((b) => { if (activo) { objeto = URL.createObjectURL(b); setUrl(objeto) } }).catch(() => setUrl(null))
    return () => { activo = false; if (objeto) URL.revokeObjectURL(objeto) }
  }, [respuestaId, evidencia.id])
  return url ? <img src={url} alt={evidencia.etiqueta ?? evidencia.nombre_original} className="h-20 w-20 rounded object-cover" /> : <div className="h-20 w-20 rounded bg-slate-200" />
}

/** Lienzo de anotación sobre una imagen: trazos, flechas y círculos. El original no se toca; se guarda la compuesta aparte. */
function Anotador({ imagen, alGuardar, alCancelar }: { imagen: string; alGuardar: (anotaciones: Record<string, unknown>, compuesta: Blob) => void; alCancelar: () => void }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const [herramienta, setHerramienta] = useState<'trazo' | 'flecha' | 'circulo'>('trazo')
  const [color, setColor] = useState('#ff0000')
  const trazos = useRef<{ tipo: string; color: string; puntos: number[][] }[]>([])
  const actual = useRef<number[][]>([])
  const fondo = useRef<HTMLImageElement | null>(null)

  useEffect(() => {
    const img = new Image()
    img.onload = () => { fondo.current = img; const c = canvas.current!; c.width = img.naturalWidth; c.height = img.naturalHeight; redibujar() }
    img.src = imagen
  }, [imagen])

  function redibujar(extra?: number[][]) {
    const c = canvas.current
    if (!c || !fondo.current) return
    const ctx = c.getContext('2d')!
    ctx.drawImage(fondo.current, 0, 0)
    ctx.lineWidth = Math.max(3, c.width / 200)
    ctx.lineCap = 'round'
    for (const t of [...trazos.current, ...(extra ? [{ tipo: herramienta, color, puntos: extra }] : [])]) dibujarTrazo(ctx, t)
  }

  function dibujarTrazo(ctx: CanvasRenderingContext2D, t: { tipo: string; color: string; puntos: number[][] }) {
    ctx.strokeStyle = t.color
    const p = t.puntos
    if (p.length < 2) return
    ctx.beginPath()
    if (t.tipo === 'trazo') { ctx.moveTo(p[0]![0]!, p[0]![1]!); p.forEach(([x, y]) => ctx.lineTo(x!, y!)); ctx.stroke(); return }
    const [x1, y1] = p[0]!
    const [x2, y2] = p[p.length - 1]!
    if (t.tipo === 'circulo') { const r = Math.hypot(x2! - x1!, y2! - y1!); ctx.arc(x1!, y1!, r, 0, Math.PI * 2); ctx.stroke(); return }
    ctx.moveTo(x1!, y1!); ctx.lineTo(x2!, y2!); ctx.stroke()
    const ang = Math.atan2(y2! - y1!, x2! - x1!)
    const cabeza = ctx.lineWidth * 4
    ctx.beginPath(); ctx.moveTo(x2!, y2!)
    ctx.lineTo(x2! - cabeza * Math.cos(ang - 0.5), y2! - cabeza * Math.sin(ang - 0.5))
    ctx.moveTo(x2!, y2!)
    ctx.lineTo(x2! - cabeza * Math.cos(ang + 0.5), y2! - cabeza * Math.sin(ang + 0.5))
    ctx.stroke()
  }

  const punto = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const r = canvas.current!.getBoundingClientRect()
    return [((e.clientX - r.left) / r.width) * canvas.current!.width, ((e.clientY - r.top) / r.height) * canvas.current!.height]
  }

  return (
    <div className="mt-3 space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {(['trazo', 'flecha', 'circulo'] as const).map((h) => <button key={h} type="button" aria-pressed={herramienta === h} className={`rounded px-2 py-1 ${herramienta === h ? 'bg-primario text-white' : 'bg-slate-100'}`} onClick={() => setHerramienta(h)}>{h}</button>)}
        <input type="color" aria-label="Color" value={color} onChange={(e) => setColor(e.target.value)} />
        <button type="button" className="rounded bg-slate-100 px-2 py-1" onClick={() => { trazos.current.pop(); redibujar() }}>Deshacer</button>
      </div>
      <canvas ref={canvas} className="w-full max-w-md touch-none rounded border" style={{ touchAction: 'none' }}
              onPointerDown={(e) => { actual.current = [punto(e)]; e.currentTarget.setPointerCapture(e.pointerId) }}
              onPointerMove={(e) => { if (actual.current.length) { actual.current.push(punto(e)); redibujar(actual.current) } }}
              onPointerUp={() => { if (actual.current.length > 1) trazos.current.push({ tipo: herramienta, color, puntos: actual.current }); actual.current = []; redibujar() }} />
      <div className="flex gap-2">
        <button type="button" className="rounded-lg bg-primario px-3 py-1.5 text-sm text-white" onClick={async () => alGuardar({ trazos: trazos.current }, await blobDeCanvas(canvas.current!))}>Guardar con anotaciones</button>
        <button type="button" className="rounded-lg border px-3 py-1.5 text-sm" onClick={alCancelar}>Cancelar</button>
      </div>
    </div>
  )
}

// ------------------------------------------------------------- Firma y dibujo

export function Lienzo({ etiqueta, fondo, permitirColor, permitirGrosor, alGuardar, pantallaCompleta, textoConfirmar }: {
  etiqueta: string; fondo?: string | null; permitirColor?: boolean; permitirGrosor?: boolean; alGuardar: (blob: Blob, tieneTrazo: boolean) => void; pantallaCompleta?: boolean; textoConfirmar: string
}) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const [color, setColor] = useState('#1C3D8F')
  const [grosor, setGrosor] = useState(3)
  const [tieneTrazo, setTieneTrazo] = useState(false)
  const [completa, setCompleta] = useState(false)
  const dibujando = useRef(false)

  useEffect(() => {
    const c = canvas.current!
    const ctx = c.getContext('2d')!
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, c.width, c.height)
    if (fondo) { const img = new Image(); img.crossOrigin = 'anonymous'; img.onload = () => ctx.drawImage(img, 0, 0, c.width, c.height); img.src = fondo }
  }, [fondo, completa])

  const punto = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const r = canvas.current!.getBoundingClientRect()
    return [((e.clientX - r.left) / r.width) * canvas.current!.width, ((e.clientY - r.top) / r.height) * canvas.current!.height] as const
  }
  const limpiar = () => { const c = canvas.current!; const ctx = c.getContext('2d')!; ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, c.width, c.height); setTieneTrazo(false) }
  const contenido = (
    <div className={`space-y-2 ${completa ? 'fixed inset-0 z-50 flex flex-col bg-white p-4' : ''}`}>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {permitirColor && <input type="color" aria-label="Color del trazo" value={color} onChange={(e) => setColor(e.target.value)} />}
        {permitirGrosor && <input type="range" aria-label="Grosor" min={1} max={12} value={grosor} onChange={(e) => setGrosor(Number(e.target.value))} />}
        <button type="button" className="rounded bg-slate-100 px-2 py-1" onClick={limpiar}>Limpiar</button>
        {pantallaCompleta && <button type="button" className="rounded bg-slate-100 px-2 py-1" onClick={() => setCompleta((v) => !v)}>{completa ? 'Salir' : 'Pantalla completa'}</button>}
      </div>
      <canvas ref={canvas} width={800} height={completa ? 500 : 300} aria-label={etiqueta} className={`w-full touch-none rounded-lg border border-slate-300 bg-white ${completa ? 'flex-1' : 'max-w-lg'}`} style={{ touchAction: 'none' }}
              onPointerDown={(e) => { dibujando.current = true; const ctx = canvas.current!.getContext('2d')!; ctx.strokeStyle = color; ctx.lineWidth = grosor; ctx.lineCap = 'round'; ctx.beginPath(); const [x, y] = punto(e); ctx.moveTo(x, y); e.currentTarget.setPointerCapture(e.pointerId) }}
              onPointerMove={(e) => { if (!dibujando.current) return; const ctx = canvas.current!.getContext('2d')!; const [x, y] = punto(e); ctx.lineTo(x, y); ctx.stroke(); setTieneTrazo(true) }}
              onPointerUp={() => { dibujando.current = false }} />
      <button type="button" disabled={!tieneTrazo} className="rounded-lg bg-primario px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              onClick={async () => { alGuardar(await blobDeCanvas(canvas.current!), tieneTrazo); setCompleta(false) }}>{textoConfirmar}</button>
    </div>
  )
  return contenido
}

export function Firma({ campo, respuestaId, evidencias, onEvidencias, onChange, soloLectura }: PropsEvidencia) {
  const [error, setError] = useState<string | null>(null)
  const firma = evidencias.find((e) => e.tipo === 'firma')
  if (!respuestaId) return <SinRespuesta />
  if (firma) {
    return (
      <div className="flex items-center gap-3">
        <MiniaturaEvidencia evidencia={firma} respuestaId={respuestaId} />
        <div className="text-xs text-slate-600">
          <p>Firmado {new Date(firma.created_at ?? Date.now()).toLocaleString('es-MX')}</p>
          {!soloLectura && <button type="button" className="text-primario underline" onClick={() => void eliminarEvidencia(respuestaId, firma.id).then(() => onEvidencias(evidencias.filter((x) => x.id !== firma.id))).catch((e) => setError(mensajeDeError(e)))}>Firmar de nuevo</button>}
        </div>
        {error && <p className="text-xs text-red-700">{error}</p>}
      </div>
    )
  }
  if (soloLectura) return <p className="text-sm text-slate-500">Sin firma</p>
  return (
    <div>
      {campo.config.texto_conformidad && <p className="mb-2 text-sm text-slate-700">{campo.config.texto_conformidad}</p>}
      <Lienzo etiqueta={campo.etiqueta} pantallaCompleta={campo.config.pantalla_completa} textoConfirmar="Guardar firma" alGuardar={async (blob, tiene) => {
        if (!tiene) { setError('La firma no puede quedar vacía'); return }
        try {
          const e = await subirEvidencia(respuestaId, { archivo: blob, nombre: 'firma.png', campoClave: campo.clave })
          onEvidencias([...evidencias, e])
          onChange({ evidencia_id: e.id, timestamp: new Date().toISOString() })
        } catch (err) { setError(mensajeDeError(err)) }
      }} />
      {error && <p className="text-xs text-red-700" role="alert">{error}</p>}
    </div>
  )
}

export function Dibujo({ campo, respuestaId, evidencias, onEvidencias, soloLectura, todas }: PropsEvidencia) {
  const cfg = campo.config
  const [fondo, setFondo] = useState<string | null>(cfg.imagen_referencia?.tipo === 'url' ? cfg.imagen_referencia.valor : null)
  const [error, setError] = useState<string | null>(null)
  const dibujo = evidencias.find((e) => e.tipo === 'dibujo')
  const ref = cfg.imagen_referencia
  useEffect(() => {
    if (ref?.tipo === 'campo_fotografia' && respuestaId && ref.valor) {
      const foto = (todas?.[ref.valor] ?? []).find((e) => e.tipo === 'foto')
      if (foto) descargarEvidencia(respuestaId, foto.id).then((b) => setFondo(URL.createObjectURL(b))).catch(() => undefined)
    }
  }, [ref?.tipo, ref?.valor, respuestaId, todas])
  if (!respuestaId) return <SinRespuesta />
  if (dibujo) {
    return (
      <div className="flex items-center gap-3">
        <MiniaturaEvidencia evidencia={dibujo} respuestaId={respuestaId} />
        {!soloLectura && <button type="button" className="text-xs text-primario underline" onClick={() => void eliminarEvidencia(respuestaId, dibujo.id).then(() => onEvidencias(evidencias.filter((x) => x.id !== dibujo.id)))}>Dibujar de nuevo</button>}
      </div>
    )
  }
  if (soloLectura) return <p className="text-sm text-slate-500">Sin dibujo</p>
  return (
    <div>
      {ref?.tipo === 'campo_fotografia' && !fondo && <p className="mb-1 text-xs text-slate-500">Toma primero la foto «{ref.valor}» para usarla de fondo.</p>}
      <Lienzo etiqueta={campo.etiqueta} fondo={fondo} permitirColor={cfg.permitir_color} permitirGrosor={cfg.permitir_grosor} textoConfirmar="Guardar dibujo" alGuardar={async (blob) => {
        try { onEvidencias([...evidencias, await subirEvidencia(respuestaId, { archivo: blob, nombre: 'dibujo.png', campoClave: campo.clave })]) } catch (err) { setError(mensajeDeError(err)) }
      }} />
      {error && <p className="text-xs text-red-700" role="alert">{error}</p>}
    </div>
  )
}

// ------------------------------------------------------------------ Archivo

const ACCEPT: Record<string, string> = { pdf: '.pdf', imagen: 'image/*', hoja_calculo: '.xlsx,.xls,.csv', documento: '.pdf,.docx,.txt', cualquiera: '*/*' }

export function Archivo({ campo, respuestaId, evidencias, onEvidencias, soloLectura }: PropsEvidencia) {
  const cfg = campo.config
  const [error, setError] = useState<string | null>(null)
  const archivos = evidencias.filter((e) => e.tipo === 'archivo')
  if (!respuestaId) return <SinRespuesta />
  return (
    <div className="space-y-2">
      <ul className="space-y-1 text-sm">
        {archivos.map((a) => (
          <li key={a.id} className="flex items-center justify-between rounded border border-slate-200 px-3 py-1">
            <span>📎 {a.nombre_original} <span className="text-xs text-slate-500">({Math.round(a.bytes / 1024)} KB)</span></span>
            {!soloLectura && <button type="button" className="text-xs text-red-700" onClick={() => void eliminarEvidencia(respuestaId, a.id).then(() => onEvidencias(evidencias.filter((x) => x.id !== a.id)))}>Quitar</button>}
          </li>
        ))}
      </ul>
      {!soloLectura && archivos.length < (cfg.cantidad_max ?? 3) && (
        <label className="inline-block cursor-pointer rounded-lg border border-slate-300 px-4 py-2 text-sm">
          Adjuntar archivo (máx. {cfg.tamano_maximo_mb} MB)
          <input type="file" className="sr-only" aria-label={`Archivo de ${campo.etiqueta}`} accept={(cfg.tipos_permitidos ?? ['cualquiera']).map((t) => ACCEPT[t]).join(',')}
                 onChange={async (e) => {
                   const f = e.target.files?.[0]
                   e.target.value = ''
                   if (!f) return
                   if (f.size > (cfg.tamano_maximo_mb ?? 10) * 1024 * 1024) { setError(`El archivo excede ${cfg.tamano_maximo_mb} MB`); return }
                   try { onEvidencias([...evidencias, await subirEvidencia(respuestaId, { archivo: f, nombre: f.name, campoClave: campo.clave })]); setError(null) } catch (err) { setError(mensajeDeError(err)) }
                 }} />
        </label>
      )}
      {error && <p className="text-xs text-red-700" role="alert">{error}</p>}
    </div>
  )
}

// -------------------------------------------------------------------- Audio

export function Audio({ campo, respuestaId, evidencias, onEvidencias, soloLectura }: PropsEvidencia) {
  const cfg = campo.config
  const [grabando, setGrabando] = useState(false)
  const [segundos, setSegundos] = useState(0)
  const [pendiente, setPendiente] = useState<{ blob: Blob; url: string } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const grabador = useRef<MediaRecorder | null>(null)
  const trozos = useRef<Blob[]>([])
  const nota = evidencias.find((e) => e.tipo === 'audio')
  const maximo = cfg.duracion_maxima_seg ?? 120

  useEffect(() => {
    if (!grabando) return
    const t = setInterval(() => setSegundos((s) => { if (s + 1 >= maximo) detener(); return s + 1 }), 1000)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [grabando])

  async function grabar() {
    setError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mr = new MediaRecorder(stream)
      trozos.current = []
      mr.ondataavailable = (e) => trozos.current.push(e.data)
      mr.onstop = () => { stream.getTracks().forEach((t) => t.stop()); const blob = new Blob(trozos.current, { type: mr.mimeType || 'audio/webm' }); setPendiente({ blob, url: URL.createObjectURL(blob) }) }
      mr.start()
      grabador.current = mr
      setSegundos(0)
      setGrabando(true)
    } catch { setError('No se pudo acceder al micrófono') }
  }
  function detener() { grabador.current?.stop(); setGrabando(false) }

  if (!respuestaId) return <SinRespuesta />
  return (
    <div className="space-y-2 text-sm">
      {nota && (
        <div className="flex items-center gap-3">
          <span>🎤 Nota de voz guardada ({Math.round(nota.bytes / 1024)} KB)</span>
          {!!nota.anotaciones_json?.transcripcion && <span className="text-xs text-slate-500">Transcripción: {String((nota.anotaciones_json.transcripcion as { estado: string }).estado)}</span>}
          {!soloLectura && <button type="button" className="text-xs text-primario underline" onClick={() => void eliminarEvidencia(respuestaId, nota.id).then(() => onEvidencias(evidencias.filter((x) => x.id !== nota.id)))}>Volver a grabar</button>}
        </div>
      )}
      {!nota && !soloLectura && !pendiente && (
        grabando
          ? <button type="button" className="rounded-lg bg-red-600 px-4 py-2 text-white" onClick={detener}>■ Detener ({segundos}s / {maximo}s)</button>
          : <button type="button" className="rounded-lg bg-primario px-4 py-2 text-white" onClick={() => void grabar()}>● Grabar (máx. {maximo}s)</button>
      )}
      {pendiente && (
        <div className="space-y-2">
          <audio controls src={pendiente.url} className="w-full max-w-sm" />
          <div className="flex gap-2">
            <button type="button" className="rounded-lg bg-primario px-3 py-1.5 text-white" onClick={async () => {
              try { onEvidencias([...evidencias, await subirEvidencia(respuestaId, { archivo: pendiente.blob, nombre: 'nota.webm', campoClave: campo.clave })]); setPendiente(null) } catch (err) { setError(mensajeDeError(err)) }
            }}>Confirmar</button>
            <button type="button" className="rounded-lg border px-3 py-1.5" onClick={() => setPendiente(null)}>Volver a grabar</button>
          </div>
        </div>
      )}
      {error && <p className="text-xs text-red-700" role="alert">{error}</p>}
    </div>
  )
}

export type { Campo }
