import { forwardRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from 'react'
import { IconoAcma } from './IconosAcma'

type Variante = 'primario' | 'secundario' | 'peligro' | 'fantasma'

const ESTILOS: Record<Variante, string> = {
  primario: 'bg-primario text-white shadow-sm hover:brightness-110 hover:shadow-md',
  secundario: 'bg-white text-primario border border-primario/30 hover:bg-primario/5',
  peligro: 'bg-red-600 text-white hover:bg-red-700',
  fantasma: 'text-slate-600 hover:bg-slate-100',
}

export function Boton({ variante = 'primario', className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variante?: Variante }) {
  return (
    <button
      className={`inline-flex min-h-11 max-w-full items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold transition-[background-color,box-shadow,transform,filter] duration-200 active:scale-[.99] disabled:cursor-not-allowed disabled:opacity-50 ${ESTILOS[variante]} ${className}`}
      {...props}
    />
  )
}

interface PropsCampo extends InputHTMLAttributes<HTMLInputElement> {
  etiqueta: string
  error?: string | undefined
}

export const Campo = forwardRef<HTMLInputElement, PropsCampo>(function Campo({ etiqueta, error, id, ...props }, ref) {
  const idCampo = id ?? props.name
  return (
    <label className="block text-sm" htmlFor={idCampo}>
      <span className="mb-1 block font-medium text-slate-700">{etiqueta}</span>
      <input
        ref={ref}
        id={idCampo}
        aria-invalid={error ? true : undefined}
        className="min-h-11 w-full min-w-0 rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-base text-slate-900 shadow-sm sm:text-sm outline-none transition focus:border-primario focus:ring-[3px] focus:ring-primario/10"
        {...props}
      />
      {error && <span className="mt-1 block text-xs text-red-600">{error}</span>}
    </label>
  )
})

interface PropsSelector extends SelectHTMLAttributes<HTMLSelectElement> {
  etiqueta: string
  opciones: { valor: string; texto: string }[]
  error?: string | undefined
}

export const Selector = forwardRef<HTMLSelectElement, PropsSelector>(function Selector({ etiqueta, opciones, error, id, ...props }, ref) {
  const idCampo = id ?? props.name
  return (
    <label className="block text-sm" htmlFor={idCampo}>
      <span className="mb-1 block font-medium text-slate-700">{etiqueta}</span>
      <select
        ref={ref}
        id={idCampo}
        className="min-h-11 w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-slate-900 shadow-sm outline-none transition focus:border-primario focus:ring-[3px] focus:ring-primario/10"
        {...props}
      >
        {opciones.map((o) => (
          <option key={o.valor} value={o.valor}>
            {o.texto}
          </option>
        ))}
      </select>
      {error && <span className="mt-1 block text-xs text-red-600">{error}</span>}
    </label>
  )
})

export function Aviso({ tipo = 'error', children }: { tipo?: 'error' | 'exito' | 'info'; children: ReactNode }) {
  const color = { error: 'bg-red-50 text-red-800 border-red-200', exito: 'bg-green-50 text-green-800 border-green-200', info: 'bg-blue-50 text-blue-800 border-blue-200' }[tipo]
  return (
    <div role={tipo === 'error' ? 'alert' : 'status'} className={`rounded-xl border px-4 py-3 text-sm leading-relaxed ${color}`}>
      {children}
    </div>
  )
}

export function Tarjeta({ titulo, acciones, children }: { titulo?: string; acciones?: ReactNode; children: ReactNode }) {
  return (
    <section className="min-w-0 rounded-2xl border border-slate-200/90 bg-white p-4 shadow-[0_4px_18px_rgba(15,23,42,.045)] sm:p-6">
      {(titulo || acciones) && (
        <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
          {titulo && <h2 className="text-base font-semibold text-slate-900">{titulo}</h2>}
          {acciones}
        </header>
      )}
      {children}
    </section>
  )
}

export function Insignia({ children, tono = 'neutro' }: { children: ReactNode; tono?: 'neutro' | 'ok' | 'alerta' | 'acento' }) {
  const color = { neutro: 'bg-slate-100 text-slate-700', ok: 'bg-green-100 text-green-800', alerta: 'bg-amber-100 text-amber-800', acento: 'bg-acento/20 text-slate-800' }[tono]
  return <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${color}`}>{children}</span>
}

export interface Columna<T> {
  titulo: string
  celda: (fila: T) => ReactNode
}

export function Tabla<T extends { id: string }>({ columnas, filas, vacio = 'Sin registros' }: { columnas: Columna<T>[]; filas: T[]; vacio?: string }) {
  return (
    <div className="min-w-0 max-w-full overflow-x-auto">
      <table className="acma-tabla w-full text-left text-sm">
        <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            {columnas.map((c) => (
              <th key={c.titulo} className="px-3 py-2 font-medium">
                {c.titulo}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {filas.length === 0 ? (
            <tr className="acma-tabla-vacia">
              <td colSpan={columnas.length} className="px-3 py-6 text-center text-slate-500">
                {vacio}
              </td>
            </tr>
          ) : (
            filas.map((f) => (
              <tr key={f.id} className="hover:bg-slate-50">
                {columnas.map((c) => (
                  <td key={c.titulo} data-label={c.titulo} className="px-3 py-2 align-top text-slate-800">
                    {c.celda(f)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}

export function Modal({ titulo, abierto, alCerrar, children }: { titulo: string; abierto: boolean; alCerrar: () => void; children: ReactNode }) {
  if (!abierto) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-slate-900/50 px-2 py-4 sm:px-4" onClick={alCerrar}>
      <div role="dialog" aria-modal="true" aria-label={titulo} className="my-auto max-h-[calc(100dvh-2rem)] w-full max-w-lg overflow-y-auto overscroll-contain rounded-2xl border border-slate-200 bg-white p-4 shadow-[0_24px_60px_rgba(15,23,42,.18)] sm:p-6" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900">{titulo}</h2>
          <button aria-label="Cerrar" className="rounded p-1 text-slate-500 hover:bg-slate-100" onClick={alCerrar}>
            <IconoAcma nombre="cerrar" className="h-5 w-5" />
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}

export function Encabezado({ titulo, descripcion, acciones }: { titulo: string; descripcion?: string; acciones?: ReactNode }) {
  return (
    <div className="mb-5 flex w-full min-w-0 flex-wrap items-start justify-between gap-3 sm:mb-6 sm:items-end">
      <div>
        <h1 className="max-w-full break-words text-xl font-extrabold tracking-tight text-[#172d47] sm:text-2xl">{titulo}</h1>
        {descripcion && <p className="mt-1 max-w-full break-words text-sm text-slate-600">{descripcion}</p>}
      </div>
      {acciones}
    </div>
  )
}
