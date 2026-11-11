import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { Aviso, Boton, Campo, Encabezado, Insignia, Modal, Selector, Tabla, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { useRecurso } from '../../hooks/useRecurso'
import { api, mensajeDeError } from '../../services/api'
import { asignarPlanAEquipo, crearPlan, describirTrigger, editarPlan, quitarPlanDeEquipo } from '../../services/preventivos'
import type { Equipo, Habilidad, TipoEquipo } from '../../types/api'
import type { Formulario } from '../../types/formularios'
import { simularPlan } from '../../services/medidores'
import type { FilaSimulacion } from '../../types/medidores'
import type { MaterialPlan, Plan, PlanEntrada, TareaPlan, Trigger } from '../../types/preventivos'
import { ROLES_PLANES } from '../../types/preventivos'
import { ConstructorTriggers, conClaves } from './ConstructorTriggers'

type Borrador = { nombre: string; descripcion: string; tipo_equipo_id: string; tiempo_ventana_dias: string; formulario_id: string; estado: 'activo' | 'inactivo'
  triggers: Trigger[]; tareas: TareaPlan[]; materiales: MaterialPlan[] }

const VACIO: Borrador = { nombre: '', descripcion: '', tipo_equipo_id: '', tiempo_ventana_dias: '7', formulario_id: '', estado: 'activo',
  triggers: [{ clave: 't1', tipo_trigger: 'tiempo_fijo', parametros_json: { cada_dias: 30 }, logica_combinacion: null }], tareas: [], materiales: [] }

/**
 * Planes de mantenimiento (§6.9.1): los seis triggers (tiempo fijo, calendario, medidor por umbral, medidor por
 * intervalo, evento del catálogo cerrado y combinados O/Y), tareas con habilidad, materiales, equipos y la
 * simulación de cuándo se dispararía con las lecturas actuales.
 */
export function Planes() {
  const { usuario } = useAuth()
  const puedeEditar = !!usuario && ROLES_PLANES.includes(usuario.rol)
  const { datos, error, recargar } = useRecurso<Plan[]>('/planes')
  const [editando, setEditando] = useState<Plan | 'nuevo' | null>(null)
  const [seleccionado, setSeleccionado] = useState<Plan | null>(null)
  const planes = datos ?? []

  return (
    <div>
      <Encabezado
        titulo="Planes de mantenimiento"
        descripcion="Cada plan define cuándo se ejecuta —por tiempo, por calendario, por lo que marca un medidor, cuando ocurre un evento, o combinando condiciones con «lo que ocurra primero»—, la ventana de ejecución, las tareas con su habilidad requerida y los materiales estándar. Los folios preventivos nacen solos, en Autorizado: con una lectura que cruza el umbral, en el momento; por fecha, en la tarea nocturna."
        acciones={<div className="flex gap-2"><Link to="/preventivos/calendario"><Boton variante="secundario">Calendario</Boton></Link>{puedeEditar && <Boton onClick={() => setEditando('nuevo')}>Nuevo plan</Boton>}</div>}
      />
      {error && <div className="mb-3"><Aviso>{error}</Aviso></div>}
      <div className="rounded-xl border border-slate-200 bg-white p-2">
        <Tabla
          filas={planes}
          vacio="Sin planes"
          columnas={[
            { titulo: 'Plan', celda: (p) => <button className="text-left font-medium text-primario underline" onClick={() => setSeleccionado(p)}>{p.nombre}</button> },
            { titulo: 'Tipo de equipo', celda: (p) => p.tipo_equipo_nombre ?? '—' },
            { titulo: 'Cuándo', celda: (p) => <span className="text-xs">{p.triggers.map((t) => describirTrigger(t)).join(' · ') || '—'}</span> },
            { titulo: 'Ventana', celda: (p) => `${p.tiempo_ventana_dias} días` },
            { titulo: 'Tareas / materiales', celda: (p) => `${p.tareas.length} / ${p.materiales.length}` },
            { titulo: 'Equipos', celda: (p) => String(p.equipos.filter((e) => e.activo).length) },
            { titulo: 'Estado', celda: (p) => <Insignia tono={p.estado === 'activo' ? 'ok' : 'neutro'}>{p.estado} · v{p.version}</Insignia> },
            { titulo: '', celda: (p) => puedeEditar ? <Boton variante="fantasma" onClick={() => setEditando(p)}>Editar</Boton> : null },
          ]}
        />
      </div>
      {seleccionado && <DetallePlan plan={seleccionado} puedeEditar={puedeEditar} alCerrar={() => setSeleccionado(null)} alCambiar={async () => { await recargar(); setSeleccionado(null) }} />}
      {editando && <EditorPlan plan={editando === 'nuevo' ? null : editando} alCerrar={() => setEditando(null)} alGuardar={async () => { setEditando(null); await recargar() }} />}
    </div>
  )
}

function EditorPlan({ plan, alCerrar, alGuardar }: { plan: Plan | null; alCerrar: () => void; alGuardar: () => Promise<void> }) {
  const [b, setB] = useState<Borrador>(plan ? { nombre: plan.nombre, descripcion: plan.descripcion, tipo_equipo_id: plan.tipo_equipo_id, tiempo_ventana_dias: String(plan.tiempo_ventana_dias), formulario_id: plan.formulario_id ?? '', estado: plan.estado, triggers: conClaves(plan.triggers), tareas: plan.tareas, materiales: plan.materiales } : VACIO)
  const [error, setError] = useState<string | null>(null)
  const tipos = useRecurso<TipoEquipo[]>('/catalogos/tipos-equipo')
  const habilidades = useRecurso<Habilidad[]>('/catalogos/habilidades')
  const formularios = useRecurso<Formulario[]>('/formularios', { tipo: 'preventivo' })

  async function guardar() {
    setError(null)
    try {
      const datos: PlanEntrada = { nombre: b.nombre, descripcion: b.descripcion, tipo_equipo_id: b.tipo_equipo_id, tiempo_ventana_dias: Number(b.tiempo_ventana_dias), formulario_id: b.formulario_id || null, estado: b.estado,
        triggers: conClaves(b.triggers), tareas: b.tareas.map((x, i) => ({ ...x, orden: i + 1, tiempo_estimado_min: Number(x.tiempo_estimado_min) || 0, habilidad_requerida_id: x.habilidad_requerida_id || null })),
        materiales: b.materiales.map((m) => ({ ...m, articulo_id: null, cantidad_estandar: String(m.cantidad_estandar || '1') })) }
      if (plan) await editarPlan(plan.id, datos)
      else await crearPlan(datos)
      await alGuardar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }
  return (
    <Modal titulo={plan ? `Editar plan (v${plan.version} → v${plan.version + 1})` : 'Nuevo plan de mantenimiento'} abierto alCerrar={alCerrar}>
      {error && <div className="mb-3"><Aviso>{error}</Aviso></div>}
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); void guardar() }}>
        <div className="grid gap-3 sm:grid-cols-2">
          <Campo etiqueta="Nombre" value={b.nombre} onChange={(e) => setB({ ...b, nombre: e.target.value })} required minLength={2} />
          <Selector etiqueta="Tipo de equipo" value={b.tipo_equipo_id} onChange={(e) => setB({ ...b, tipo_equipo_id: e.target.value })} required
                    opciones={[{ valor: '', texto: 'Elegir…' }, ...(tipos.datos ?? []).map((x) => ({ valor: x.id, texto: x.nombre }))]} />
          <Campo etiqueta="Ventana de ejecución (días)" type="number" min={0} max={365} value={b.tiempo_ventana_dias} onChange={(e) => setB({ ...b, tiempo_ventana_dias: e.target.value })} />
          <Selector etiqueta="Formulario preventivo" value={b.formulario_id} onChange={(e) => setB({ ...b, formulario_id: e.target.value })}
                    opciones={[{ valor: '', texto: 'Resolver por tipo de equipo' }, ...(formularios.datos ?? []).map((f) => ({ valor: f.id, texto: f.nombre }))]} />
          <Campo etiqueta="Descripción" value={b.descripcion} onChange={(e) => setB({ ...b, descripcion: e.target.value })} />
          {plan && <Selector etiqueta="Estado" value={b.estado} onChange={(e) => setB({ ...b, estado: e.target.value as 'activo' | 'inactivo' })} opciones={[{ valor: 'activo', texto: 'Activo' }, { valor: 'inactivo', texto: 'Inactivo' }]} />}
        </div>

        <ConstructorTriggers triggers={b.triggers} alCambiar={(triggers) => setB({ ...b, triggers })} />

        <fieldset className="rounded-lg border border-slate-200 p-3">
          <legend className="px-1 text-sm font-medium text-slate-700">Tareas ({b.tareas.length})</legend>
          {b.tareas.map((x, i) => (
            <div key={i} className="mb-2 grid gap-2 sm:grid-cols-[1fr_6rem_1fr_auto]">
              <input aria-label={`Tarea ${i + 1}`} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm" placeholder="Descripción" value={x.descripcion} onChange={(e) => setB({ ...b, tareas: b.tareas.map((y, j) => (j === i ? { ...y, descripcion: e.target.value } : y)) })} />
              <input aria-label={`Minutos tarea ${i + 1}`} type="number" min={0} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm" value={x.tiempo_estimado_min} onChange={(e) => setB({ ...b, tareas: b.tareas.map((y, j) => (j === i ? { ...y, tiempo_estimado_min: Number(e.target.value) } : y)) })} />
              <select aria-label={`Habilidad tarea ${i + 1}`} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm" value={x.habilidad_requerida_id ?? ''} onChange={(e) => setB({ ...b, tareas: b.tareas.map((y, j) => (j === i ? { ...y, habilidad_requerida_id: e.target.value || null } : y)) })}>
                <option value="">Sin habilidad específica</option>
                {(habilidades.datos ?? []).map((h) => <option key={h.id} value={h.id}>{h.nombre}</option>)}
              </select>
              <Boton type="button" variante="fantasma" onClick={() => setB({ ...b, tareas: b.tareas.filter((_, j) => j !== i) })}>Quitar</Boton>
            </div>
          ))}
          <Boton type="button" variante="secundario" onClick={() => setB({ ...b, tareas: [...b.tareas, { orden: b.tareas.length + 1, descripcion: '', tiempo_estimado_min: 15, habilidad_requerida_id: null }] })}>+ Tarea</Boton>
        </fieldset>

        <fieldset className="rounded-lg border border-slate-200 p-3">
          <legend className="px-1 text-sm font-medium text-slate-700">Materiales estándar ({b.materiales.length})</legend>
          {b.materiales.map((m, i) => (
            <div key={i} className="mb-2 grid gap-2 sm:grid-cols-[1fr_6rem_6rem_auto]">
              <input aria-label={`Material ${i + 1}`} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm" placeholder="Descripción" value={m.descripcion} onChange={(e) => setB({ ...b, materiales: b.materiales.map((y, j) => (j === i ? { ...y, descripcion: e.target.value } : y)) })} />
              <input aria-label={`Cantidad material ${i + 1}`} type="number" min={0.01} step="0.01" className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm" value={m.cantidad_estandar} onChange={(e) => setB({ ...b, materiales: b.materiales.map((y, j) => (j === i ? { ...y, cantidad_estandar: e.target.value } : y)) })} />
              <input aria-label={`Unidad material ${i + 1}`} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm" value={m.unidad} onChange={(e) => setB({ ...b, materiales: b.materiales.map((y, j) => (j === i ? { ...y, unidad: e.target.value } : y)) })} />
              <Boton type="button" variante="fantasma" onClick={() => setB({ ...b, materiales: b.materiales.filter((_, j) => j !== i) })}>Quitar</Boton>
            </div>
          ))}
          <Boton type="button" variante="secundario" onClick={() => setB({ ...b, materiales: [...b.materiales, { articulo_id: null, descripcion: '', cantidad_estandar: '1', unidad: 'pieza' }] })}>+ Material</Boton>
        </fieldset>

        <div className="flex justify-end gap-2">
          <Boton type="button" variante="fantasma" onClick={alCerrar}>Cancelar</Boton>
          <Boton type="submit" disabled={!b.nombre || !b.tipo_equipo_id}>{plan ? 'Guardar cambios' : 'Crear plan'}</Boton>
        </div>
      </form>
    </Modal>
  )
}

function DetallePlan({ plan, puedeEditar, alCerrar, alCambiar }: { plan: Plan; puedeEditar: boolean; alCerrar: () => void; alCambiar: () => Promise<void> }) {
  const [equipos, setEquipos] = useState<Equipo[]>([])
  const [equipoId, setEquipoId] = useState('')
  const [fechaBase, setFechaBase] = useState('')
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { api<Equipo[]>('/catalogos/equipos', { params: { tipo_equipo_id: plan.tipo_equipo_id } }).then((l) => setEquipos(l.filter((e) => e.tipo_equipo_id === plan.tipo_equipo_id))).catch(() => setEquipos([])) }, [plan.tipo_equipo_id])
  const nombres = Object.fromEntries(equipos.map((e) => [e.id, `${e.codigo} · ${e.nombre}`]))
  async function asignar() {
    try { await asignarPlanAEquipo(plan.id, equipoId, fechaBase || null); await alCambiar() } catch (e) { setError(mensajeDeError(e)) }
  }
  return (
    <Modal titulo={plan.nombre} abierto alCerrar={alCerrar}>
      {error && <div className="mb-3"><Aviso>{error}</Aviso></div>}
      <div className="space-y-3 text-sm">
        <p className="text-slate-600">{plan.descripcion || 'Sin descripción'} · {plan.tipo_equipo_nombre} · ventana {plan.tiempo_ventana_dias} días · formulario {plan.formulario_nombre ?? 'por resolver'} · v{plan.version}</p>
        <ul className="text-sm"><strong>Cuándo se ejecuta:</strong>
          {plan.triggers.map((t) => <li key={t.id ?? t.clave}><Insignia tono="acento">{t.clave}</Insignia> {describirTrigger(t)}</li>)}
        </ul>
        <Simulacion plan={plan} />
        <Tarjeta titulo={`Tareas (${plan.tareas.length})`}>
          <ol className="list-decimal pl-5">{plan.tareas.map((t) => <li key={t.id ?? t.descripcion}>{t.descripcion} <span className="text-xs text-slate-500">· {t.tiempo_estimado_min} min{t.habilidad_requerida_id && ' · habilidad requerida'}</span></li>)}</ol>
        </Tarjeta>
        <Tarjeta titulo={`Materiales (${plan.materiales.length})`}>
          <ul>{plan.materiales.map((m) => <li key={m.id ?? m.descripcion}>{m.cantidad_estandar} {m.unidad} · {m.descripcion}</li>)}</ul>
        </Tarjeta>
        <Tarjeta titulo={`Equipos (${plan.equipos.length})`}>
          <ul className="divide-y divide-slate-100">
            {plan.equipos.map((e) => (
              <li key={e.id} className="flex items-center justify-between py-1">
                <span>{nombres[e.equipo_id] ?? e.equipo_id} <span className="text-xs text-slate-500">· próxima {e.fecha_proxima_ejecucion ?? '—'} · última {e.fecha_ultima_ejecucion ?? '—'}{e.ultimo_valor_medidor ? ` · último PM al medidor ${Number(e.ultimo_valor_medidor)}` : ''}</span> {!e.activo && <Insignia>inactivo</Insignia>}</span>
                {puedeEditar && e.activo && <Boton variante="fantasma" onClick={async () => { try { await quitarPlanDeEquipo(plan.id, e.equipo_id); await alCambiar() } catch (err) { setError(mensajeDeError(err)) } }}>Quitar</Boton>}
              </li>
            ))}
          </ul>
          {puedeEditar && (
            <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_auto_auto]">
              <Selector etiqueta="Agregar equipo" value={equipoId} onChange={(e) => setEquipoId(e.target.value)} opciones={[{ valor: '', texto: 'Elegir…' }, ...equipos.filter((e) => !plan.equipos.some((x) => x.equipo_id === e.id && x.activo)).map((e) => ({ valor: e.id, texto: `${e.codigo} · ${e.nombre}` }))]} />
              <Campo etiqueta="Fecha base" type="date" value={fechaBase} onChange={(e) => setFechaBase(e.target.value)} />
              <Boton className="self-end" disabled={!equipoId} onClick={() => void asignar()}>Asignar</Boton>
            </div>
          )}
        </Tarjeta>
      </div>
    </Modal>
  )
}

/**
 * «¿Cuándo se dispararía este plan con las lecturas actuales?» (§6.9.1): una fila por equipo asignado con la fecha
 * estimada y el detalle de cada condición. Es lo que permite revisar un plan por medidor antes de confiar en él.
 */
function Simulacion({ plan }: { plan: Plan }) {
  const [filas, setFilas] = useState<FilaSimulacion[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [abierto, setAbierto] = useState(false)
  async function cargar() {
    setAbierto(true)
    try { setFilas(await simularPlan(plan.id)) } catch (e) { setError(mensajeDeError(e)) }
  }
  if (!abierto) return <Boton variante="secundario" onClick={() => void cargar()}>Simular: ¿cuándo se dispararía?</Boton>
  return (
    <Tarjeta titulo="Simulación con las lecturas actuales">
      {error && <Aviso>{error}</Aviso>}
      {!filas && !error && <p className="text-sm text-slate-500">Calculando…</p>}
      {filas && filas.length === 0 && <p className="text-sm text-slate-500">El plan no está asignado a ningún equipo todavía.</p>}
      <div className="space-y-2" data-testid="simulacion">
        {(filas ?? []).map((f) => (
          <article key={f.equipo_id} className="rounded-lg border border-slate-200 p-2">
            <p className="text-sm font-medium">
              {f.equipo_codigo} · {f.equipo}
              {f.fecha_estimada ? <> → <strong>{f.fecha_estimada}</strong></> : <span className="text-slate-500"> → sin fecha estimada</span>}
              {f.folio_abierto && <> <Insignia tono="alerta">ya tiene el folio {f.folio_abierto.numero_folio} abierto</Insignia></>}
            </p>
            <ul className="mt-1 text-xs text-slate-600">
              {f.triggers.map((t) => (
                <li key={t.clave}>
                  <Insignia>{t.clave}</Insignia> {t.fecha_estimada ?? 'sin fecha'}
                  {t.valor_actual !== null && <> · va en {Number(t.valor_actual)} de {Number(t.valor_objetivo)} {t.unidad}</>}
                  {t.motivo && <> · {t.motivo}</>}
                </li>
              ))}
            </ul>
          </article>
        ))}
      </div>
    </Tarjeta>
  )
}
