import { useEffect, useMemo, useState } from 'react'
import type { Campo, Opcion, OpcionCatalogo } from '../../../types/formularios'

export interface PropsCampo {
  campo: Campo
  valor: unknown
  onChange: (v: unknown) => void
  opciones?: OpcionCatalogo[]
  aviso?: string | null
  soloLectura?: boolean
  calculado?: unknown
}

const CLASE_INPUT = 'w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-slate-900 outline-none focus:border-primario focus:ring-2 focus:ring-primario/20 disabled:bg-slate-50'

function opcionesDe(campo: Campo, remotas?: OpcionCatalogo[]): Opcion[] {
  if (campo.fuente_opciones?.origen === 'fija') return campo.fuente_opciones.opciones
  return (remotas ?? []).map((o) => ({ valor: o.valor, etiqueta: o.etiqueta, descripcion: o.descripcion ?? null, grupo: null, color: null }))
}

export function SiNo({ campo, valor, onChange, soloLectura }: PropsCampo) {
  const cfg = campo.config
  return (
    <div className="flex gap-2" role="group" aria-label={campo.etiqueta}>
      {[[true, cfg.etiqueta_si ?? 'Sí'], [false, cfg.etiqueta_no ?? 'No']].map(([v, texto]) => (
        <button key={String(v)} type="button" disabled={soloLectura} aria-pressed={valor === v} onClick={() => onChange(v)}
                className={`flex-1 rounded-lg border px-4 py-3 text-sm font-medium ${valor === v ? 'border-primario bg-primario text-white' : 'border-slate-300 bg-white text-slate-700 hover:bg-slate-50'}`}>
          {String(texto)}
        </button>
      ))}
    </div>
  )
}

export function Texto({ campo, valor, onChange, soloLectura }: PropsCampo) {
  const cfg = campo.config
  const comun = { id: campo.clave, name: campo.clave, disabled: soloLectura, value: (valor as string) ?? '', maxLength: cfg.longitud_max,
    placeholder: campo.tipo === 'texto_amplio' || campo.tipo === 'texto' ? (campo.valor_defecto as string) ?? '' : '' }
  if (campo.tipo === 'texto_amplio') {
    return <textarea {...comun} rows={cfg.lineas_visibles ?? 4} onChange={(e) => onChange(e.target.value)} className={CLASE_INPUT} />
  }
  const modo = cfg.formato === 'numeros' ? 'decimal' : 'text'
  return <input {...comun} type="text" inputMode={modo} onChange={(e) => onChange(e.target.value)} className={CLASE_INPUT} />
}

export function Radio({ campo, valor, onChange, opciones, soloLectura }: PropsCampo) {
  const lista = opcionesDe(campo, opciones)
  const horizontal = campo.config.disposicion === 'horizontal'
  return (
    <div role="radiogroup" aria-label={campo.etiqueta} className={horizontal ? 'flex flex-wrap gap-3' : 'space-y-2'}>
      {lista.map((o) => (
        <label key={o.valor} className={`flex cursor-pointer items-start gap-2 rounded-lg border px-3 py-2 text-sm ${valor === o.valor ? 'border-primario bg-primario/5' : 'border-slate-200'}`}>
          <input type="radio" name={campo.clave} value={o.valor} checked={valor === o.valor} disabled={soloLectura} onChange={() => onChange(o.valor)} className="mt-0.5" />
          <span><span className="font-medium">{o.etiqueta}</span>{o.descripcion && <span className="block text-xs text-slate-500">{o.descripcion}</span>}</span>
        </label>
      ))}
      {lista.length === 0 && <p className="text-xs text-slate-500">Sin opciones disponibles</p>}
    </div>
  )
}

export function BotonGrupo({ campo, valor, onChange, soloLectura }: PropsCampo) {
  const lista = campo.fuente_opciones?.origen === 'fija' ? campo.fuente_opciones.opciones : []
  const grande = campo.config.tamano !== 'normal'
  return (
    <div role="group" aria-label={campo.etiqueta} className="grid gap-2" style={{ gridTemplateColumns: `repeat(${Math.min(lista.length, 5)}, minmax(0, 1fr))` }}>
      {lista.map((o) => {
        const activo = valor === o.valor
        return (
          <button key={o.valor} type="button" disabled={soloLectura} aria-pressed={activo} onClick={() => onChange(o.valor)}
                  className={`rounded-xl border-2 font-semibold text-white transition ${grande ? 'px-3 py-5 text-base' : 'px-3 py-2 text-sm'} ${activo ? 'ring-4 ring-offset-2' : 'opacity-80 hover:opacity-100'}`}
                  style={{ background: o.color ?? '#64748b', borderColor: o.color ?? '#64748b', ...(activo ? { ['--tw-ring-color' as string]: o.color ?? '#64748b' } : {}) }}>
            {o.etiqueta}
          </button>
        )
      })}
    </div>
  )
}

export function ListaDesplegable({ campo, valor, onChange, opciones, aviso, soloLectura }: PropsCampo) {
  const lista = opcionesDe(campo, opciones)
  const multiple = campo.config.seleccion === 'multiple'
  const [q, setQ] = useState('')
  const filtradas = useMemo(() => (q ? lista.filter((o) => o.etiqueta.toLowerCase().includes(q.toLowerCase())) : lista), [lista, q])
  const seleccion = multiple ? ((valor as string[]) ?? []) : valor ? [valor as string] : []
  return (
    <div className="space-y-2">
      {campo.config.busqueda && lista.length > 6 && (
        <input type="search" aria-label={`Buscar en ${campo.etiqueta}`} placeholder="Escribe para filtrar…" value={q} onChange={(e) => setQ(e.target.value)} className={CLASE_INPUT} disabled={soloLectura} />
      )}
      {multiple ? (
        <div className="max-h-56 space-y-1 overflow-y-auto rounded-lg border border-slate-200 p-2">
          {filtradas.map((o) => (
            <label key={o.valor} className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={seleccion.includes(o.valor)} disabled={soloLectura}
                     onChange={(e) => onChange(e.target.checked ? [...seleccion, o.valor] : seleccion.filter((x) => x !== o.valor))} />
              {o.etiqueta}
            </label>
          ))}
        </div>
      ) : (
        <select id={campo.clave} name={campo.clave} value={(valor as string) ?? ''} disabled={soloLectura} onChange={(e) => onChange(e.target.value || null)} className={CLASE_INPUT}>
          <option value="">Selecciona…</option>
          {filtradas.map((o) => <option key={o.valor} value={o.valor}>{o.etiqueta}</option>)}
        </select>
      )}
      {aviso && <p className="text-xs text-amber-700">{aviso}</p>}
    </div>
  )
}

export function OpcionMultiple({ campo, valor, onChange, opciones, aviso, soloLectura }: PropsCampo) {
  const lista = opcionesDe(campo, opciones)
  const cfg = campo.config
  const contador = campo.tipo === 'seleccion_multiple' && cfg.contador_por_opcion
  const seleccion = ((valor as unknown[]) ?? []).map((x) => (typeof x === 'object' && x !== null ? (x as { valor: string; cantidad?: number }) : { valor: String(x), cantidad: 1 }))
  const grupos = cfg.grupos_colapsables ? [...new Set(lista.map((o) => o.grupo ?? 'General'))] : [null]
  const [colapsados, setColapsados] = useState<Set<string>>(new Set())

  const emitir = (nuevo: { valor: string; cantidad?: number }[]) => onChange(contador ? nuevo : nuevo.map((x) => x.valor))
  const alternar = (v: string, marcado: boolean) => emitir(marcado ? [...seleccion, { valor: v, cantidad: cfg.contador_min ?? 1 }] : seleccion.filter((x) => x.valor !== v))
  const cantidad = (v: string, n: number) => emitir(seleccion.map((x) => (x.valor === v ? { ...x, cantidad: n } : x)))

  return (
    <div className="space-y-2">
      {cfg.plantillas_combinaciones && cfg.plantillas_combinaciones.length > 0 && !soloLectura && (
        <div className="flex flex-wrap gap-1">
          {cfg.plantillas_combinaciones.map((p) => (
            <button key={p.nombre} type="button" className="rounded-full bg-acento/30 px-3 py-1 text-xs font-medium text-slate-800 hover:bg-acento/50"
                    onClick={() => emitir(p.valores.map((v) => ({ valor: v, cantidad: p.cantidades?.[v] ?? cfg.contador_min ?? 1 })))}>
              {p.nombre}
            </button>
          ))}
        </div>
      )}
      {grupos.map((g) => {
        const del = g === null ? lista : lista.filter((o) => (o.grupo ?? 'General') === g)
        const cerrado = g !== null && colapsados.has(g)
        return (
          <div key={g ?? 'todo'} className={g ? 'rounded-lg border border-slate-200' : ''}>
            {g && (
              <button type="button" className="flex w-full items-center justify-between px-3 py-2 text-sm font-medium" aria-expanded={!cerrado}
                      onClick={() => setColapsados((s) => { const n = new Set(s); if (n.has(g)) n.delete(g); else n.add(g); return n })}>
                {g} <span>{cerrado ? '▸' : '▾'}</span>
              </button>
            )}
            {!cerrado && (
              <div className={`space-y-1 ${g ? 'px-3 pb-2' : ''}`}>
                {del.map((o) => {
                  const sel = seleccion.find((x) => x.valor === o.valor)
                  return (
                    <div key={o.valor} className="flex items-center gap-2 text-sm">
                      <label className="flex flex-1 items-center gap-2">
                        <input type="checkbox" checked={!!sel} disabled={soloLectura} onChange={(e) => alternar(o.valor, e.target.checked)} />
                        {o.etiqueta}
                      </label>
                      {contador && sel && (
                        <input type="number" aria-label={`Cantidad ${o.etiqueta}`} min={cfg.contador_min ?? 1} max={cfg.contador_max ?? undefined} value={sel.cantidad ?? 1}
                               disabled={soloLectura} onChange={(e) => cantidad(o.valor, Number(e.target.value))} className="w-20 rounded border border-slate-300 px-2 py-1" />
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )
      })}
      {aviso && <p className="text-xs text-amber-700">{aviso}</p>}
    </div>
  )
}

export function Slider({ campo, valor, onChange, soloLectura }: PropsCampo) {
  const cfg = campo.config
  const min = cfg.minimo ?? 0
  const max = cfg.maximo ?? 10
  const paso = cfg.incremento ?? 1
  if (cfg.modo_rango) {
    const [a, b] = (Array.isArray(valor) && valor.length === 2 ? (valor as [number, number]) : [min, max]) as [number, number]
    return (
      <div className="space-y-1">
        <div className="flex items-center gap-3 text-sm">
          <span className="w-16 text-slate-500">{cfg.etiqueta_min ?? min}</span>
          <input type="range" aria-label={`${campo.etiqueta} desde`} min={min} max={max} step={paso} value={a} disabled={soloLectura} onChange={(e) => onChange([Math.min(Number(e.target.value), b), b])} className="flex-1" />
          <input type="range" aria-label={`${campo.etiqueta} hasta`} min={min} max={max} step={paso} value={b} disabled={soloLectura} onChange={(e) => onChange([a, Math.max(Number(e.target.value), a)])} className="flex-1" />
          <span className="w-16 text-right text-slate-500">{cfg.etiqueta_max ?? max}</span>
        </div>
        <p className="text-center text-sm font-semibold text-primario">{a} – {b}</p>
      </div>
    )
  }
  const v = typeof valor === 'number' ? valor : min
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-3 text-sm">
        <span className="w-16 text-slate-500">{cfg.etiqueta_min ?? min}</span>
        <input type="range" id={campo.clave} aria-label={campo.etiqueta} min={min} max={max} step={paso} value={v} disabled={soloLectura} onChange={(e) => onChange(Number(e.target.value))} className="flex-1" />
        <span className="w-16 text-right text-slate-500">{cfg.etiqueta_max ?? max}</span>
      </div>
      <p className="text-center text-lg font-semibold text-primario">{valor === undefined || valor === null ? '—' : String(v)}</p>
    </div>
  )
}

export function Encuesta({ campo, valor, onChange, soloLectura }: PropsCampo) {
  const cfg = campo.config
  const n = cfg.escala_max ?? 5
  const simbolo = (i: number) => (cfg.modalidad === 'emojis' ? (n === 3 ? ['😞', '😐', '😊'] : ['😡', '😞', '😐', '🙂', '😄'])[i - 1] : cfg.modalidad === 'numerica' ? String(i) : '★')
  return (
    <div>
      <div className="flex flex-wrap gap-1" role="radiogroup" aria-label={campo.etiqueta}>
        {Array.from({ length: n }, (_, i) => i + 1).map((i) => (
          <button key={i} type="button" role="radio" aria-checked={valor === i} aria-label={`${i} de ${n}`} disabled={soloLectura} onClick={() => onChange(i)}
                  className={`h-10 min-w-10 rounded-lg px-2 text-xl ${cfg.modalidad === 'estrellas' ? (typeof valor === 'number' && i <= valor ? 'text-amber-400' : 'text-slate-300') : valor === i ? 'bg-primario text-white' : 'bg-slate-100 text-slate-700'}`}>
            {simbolo(i)}
          </button>
        ))}
      </div>
      {(cfg.etiqueta_min || cfg.etiqueta_max) && <div className="mt-1 flex justify-between text-xs text-slate-500"><span>{cfg.etiqueta_min}</span><span>{cfg.etiqueta_max}</span></div>}
    </div>
  )
}

export function FechaHora({ campo, valor, onChange, soloLectura }: PropsCampo) {
  const cfg = campo.config
  const tipo = { fecha: 'date', hora: 'time', ambos: 'datetime-local' }[cfg.modo ?? 'ambos']
  useEffect(() => {
    if ((valor === undefined || valor === null) && cfg.defecto_hoy_mas_dias != null && !soloLectura) {
      const d = new Date()
      d.setDate(d.getDate() + cfg.defecto_hoy_mas_dias)
      const fecha = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
      onChange(cfg.modo === 'fecha' ? fecha : `${fecha}T${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return <input id={campo.clave} name={campo.clave} type={tipo} value={(valor as string) ?? ''} disabled={soloLectura} step={cfg.modo !== 'fecha' && cfg.intervalo_minutos ? cfg.intervalo_minutos * 60 : undefined}
                onChange={(e) => onChange(e.target.value || null)} className={CLASE_INPUT} />
}

export function EtiquetaInfo({ campo }: PropsCampo) {
  const cfg = campo.config
  const icono = { ninguno: '', info: 'ℹ️', advertencia: '⚠️', peligro: '⛔' }[cfg.icono ?? 'ninguno']
  const tono = { ninguno: 'bg-slate-50 border-slate-200', info: 'bg-blue-50 border-blue-200', advertencia: 'bg-amber-50 border-amber-200', peligro: 'bg-red-50 border-red-200' }[cfg.icono ?? 'ninguno']
  const lineas = (cfg.contenido ?? '').split('\n')
  const render = (t: string) => t.split(/(\*\*[^*]+\*\*)/g).map((p, i) => (p.startsWith('**') ? <strong key={i}>{p.slice(2, -2)}</strong> : p))
  return (
    <div className={`rounded-lg border px-4 py-3 text-sm text-slate-800 ${tono}`} role="note">
      {icono && <span className="mr-2">{icono}</span>}
      {lineas.map((l, i) => (l.startsWith('- ') ? <li key={i} className="ml-5 list-disc">{render(l.slice(2))}</li> : <p key={i} className="inline">{render(l)} </p>))}
      {cfg.enlace && <a href={cfg.enlace.url} target="_blank" rel="noreferrer" className="ml-1 text-primario underline">{cfg.enlace.texto}</a>}
    </div>
  )
}

/** Campos calculados por el servidor: solo lectura con el valor recalculado localmente como vista previa. */
export function Calculado({ campo, calculado }: PropsCampo) {
  let texto = '—'
  if (calculado !== null && calculado !== undefined) {
    if (typeof calculado === 'object' && calculado !== null && 'texto' in calculado) texto = String((calculado as { texto: unknown }).texto)
    else if (campo.tipo === 'sello_fecha_hora') texto = String(calculado).replace('T', ' ').slice(0, 19)
    else texto = String(calculado)
  }
  const nota = { concatenacion: 'Se genera automáticamente', matematicas_tiempo: 'Se calcula automáticamente', sello_fecha_hora: { al_abrir: 'Al abrir el formulario', al_enviar: 'Al enviar', al_llegar_seccion: 'Al llegar a esta sección', por_condicion: 'Al activarse' }[campo.config.trigger ?? 'al_enviar'] }[campo.tipo as 'concatenacion' | 'matematicas_tiempo' | 'sello_fecha_hora']
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-3 py-2">
      <p className="font-mono text-sm text-slate-800" data-testid={`calculado-${campo.clave}`}>{texto}</p>
      <p className="text-xs text-slate-500">{nota}</p>
    </div>
  )
}
