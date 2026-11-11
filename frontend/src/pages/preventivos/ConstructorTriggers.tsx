import { useEffect, useState } from 'react'
import { Aviso, Boton, Campo, Insignia, Selector } from '../../components/ui'
import { catalogoEventos, describirTriggerUso, tiposMedidor } from '../../services/medidores'
import type { EventoCatalogo, TipoMedidor } from '../../types/medidores'
import type { TipoTrigger, Trigger } from '../../types/preventivos'
import { TRIGGERS } from '../../types/preventivos'

const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
const SEVERIDADES = ['muy_baja', 'baja', 'media', 'alta', 'critica']

/** Clave estable de cada condición dentro del plan: `t1`, `t2`, … Es a lo que apunta el combinado. */
export function conClaves(triggers: Trigger[]): Trigger[] {
  return triggers.map((t, i) => ({ ...t, clave: t.clave || `t${i + 1}` }))
}

function parametrosPorDefecto(tipo: TipoTrigger, tipos: TipoMedidor[], eventos: EventoCatalogo[]): Record<string, unknown> {
  if (tipo === 'tiempo_fijo') return { cada_dias: 30 }
  if (tipo === 'calendario') return { mes: 1, dia: 15 }
  if (tipo === 'medidor_umbral') return { tipo_medidor_id: tipos[0]?.id ?? '', umbral: 500 }
  if (tipo === 'medidor_intervalo') return { tipo_medidor_id: tipos[0]?.id ?? '', intervalo: 10000 }
  if (tipo === 'evento') {
    const clave = eventos[0]?.clave ?? 'falla_correctiva_grave'
    return { evento: clave, ...(clave === 'falla_correctiva_grave' ? { severidades: ['alta', 'critica'] } : {}) }
  }
  return { triggers_claves: [], logica: 'OR' }
}

/**
 * Constructor de las condiciones de un plan (§6.9.1), en lenguaje claro: «Cada 10,000 ciclos desde el último
 * mantenimiento», «Cuando ocurra una falla correctiva grave», «90 días O 400 horas, lo que ocurra primero».
 *
 * Los seis tipos están activos desde F2-04. Una condición que forma parte de un combinado no dispara por sí sola:
 * la pantalla lo dice, porque es la diferencia entre «dos reglas» y «una regla con dos condiciones».
 */
export function ConstructorTriggers({ triggers, alCambiar }: { triggers: Trigger[]; alCambiar: (t: Trigger[]) => void }) {
  const [tipos, setTipos] = useState<TipoMedidor[]>([])
  const [eventos, setEventos] = useState<EventoCatalogo[]>([])
  useEffect(() => {
    void tiposMedidor({ solo_activos: true }).then(setTipos).catch(() => setTipos([]))
    void catalogoEventos().then(setEventos).catch(() => setEventos([]))
  }, [])

  const lista = conClaves(triggers)
  const claves: Record<string, string> = Object.fromEntries(lista.map((t) => [t.clave!, describirTriggerUso(t, tipos)]))
  const hijas = new Set(lista.filter((t) => t.tipo_trigger === 'combinado').flatMap((t) => (t.parametros_json.triggers_claves as string[]) ?? []))

  function cambiar(i: number, c: Partial<Trigger>) {
    alCambiar(lista.map((t, j) => (j === i ? { ...t, ...c } : t)))
  }
  function params(i: number, c: Record<string, unknown>) {
    cambiar(i, { parametros_json: { ...(lista[i]?.parametros_json ?? {}), ...c } })
  }

  return (
    <fieldset className="rounded-lg border border-slate-200 p-3" data-testid="constructor-triggers">
      <legend className="px-1 text-sm font-medium text-slate-700">Cuándo se ejecuta este plan ({lista.length})</legend>
      {lista.length === 0 && <p className="text-sm text-slate-500">Agrega al menos una condición.</p>}
      <div className="space-y-3">
        {lista.map((t, i) => {
          const p = t.parametros_json
          const esHija = hijas.has(t.clave!)
          return (
            <div key={t.clave ?? i} className={`rounded-lg border p-3 ${esHija ? 'border-dashed border-slate-300 bg-slate-50' : 'border-slate-200'}`} data-testid={`trigger-${t.clave}`}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <Insignia tono="acento">{t.clave}</Insignia>
                  <select aria-label={`Tipo de la condición ${t.clave}`} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
                    value={t.tipo_trigger}
                    onChange={(e) => {
                      const tipo = e.target.value as TipoTrigger
                      cambiar(i, { tipo_trigger: tipo, parametros_json: parametrosPorDefecto(tipo, tipos, eventos), logica_combinacion: tipo === 'combinado' ? 'OR' : null })
                    }}>
                    {TRIGGERS.map((x) => <option key={x.valor} value={x.valor}>{x.texto}</option>)}
                  </select>
                  {esHija && <span className="text-xs text-slate-500">es condición de un combinado: por sí sola no dispara</span>}
                </div>
                <Boton type="button" variante="fantasma" onClick={() => alCambiar(conClaves(lista.filter((_, j) => j !== i).map(({ clave: _c, ...r }) => r as Trigger)))}>Quitar</Boton>
              </div>

              <div className="mt-2">
                {t.tipo_trigger === 'tiempo_fijo' && (
                  <div className="flex flex-wrap items-end gap-2 text-sm">
                    <span className="pb-2">Cada</span>
                    {'cada_dias' in p ? (
                      <>
                        <Campo etiqueta="" aria-label={`Días de ${t.clave}`} type="number" min={1} className="w-24" value={String(p.cada_dias ?? 30)} onChange={(e) => params(i, { cada_dias: Number(e.target.value) })} />
                        <span className="pb-2">días</span>
                        <Boton type="button" variante="fantasma" onClick={() => params(i, { cada: 3, unidad: 'meses', cada_dias: undefined })}>usar semanas o meses</Boton>
                      </>
                    ) : (
                      <>
                        <Campo etiqueta="" aria-label={`Cantidad de ${t.clave}`} type="number" min={1} className="w-20" value={String(p.cada ?? 3)} onChange={(e) => params(i, { cada: Number(e.target.value) })} />
                        <Selector etiqueta="" aria-label={`Unidad de ${t.clave}`} value={String(p.unidad ?? 'meses')} onChange={(e) => params(i, { unidad: e.target.value })}
                          opciones={[{ valor: 'dias', texto: 'días' }, { valor: 'semanas', texto: 'semanas' }, { valor: 'meses', texto: 'meses' }]} />
                        <Boton type="button" variante="fantasma" onClick={() => params(i, { cada_dias: 30, cada: undefined, unidad: undefined })}>usar días</Boton>
                      </>
                    )}
                    <span className="pb-2 text-xs text-slate-500">desde la última ejecución</span>
                  </div>
                )}

                {t.tipo_trigger === 'calendario' && (
                  <div className="flex flex-wrap items-end gap-2 text-sm">
                    {'fechas' in p ? (
                      <>
                        <Campo etiqueta="Fechas (MM-DD o AAAA-MM-DD, separadas por coma)" value={((p.fechas as string[]) ?? []).join(', ')}
                          onChange={(e) => params(i, { fechas: e.target.value.split(/[,;\s]+/).filter(Boolean) })} />
                        <Boton type="button" variante="fantasma" onClick={() => params(i, { mes: 1, dia: 15, fechas: undefined })}>usar una fecha anual</Boton>
                      </>
                    ) : (
                      <>
                        <span className="pb-2">Cada</span>
                        <Campo etiqueta="" aria-label={`Día de ${t.clave}`} type="number" min={1} max={31} className="w-20" value={String(p.dia ?? 15)} onChange={(e) => params(i, { dia: Number(e.target.value) })} />
                        <span className="pb-2">de</span>
                        <Selector etiqueta="" aria-label={`Mes de ${t.clave}`} value={String(p.mes ?? 1)} onChange={(e) => params(i, { mes: Number(e.target.value) })}
                          opciones={MESES.map((m, k) => ({ valor: String(k + 1), texto: m }))} />
                        <Boton type="button" variante="fantasma" onClick={() => params(i, { fechas: [], mes: undefined, dia: undefined })}>usar una lista de fechas</Boton>
                      </>
                    )}
                  </div>
                )}

                {(t.tipo_trigger === 'medidor_umbral' || t.tipo_trigger === 'medidor_intervalo') && (
                  tipos.length === 0 ? (
                    <Aviso tipo="info">Todavía no hay tipos de medidor en el catálogo: créalos en el módulo de medidores y dale uno al equipo.</Aviso>
                  ) : (
                    <div className="flex flex-wrap items-end gap-2 text-sm">
                      <span className="pb-2">{t.tipo_trigger === 'medidor_umbral' ? 'Al llegar a' : 'Cada'}</span>
                      <Campo etiqueta="" aria-label={`Valor de ${t.clave}`} type="number" min={1} className="w-28"
                        value={String(t.tipo_trigger === 'medidor_umbral' ? (p.umbral ?? 500) : (p.intervalo ?? 10000))}
                        onChange={(e) => params(i, t.tipo_trigger === 'medidor_umbral' ? { umbral: Number(e.target.value) } : { intervalo: Number(e.target.value) })} />
                      <Selector etiqueta="" aria-label={`Medidor de ${t.clave}`} value={String(p.tipo_medidor_id ?? '')} onChange={(e) => params(i, { tipo_medidor_id: e.target.value })}
                        opciones={tipos.map((x) => ({ valor: x.id, texto: `${x.unidad} · ${x.nombre}` }))} />
                      <span className="pb-2 text-xs text-slate-500">
                        {t.tipo_trigger === 'medidor_umbral'
                          ? 'una sola vez: es un hito del equipo'
                          : 'desde el último mantenimiento de este plan'}
                      </span>
                    </div>
                  )
                )}

                {t.tipo_trigger === 'evento' && (
                  <div className="space-y-2 text-sm">
                    <Selector etiqueta="Cuando ocurra" value={String(p.evento ?? '')}
                      onChange={(e) => params(i, { ...parametrosPorDefecto('evento', tipos, eventos), evento: e.target.value, severidades: e.target.value === 'falla_correctiva_grave' ? ['alta', 'critica'] : undefined })}
                      opciones={eventos.map((x) => ({ valor: x.clave, texto: x.clave.replace(/_/g, ' ') }))} />
                    <p className="text-xs text-slate-600">{eventos.find((x) => x.clave === p.evento)?.descripcion}</p>
                    {p.evento === 'falla_correctiva_grave' && (
                      <div className="flex flex-wrap gap-2">
                        {SEVERIDADES.map((s) => (
                          <label key={s} className="flex items-center gap-1 text-sm">
                            <input type="checkbox" aria-label={s} checked={((p.severidades as string[]) ?? []).includes(s)}
                              onChange={(e) => params(i, { severidades: e.target.checked ? [...((p.severidades as string[]) ?? []), s] : ((p.severidades as string[]) ?? []).filter((x) => x !== s) })} />
                            {s.replace('_', ' ')}
                          </label>
                        ))}
                      </div>
                    )}
                    {p.evento === 'fallas_repetidas' && (
                      <div className="flex flex-wrap items-end gap-2">
                        <Campo etiqueta="Cuántas fallas" type="number" min={2} max={20} className="w-24" value={String(p.cantidad ?? 3)} onChange={(e) => params(i, { cantidad: Number(e.target.value) })} />
                        <Campo etiqueta="En cuántos días" type="number" min={1} max={365} className="w-24" value={String(p.dias ?? 30)} onChange={(e) => params(i, { dias: Number(e.target.value) })} />
                      </div>
                    )}
                    {p.evento === 'equipo_instalado' && (
                      <Campo etiqueta="Días después de la instalación" type="number" min={0} max={365} className="w-28" value={String(p.dias_despues ?? 30)} onChange={(e) => params(i, { dias_despues: Number(e.target.value) })} />
                    )}
                    {p.evento === 'reemplazo_componente' && (
                      <Campo etiqueta="Categorías de refacción (separadas por coma; vacío = cualquiera)" value={((p.categorias as string[]) ?? []).join(', ')}
                        onChange={(e) => params(i, { categorias: e.target.value.split(/[,;]+/).map((x) => x.trim()).filter(Boolean) })} />
                    )}
                    {p.evento === 'cambio_medidor' && (
                      <Selector etiqueta="Tipo de medidor (vacío = cualquiera)" value={String(p.tipo_medidor_id ?? '')} onChange={(e) => params(i, { tipo_medidor_id: e.target.value || undefined })}
                        opciones={[{ valor: '', texto: 'Cualquier medidor' }, ...tipos.map((x) => ({ valor: x.id, texto: x.nombre }))]} />
                    )}
                  </div>
                )}

                {t.tipo_trigger === 'combinado' && (
                  <div className="space-y-2 text-sm">
                    <Selector etiqueta="Lógica" value={String(p.logica ?? 'OR')} onChange={(e) => { params(i, { logica: e.target.value }); cambiar(i, { logica_combinacion: e.target.value }) }}
                      opciones={[{ valor: 'OR', texto: 'O (lo que ocurra primero)' }, { valor: 'AND', texto: 'Y (cuando se cumplan todas)' }]} />
                    <p className="text-xs text-slate-600">Elige las condiciones que se combinan (al menos dos):</p>
                    <div className="space-y-1">
                      {lista.filter((x) => x.clave !== t.clave && x.tipo_trigger !== 'combinado').map((x) => (
                        <label key={x.clave} className="flex items-start gap-2">
                          <input type="checkbox" aria-label={`Incluir ${x.clave}`} checked={((p.triggers_claves as string[]) ?? []).includes(x.clave!)}
                            onChange={(e) => params(i, {
                              triggers_claves: e.target.checked
                                ? [...((p.triggers_claves as string[]) ?? []), x.clave!]
                                : ((p.triggers_claves as string[]) ?? []).filter((c) => c !== x.clave),
                            })} />
                          <span><Insignia>{x.clave}</Insignia> {describirTriggerUso(x, tipos)}</span>
                        </label>
                      ))}
                    </div>
                    {((p.triggers_claves as string[]) ?? []).length < 2 && <Aviso tipo="info">Un combinado necesita dos condiciones o más.</Aviso>}
                  </div>
                )}
              </div>
              <p className="mt-2 text-xs text-slate-500" data-testid={`resumen-${t.clave}`}>{describirTriggerUso(t, tipos, claves)}</p>
            </div>
          )
        })}
      </div>
      <div className="mt-3">
        <Boton type="button" variante="secundario" onClick={() => alCambiar(conClaves([...lista, {
          tipo_trigger: 'tiempo_fijo', parametros_json: parametrosPorDefecto('tiempo_fijo', tipos, eventos), logica_combinacion: null,
        }]))}>+ Condición</Boton>
      </div>
    </fieldset>
  )
}
