/** Matriz 5×5 de §6.9.3, en sus dos usos: probabilidad × impacto de los activos y severidad × frecuencia de los
 * modos de falla. Se dibuja completa (las 25 celdas) aunque el backend solo devuelva las ocupadas, porque una
 * celda vacía también dice algo: ahí no hay riesgo. Al hacer clic en una celda se listan sus elementos. */
import { useState } from 'react'
import { Tarjeta } from '../ui'

export interface ElementoCelda { id: string; etiqueta: string; nota?: string }
export interface CeldaPlana { x: number; y: number; total: number; elementos: ElementoCelda[]; categoria?: string }

const FONDO: Record<string, string> = {
  bajo: 'bg-emerald-100 text-emerald-900', medio: 'bg-amber-100 text-amber-900',
  alto: 'bg-orange-200 text-orange-900', critico: 'bg-red-200 text-red-900',
}

export function MatrizInteractiva({ titulo, descripcion, etiquetaX, etiquetaY, celdas, categoriaDe, acciones }: {
  titulo: string
  descripcion: string
  /** Eje horizontal (impacto o frecuencia) y vertical (probabilidad o severidad), ambos 1–5. */
  etiquetaX: string
  etiquetaY: string
  celdas: CeldaPlana[]
  /** Color de la celda cuando el backend no manda categoría: el producto de los dos ejes. */
  categoriaDe: (x: number, y: number) => string
  acciones?: React.ReactNode
}) {
  const [abierta, setAbierta] = useState<string | null>(null)
  const por = new Map(celdas.map((c) => [`${c.y}x${c.x}`, c]))
  const seleccionada = abierta ? por.get(abierta) : undefined
  const niveles = [5, 4, 3, 2, 1]

  return (
    <Tarjeta titulo={titulo} acciones={acciones}>
      <p className="mb-3 text-sm text-slate-600">{descripcion}</p>
      <div className="overflow-x-auto">
        <table className="text-center text-sm">
          <caption className="sr-only">{`${titulo}: ${etiquetaY} contra ${etiquetaX}`}</caption>
          <thead>
            <tr>
              <th scope="col" className="px-2 py-1 text-xs font-medium text-slate-500">{`${etiquetaY} ↓ / ${etiquetaX} →`}</th>
              {[1, 2, 3, 4, 5].map((x) => (
                <th key={x} scope="col" className="w-20 px-2 py-1 text-xs font-medium text-slate-500">{x}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {niveles.map((y) => (
              <tr key={y}>
                <th scope="row" className="px-2 py-1 text-xs font-medium text-slate-500">{y}</th>
                {[1, 2, 3, 4, 5].map((x) => {
                  const clave = `${y}x${x}`
                  const celda = por.get(clave)
                  const categoria = celda?.categoria ?? categoriaDe(x, y)
                  const vacia = !celda || celda.total === 0
                  return (
                    <td key={x} className="p-0.5">
                      <button
                        type="button"
                        aria-label={`${etiquetaY} ${y}, ${etiquetaX} ${x}: ${celda?.total ?? 0}`}
                        aria-pressed={abierta === clave}
                        disabled={vacia}
                        onClick={() => setAbierta(abierta === clave ? null : clave)}
                        className={`h-12 w-full rounded-lg ${FONDO[categoria] ?? 'bg-slate-100 text-slate-700'} ${
                          vacia ? 'opacity-40' : 'cursor-pointer hover:ring-2 hover:ring-primario'} ${
                          abierta === clave ? 'ring-2 ring-primario' : ''}`}>
                        <span className="text-base font-semibold">{celda?.total ?? 0}</span>
                      </button>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {seleccionada && (
        <div className="mt-3 rounded-lg border border-slate-200 p-3">
          <p className="text-sm font-medium text-slate-700">
            {`${etiquetaY} ${seleccionada.y} · ${etiquetaX} ${seleccionada.x} · ${seleccionada.total} elemento(s)`}
          </p>
          <ul className="mt-1 space-y-1 text-sm text-slate-700">
            {seleccionada.elementos.map((e) => (
              <li key={e.id}>{e.etiqueta}{e.nota ? <span className="text-xs text-slate-500"> · {e.nota}</span> : null}</li>
            ))}
          </ul>
        </div>
      )}
    </Tarjeta>
  )
}
