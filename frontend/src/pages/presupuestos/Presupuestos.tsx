import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { Aviso, Boton, Campo, Encabezado, Insignia, Modal, Selector, Tabla, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { useRecurso } from '../../hooks/useRecurso'
import { mensajeDeError } from '../../services/api'
import { consolidado as cargarConsolidado, consumosPresupuesto, crearPresupuesto, editarPresupuesto, listarPresupuestos } from '../../services/inventario'
import type { GrupoUN, UnidadNegocio } from '../../types/api'
import type { Consolidado, ConsumoPresupuesto, NivelConsolidado, Presupuesto, TipoActividad } from '../../types/inventario'
import { NOMBRE_SEMAFORO, NOMBRE_TIPO_ACTIVIDAD, ROLES_ESCRIBEN_PRESUPUESTO } from '../../types/inventario'

type Vista = 'tablero' | 'listado'

function moneda(v: string | null | undefined) {
  return v == null ? '—' : `$${Number(v).toLocaleString('es-MX', { minimumFractionDigits: 2 })}`
}

function Barra({ fila }: { fila: { porcentaje: string; semaforo: string } }) {
  const pct = Math.min(100, Number(fila.porcentaje))
  const color = { verde: 'bg-green-500', amarillo: 'bg-amber-500', rojo: 'bg-red-600' }[fila.semaforo] ?? 'bg-slate-400'
  return (
    <div>
      <div className="h-2 w-full rounded bg-slate-200"><div className={`h-2 rounded ${color}`} style={{ width: `${pct}%` }} /></div>
      <p className="mt-1 text-xs text-slate-600">{`${Number(fila.porcentaje).toFixed(1)}%`} · {NOMBRE_SEMAFORO[fila.semaforo] ?? fila.semaforo}</p>
    </div>
  )
}

/** Presupuestos y control de gasto (§4.1, §6.8.5): alta por UN o grupo y tablero consolidado Tenant → Grupo → UN. */
export function Presupuestos() {
  const { usuario } = useAuth()
  const [params, setParams] = useSearchParams()
  const vista = (params.get('vista') as Vista) || 'tablero'
  const presupuestoId = params.get('presupuesto')
  const [datos, setDatos] = useState<Consolidado | null>(null)
  const [lista, setLista] = useState<Presupuesto[]>([])
  const [vigentes, setVigentes] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [creando, setCreando] = useState(false)

  const cargar = useCallback(async () => {
    try {
      if (vista === 'tablero') setDatos(await cargarConsolidado({ vigentes }))
      else setLista(await listarPresupuestos({ vigentes }))
    } catch (e) { setError(mensajeDeError(e)) }
  }, [vista, vigentes])
  useEffect(() => { void cargar() }, [cargar])

  function ir(cambios: Record<string, string | null>) {
    const p = new URLSearchParams(params)
    for (const [k, v] of Object.entries(cambios)) { if (v) p.set(k, v); else p.delete(k) }
    setParams(p)
  }
  if (!usuario) return null
  const escribe = ROLES_ESCRIBEN_PRESUPUESTO.includes(usuario.rol)
  const soloLectura = usuario.rol === 'admin_un' || usuario.rol === 'supervisor_operadores'

  return (
    <div>
      <Encabezado titulo="Presupuestos" descripcion="Gasto contra presupuesto por unidad de negocio, grupo y tipo de actividad (§6.8.5). El consumo se registra al validarse el costo de cada folio; el comprometido son los folios autorizados que aún no cierran."
        acciones={escribe ? <Boton onClick={() => setCreando(true)}>Nuevo presupuesto</Boton> : undefined} />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex gap-1" role="tablist" aria-label="Vistas de presupuesto">
          {([['tablero', 'Tablero consolidado'], ['listado', 'Listado']] as [Vista, string][]).map(([v, texto]) => (
            <button key={v} role="tab" aria-selected={vista === v} className={`rounded-lg px-3 py-1.5 text-sm ${vista === v ? 'bg-primario text-white' : 'border border-slate-300'}`}
              onClick={() => ir({ vista: v })}>{texto}</button>
          ))}
        </div>
        <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={vigentes} onChange={(e) => setVigentes(e.target.checked)} /> Solo períodos vigentes</label>
        {soloLectura && <Insignia>Solo lectura de tus UNs</Insignia>}
      </div>
      {error && <div className="mb-3"><Aviso>{error}</Aviso></div>}
      {aviso && <div className="mb-3"><Aviso tipo="exito">{aviso}</Aviso></div>}

      {vista === 'tablero' && datos && (
        <div className="space-y-4" data-testid="tablero-presupuestos">
          <Tarjeta titulo="Cliente">
            <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
              <Barra fila={datos.tenant} />
              <p className="text-sm">Presupuesto {moneda(datos.tenant.monto)} · consumido {moneda(datos.tenant.consumido)} · comprometido {moneda(datos.tenant.comprometido)} · disponible <strong>{moneda(datos.tenant.disponible)}</strong></p>
            </div>
          </Tarjeta>
          {(['grupos', 'unidades'] as const).map((nivel) => (
            <Tarjeta key={nivel} titulo={nivel === 'grupos' ? 'Por grupo de unidades' : 'Por unidad de negocio'}>
              {datos[nivel].length === 0 ? <p className="text-sm text-slate-500">Sin presupuestos en este nivel.</p> : (
                <ul className="space-y-3" data-testid={`nivel-${nivel}`}>
                  {datos[nivel].map((n: NivelConsolidado) => (
                    <li key={n.id ?? n.nombre}>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="text-sm font-medium">{n.nombre}</span>
                        <span className="text-xs text-slate-600">{moneda(n.consumido)} de {moneda(n.monto)} · disponible {moneda(n.disponible)} · desviación {moneda(n.desviacion)}</span>
                      </div>
                      <Barra fila={n} />
                      <ul className="mt-1 text-xs text-slate-500">{n.presupuestos.map((p) => (
                        <li key={p.id}><button className="text-primario underline" onClick={() => ir({ presupuesto: p.id })}>{p.nombre || NOMBRE_TIPO_ACTIVIDAD[p.tipo_actividad]}</button> · {NOMBRE_TIPO_ACTIVIDAD[p.tipo_actividad]} · {p.periodo_inicio} a {p.periodo_fin}</li>
                      ))}</ul>
                    </li>
                  ))}
                </ul>
              )}
            </Tarjeta>
          ))}
        </div>
      )}
      {vista === 'listado' && (
        <div className="rounded-xl border border-slate-200 bg-white p-2">
          <Tabla filas={lista} vacio="Sin presupuestos" columnas={[
            { titulo: 'Nombre', celda: (p) => <button className="text-left text-sm text-primario underline" onClick={() => ir({ presupuesto: p.id })}>{p.nombre || 'Sin nombre'}</button> },
            { titulo: 'Alcance', celda: (p) => p.grupo_nombre ? <span>Grupo {p.grupo_nombre}</span> : <span>{p.un_codigo} · {p.un_nombre}</span> },
            { titulo: 'Actividad', celda: (p) => NOMBRE_TIPO_ACTIVIDAD[p.tipo_actividad] },
            { titulo: 'Período', celda: (p) => <span className="text-xs">{p.periodo_inicio} a {p.periodo_fin}</span> },
            { titulo: 'Monto', celda: (p) => moneda(p.monto) },
            { titulo: 'Consumido', celda: (p) => <span className={p.semaforo === 'rojo' ? 'font-semibold text-red-700' : ''}>{moneda(p.consumido)}</span> },
            { titulo: 'Disponible', celda: (p) => moneda(p.disponible) },
            { titulo: 'Avance', celda: (p) => <div className="w-32"><Barra fila={p} /></div> },
          ]} />
        </div>
      )}

      {creando && <FormPresupuesto alCerrar={() => setCreando(false)} alGuardar={async (d) => {
        setError(null)
        try { await crearPresupuesto(d); setCreando(false); setAviso('Presupuesto creado'); await cargar() } catch (e) { setError(mensajeDeError(e)) }
      }} />}
      {presupuestoId && <DetallePresupuesto presupuestoId={presupuestoId} alCerrar={() => ir({ presupuesto: null })} alCambiar={async (t) => { setAviso(t); await cargar() }} />}
    </div>
  )
}

function FormPresupuesto({ alCerrar, alGuardar }: { alCerrar: () => void; alGuardar: (d: Record<string, unknown>) => Promise<void> }) {
  const hoy = new Date()
  const fin = new Date(hoy.getFullYear(), hoy.getMonth() + 3, 0)
  const [d, setD] = useState({ nombre: '', alcance: 'un', un_id: '', grupo_id: '', tipo_actividad: 'todos' as TipoActividad, monto: '',
                               periodo_inicio: new Date(hoy.getFullYear(), hoy.getMonth(), 1).toISOString().slice(0, 10), periodo_fin: fin.toISOString().slice(0, 10),
                               umbrales: '50,80,100' })
  const unidades = useRecurso<UnidadNegocio[]>('/unidades-negocio')
  const grupos = useRecurso<GrupoUN[]>('/grupos-un')
  const listo = d.monto && Number(d.monto) > 0 && (d.alcance === 'un' ? d.un_id : d.grupo_id)
  return (
    <Modal titulo="Nuevo presupuesto" abierto alCerrar={alCerrar}>
      <div className="space-y-3" data-testid="form-presupuesto">
        <Campo etiqueta="Nombre" value={d.nombre} onChange={(e) => setD({ ...d, nombre: e.target.value })} />
        <Selector etiqueta="Alcance" value={d.alcance} onChange={(e) => setD({ ...d, alcance: e.target.value, un_id: '', grupo_id: '' })}
          opciones={[{ valor: 'un', texto: 'Una unidad de negocio' }, { valor: 'grupo', texto: 'Un grupo de UNs' }]} />
        {d.alcance === 'un' ? (
          <Selector etiqueta="Unidad de negocio" value={d.un_id} onChange={(e) => setD({ ...d, un_id: e.target.value })}
            opciones={[{ valor: '', texto: 'Elegir…' }, ...(unidades.datos ?? []).map((u) => ({ valor: u.id, texto: `${u.codigo} · ${u.nombre}` }))]} />
        ) : (
          <Selector etiqueta="Grupo" value={d.grupo_id} onChange={(e) => setD({ ...d, grupo_id: e.target.value })}
            opciones={[{ valor: '', texto: 'Elegir…' }, ...(grupos.datos ?? []).map((g) => ({ valor: g.id, texto: g.nombre }))]} />
        )}
        <Selector etiqueta="Tipo de actividad" value={d.tipo_actividad} onChange={(e) => setD({ ...d, tipo_actividad: e.target.value as TipoActividad })}
          opciones={(['todos', 'correctivo', 'preventivo', 'especial'] as TipoActividad[]).map((t) => ({ valor: t, texto: NOMBRE_TIPO_ACTIVIDAD[t] }))} />
        <div className="grid gap-2 sm:grid-cols-2">
          <Campo etiqueta="Inicio del período" type="date" value={d.periodo_inicio} onChange={(e) => setD({ ...d, periodo_inicio: e.target.value })} />
          <Campo etiqueta="Fin del período" type="date" value={d.periodo_fin} onChange={(e) => setD({ ...d, periodo_fin: e.target.value })} />
          <Campo etiqueta="Monto" type="number" value={d.monto} onChange={(e) => setD({ ...d, monto: e.target.value })} />
          <Campo etiqueta="Umbrales de alerta (%)" value={d.umbrales} onChange={(e) => setD({ ...d, umbrales: e.target.value })} />
        </div>
        <div className="flex gap-2">
          <Boton disabled={!listo} onClick={() => void alGuardar({
            nombre: d.nombre, tipo_actividad: d.tipo_actividad, periodo_inicio: d.periodo_inicio, periodo_fin: d.periodo_fin, monto: d.monto,
            umbrales_alerta_json: d.umbrales.split(',').map((x) => Number(x.trim())).filter((x) => x > 0),
            ...(d.alcance === 'un' ? { un_id: d.un_id } : { grupo_id: d.grupo_id }),
          })}>Crear</Boton>
          <Boton variante="secundario" onClick={alCerrar}>Cancelar</Boton>
        </div>
      </div>
    </Modal>
  )
}

function DetallePresupuesto({ presupuestoId, alCerrar, alCambiar }: { presupuestoId: string; alCerrar: () => void; alCambiar: (t: string) => Promise<void> }) {
  const { usuario } = useAuth()
  const [p, setP] = useState<Presupuesto | null>(null)
  const [consumos, setConsumos] = useState<ConsumoPresupuesto[]>([])
  const [monto, setMonto] = useState('')
  const [error, setError] = useState<string | null>(null)
  const cargar = useCallback(async () => {
    try {
      const lista = await listarPresupuestos({})
      const actual = lista.find((x) => x.id === presupuestoId) ?? null
      setP(actual)
      setMonto(actual?.monto ?? '')
      setConsumos(await consumosPresupuesto(presupuestoId))
    } catch (e) { setError(mensajeDeError(e)) }
  }, [presupuestoId])
  useEffect(() => { void cargar() }, [cargar])
  if (!p || !usuario) return <Modal titulo="Presupuesto" abierto alCerrar={alCerrar}>{error ? <Aviso>{error}</Aviso> : <p className="text-sm text-slate-500">Cargando…</p>}</Modal>
  const escribe = ROLES_ESCRIBEN_PRESUPUESTO.includes(usuario.rol)
  return (
    <Modal titulo={p.nombre || 'Presupuesto'} abierto alCerrar={alCerrar}>
      {error && <div className="mb-2"><Aviso>{error}</Aviso></div>}
      <div className="space-y-3 text-sm" data-testid="detalle-presupuesto">
        <p className="text-slate-700">{p.grupo_nombre ? `Grupo ${p.grupo_nombre}` : `${p.un_codigo} · ${p.un_nombre}`} · {NOMBRE_TIPO_ACTIVIDAD[p.tipo_actividad]} · {p.periodo_inicio} a {p.periodo_fin}</p>
        <Barra fila={p} />
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
          <dt className="text-slate-500">Presupuesto</dt><dd>{moneda(p.monto)} {p.moneda}</dd>
          <dt className="text-slate-500">Consumido</dt><dd>{moneda(p.consumido)}</dd>
          <dt className="text-slate-500">Comprometido</dt><dd>{moneda(p.comprometido)} <span className="text-xs text-slate-500">(folios autorizados sin cerrar)</span></dd>
          <dt className="text-slate-500">Disponible</dt><dd><strong>{moneda(p.disponible)}</strong></dd>
          <dt className="text-slate-500">Desviación</dt><dd>{moneda(p.desviacion)}</dd>
          <dt className="text-slate-500">Umbrales</dt><dd>{(p.umbrales_alerta_json ?? []).join('% · ')}%</dd>
        </dl>
        {escribe && (
          <div className="flex flex-wrap items-end gap-2">
            <Campo etiqueta="Nuevo monto" type="number" value={monto} onChange={(e) => setMonto(e.target.value)} />
            <Boton variante="secundario" disabled={!monto || Number(monto) <= 0} onClick={async () => {
              setError(null)
              try { await editarPresupuesto(p.id, { monto }); await cargar(); await alCambiar('Presupuesto actualizado') } catch (e) { setError(mensajeDeError(e)) }
            }}>Guardar monto</Boton>
          </div>
        )}
        <div>
          <h3 className="text-xs font-semibold uppercase text-slate-500">Folios cargados ({consumos.length})</h3>
          {consumos.length === 0 ? <p className="text-sm text-slate-500">Todavía no hay folios con costo validado en este período.</p> : (
            <ul className="text-xs text-slate-600" data-testid="consumos-presupuesto">{consumos.map((c) => (
              <li key={c.id}>{c.fecha} · {c.folio_id ? <Link className="text-primario underline" to={`/folios/${c.folio_id}`}>{c.numero_folio}</Link> : (c.descripcion ?? 'ajuste manual')} · {c.un_codigo} · {moneda(c.monto)} <span className="text-slate-400">({c.tipo})</span></li>
            ))}</ul>
          )}
        </div>
      </div>
    </Modal>
  )
}
