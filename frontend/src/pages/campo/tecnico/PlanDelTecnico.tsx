import { useEffect, useState } from 'react'
import { Boton } from '../../../components/ui'
import { planDelFolio } from '../../../services/preventivos'
import { baseLocal } from '../../../services/db'
import { esSinConexion, syncEngine } from '../../../services/syncEngine'
import type { MaterialPlan, TareasMateriales } from '../../../types/preventivos'

const CLAVE = (folioId: string) => `plan.${folioId}`

/** Lista de verificación de las tareas del plan y materiales estándar precargados (app del técnico, operable sin conexión). */
export function PlanDelTecnico({ folioId, alUsarMaterial }: { folioId: string; alUsarMaterial: (m: MaterialPlan) => void }) {
  const [plan, setPlan] = useState<TareasMateriales | null>(null)
  const [hechas, setHechas] = useState<Record<string, boolean>>({})

  useEffect(() => {
    ;(async () => {
      let p: TareasMateriales | null = null
      if (syncEngine.enLinea()) {
        try {
          p = await planDelFolio(folioId)
          await baseLocal.metadatos.put({ clave: CLAVE(folioId), valor: p as unknown as Record<string, unknown>, actualizado: new Date().toISOString() })
        } catch (e) {
          if (!esSinConexion(e)) return
        }
      }
      if (!p) p = ((await baseLocal.metadatos.get(CLAVE(folioId)))?.valor as unknown as TareasMateriales | undefined) ?? null
      setPlan(p)
      const marcadas = (await baseLocal.metadatos.get(`${CLAVE(folioId)}.hechas`))?.valor as Record<string, boolean> | undefined
      if (marcadas) setHechas(marcadas)
    })()
  }, [folioId])

  if (!plan || (plan.tareas.length === 0 && plan.materiales.length === 0)) return null
  const total = plan.tareas.length
  const listas = plan.tareas.filter((t) => hechas[t.id ?? t.descripcion]).length

  async function marcar(clave: string, valor: boolean) {
    const nuevas = { ...hechas, [clave]: valor }
    setHechas(nuevas)
    await baseLocal.metadatos.put({ clave: `${CLAVE(folioId)}.hechas`, valor: nuevas, actualizado: new Date().toISOString() })
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4" data-testid="plan-tecnico">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-800">Tareas del plan</h2>
        <span className="text-xs text-slate-500">{listas}/{total} listas</span>
      </div>
      <ul className="mt-2 space-y-1">
        {plan.tareas.map((t) => {
          const clave = t.id ?? t.descripcion
          return (
            <li key={clave}>
              <label className="flex items-start gap-2 text-sm">
                <input type="checkbox" className="mt-1" checked={!!hechas[clave]} onChange={(e) => void marcar(clave, e.target.checked)} />
                <span className={hechas[clave] ? 'text-slate-400 line-through' : ''}>{t.orden ? `${t.orden}. ` : ''}{t.descripcion} <span className="text-xs text-slate-500">· {t.tiempo_estimado_min} min</span></span>
              </label>
            </li>
          )
        })}
      </ul>
      {plan.materiales.length > 0 && (
        <>
          <h3 className="mt-3 text-xs font-semibold uppercase text-slate-500">Materiales estándar</h3>
          <ul className="mt-1 space-y-1 text-sm">
            {plan.materiales.map((m) => (
              <li key={m.id ?? m.descripcion} className="flex items-center justify-between gap-2">
                <span>{m.cantidad_estandar} {m.unidad} · {m.descripcion}</span>
                <Boton variante="fantasma" className="px-2 py-1 text-xs" onClick={() => alUsarMaterial(m)}>Usar como refacción</Boton>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
