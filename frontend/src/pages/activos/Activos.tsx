import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { Aviso, Boton, Campo, Encabezado, Insignia, Modal, Selector, Tabla } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { useRecurso } from '../../hooks/useRecurso'
import { mensajeDeError } from '../../services/api'
import { alertasReemplazo, decidirReemplazo, guardarUmbralReemplazo, listarActivos } from '../../services/inventario'
import type { UnidadNegocio } from '../../types/api'
import type { ActivoResumen, AlertaReemplazo } from '../../types/inventario'
import { ROLES_ESCRIBEN_PRESUPUESTO } from '../../types/inventario'

function moneda(v: string | null | undefined) {
  return v == null ? '—' : `$${Number(v).toLocaleString('es-MX', { minimumFractionDigits: 2 })}`
}

/** Listado de activos con TCO y alerta de reemplazo (§6.9.4). La ficha completa está en `FichaEquipo`. */
export function Activos() {
  const { usuario } = useAuth()
  const [params, setParams] = useSearchParams()
  const vista = params.get('vista') === 'alertas' ? 'alertas' : 'listado'
  const [activos, setActivos] = useState<ActivoResumen[]>([])
  const [alertas, setAlertas] = useState<AlertaReemplazo[]>([])
  const [filtros, setFiltros] = useState({ un_id: '', con_alerta: false })
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [umbral, setUmbral] = useState(false)
  const [decidiendo, setDecidiendo] = useState<AlertaReemplazo | null>(null)
  const unidades = useRecurso<UnidadNegocio[]>('/unidades-negocio')

  const cargar = useCallback(async () => {
    try {
      if (vista === 'listado') setActivos(await listarActivos({ un_id: filtros.un_id || undefined, con_alerta: filtros.con_alerta }))
      else setAlertas(await alertasReemplazo(true))
    } catch (e) { setError(mensajeDeError(e)) }
  }, [vista, filtros])
  useEffect(() => { void cargar() }, [cargar])

  function ir(cambios: Record<string, string | null>) {
    const p = new URLSearchParams(params)
    for (const [k, v] of Object.entries(cambios)) { if (v) p.set(k, v); else p.delete(k) }
    setParams(p)
  }
  if (!usuario) return null
  const decide = ROLES_ESCRIBEN_PRESUPUESTO.includes(usuario.rol)

  return (
    <div>
      <Encabezado titulo="Equipos y activos" descripcion="Ficha por equipo con historial, depreciación y costo total de propiedad. Cuando el TCO acumulado supera el porcentaje configurado de su valor de reposición, ACMA recomienda reemplazar. La criticidad automática, el FMEA, el MTBF y el MTTR llegan en Fase 2."
        acciones={decide ? <Boton variante="secundario" onClick={() => setUmbral(true)}>Umbral de reemplazo</Boton> : undefined} />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex gap-1" role="tablist" aria-label="Vistas de activos">
          {([['listado', 'Listado'], ['alertas', 'Reemplazos recomendados']] as [string, string][]).map(([v, texto]) => (
            <button key={v} role="tab" aria-selected={vista === v} className={`rounded-lg px-3 py-1.5 text-sm ${vista === v ? 'bg-primario text-white' : 'border border-slate-300'}`}
              onClick={() => ir({ vista: v })}>{texto}</button>
          ))}
        </div>
        {vista === 'listado' && (
          <>
            <Selector etiqueta="Unidad de negocio" value={filtros.un_id} onChange={(e) => setFiltros({ ...filtros, un_id: e.target.value })}
              opciones={[{ valor: '', texto: 'Todas' }, ...(unidades.datos ?? []).map((u) => ({ valor: u.id, texto: `${u.codigo} · ${u.nombre}` }))]} />
            <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={filtros.con_alerta}
              onChange={(e) => setFiltros({ ...filtros, con_alerta: e.target.checked })} /> Solo con alerta de reemplazo</label>
          </>
        )}
      </div>
      {error && <div className="mb-3"><Aviso>{error}</Aviso></div>}
      {aviso && <div className="mb-3"><Aviso tipo="exito">{aviso}</Aviso></div>}

      {vista === 'listado' && (
        <div className="rounded-xl border border-slate-200 bg-white p-2">
          <Tabla filas={activos} vacio="Sin equipos con datos de activo" columnas={[
            { titulo: 'Código', celda: (a) => <Link className="font-mono text-xs text-primario underline" to={`/activos/${a.id}`}>{a.codigo}</Link> },
            { titulo: 'Equipo', celda: (a) => <span className="text-sm">{a.nombre}{a.marca && <span className="text-xs text-slate-500"> · {a.marca} {a.modelo}</span>}</span> },
            { titulo: 'UN', celda: (a) => <span>{a.un_codigo} <span className="text-xs text-slate-500">{a.un_nombre}</span></span> },
            { titulo: 'Criticidad', celda: (a) => a.criticidad ? <Insignia tono={['A', 'B'].includes(a.criticidad) ? 'alerta' : 'neutro'}>{a.criticidad}</Insignia> : <span className="text-xs text-slate-400">—</span> },
            { titulo: 'Adquisición', celda: (a) => moneda(a.costo_adquisicion) },
            { titulo: 'TCO', celda: (a) => moneda(a.tco_total) },
            { titulo: 'TCO / reposición', celda: (a) => a.porcentaje_vs_reposicion == null ? '—'
              : <span className={a.alerta_reemplazo ? 'font-semibold text-red-700' : ''}>{Number(a.porcentaje_vs_reposicion).toFixed(1)}%</span> },
            { titulo: 'Estado', celda: (a) => a.alerta_reemplazo ? <Insignia tono="alerta">Reemplazo recomendado</Insignia> : <Insignia tono="ok">En operación</Insignia> },
          ]} />
        </div>
      )}
      {vista === 'alertas' && (
        <div className="rounded-xl border border-slate-200 bg-white p-2" data-testid="alertas-reemplazo">
          <Tabla filas={alertas} vacio="No hay reemplazos recomendados pendientes de decisión" columnas={[
            { titulo: 'Equipo', celda: (a) => <Link className="font-mono text-xs text-primario underline" to={`/activos/${a.equipo_id}`}>{a.equipo_codigo}</Link> },
            { titulo: 'Descripción', celda: (a) => <span className="text-sm">{a.equipo_nombre}</span> },
            { titulo: 'UN', celda: (a) => a.un_codigo ?? '—' },
            { titulo: 'Fecha', celda: (a) => a.fecha_alerta },
            { titulo: 'TCO', celda: (a) => moneda(a.tco_al_momento) },
            { titulo: 'Reposición', celda: (a) => moneda(a.valor_reposicion) },
            { titulo: 'Avance', celda: (a) => <span className="font-semibold text-red-700">{Number(a.porcentaje_alcanzado).toFixed(1)}% <span className="text-xs font-normal text-slate-500">(umbral {Number(a.porcentaje_umbral).toFixed(0)}%)</span></span> },
            { titulo: 'Decisión', celda: (a) => decide ? <Boton variante="secundario" onClick={() => setDecidiendo(a)}>Decidir</Boton> : <span className="text-xs text-slate-500">pendiente</span> },
          ]} />
        </div>
      )}
      {umbral && <FormUmbral alCerrar={() => setUmbral(false)} alGuardar={async (v) => {
        setError(null)
        try { await guardarUmbralReemplazo(v); setUmbral(false); setAviso(`Umbral de reemplazo fijado en ${v}%`); await cargar() } catch (e) { setError(mensajeDeError(e)) }
      }} />}
      {decidiendo && <FormDecision alerta={decidiendo} alCerrar={() => setDecidiendo(null)} alDecidir={async (decision, razon) => {
        setError(null)
        try {
          const r = await decidirReemplazo(decidiendo.id, decision, razon)
          setDecidiendo(null)
          setAviso(r.trabajo_especial ? `Trabajo especial de reemplazo ${r.trabajo_especial.numero} creado para que el prestador lo cotice` : 'Reemplazo pospuesto con la razón documentada')
          await cargar()
        } catch (e) { setError(mensajeDeError(e)) }
      }} />}
    </div>
  )
}

function FormUmbral({ alCerrar, alGuardar }: { alCerrar: () => void; alGuardar: (v: string) => Promise<void> }) {
  const [v, setV] = useState('70')
  return (
    <Modal titulo="Umbral de reemplazo recomendado" abierto alCerrar={alCerrar}>
      <div className="space-y-3" data-testid="form-umbral">
        <Aviso tipo="info">Porcentaje del valor de reposición que el TCO acumulado debe superar para que ACMA recomiende reemplazar el activo.</Aviso>
        <Campo etiqueta="Umbral (%)" type="number" value={v} onChange={(e) => setV(e.target.value)} />
        <div className="flex gap-2"><Boton disabled={Number(v) < 10} onClick={() => void alGuardar(v)}>Guardar</Boton><Boton variante="secundario" onClick={alCerrar}>Cancelar</Boton></div>
      </div>
    </Modal>
  )
}

function FormDecision({ alerta, alCerrar, alDecidir }: { alerta: AlertaReemplazo; alCerrar: () => void; alDecidir: (d: 'aceptado' | 'pospuesto', razon: string) => Promise<void> }) {
  const [razon, setRazon] = useState('')
  return (
    <Modal titulo={`Reemplazar o reparar: ${alerta.equipo_codigo}`} abierto alCerrar={alCerrar}>
      <div className="space-y-3 text-sm" data-testid="form-decision-reemplazo">
        <p>El costo total de propiedad acumulado es {moneda(alerta.tco_al_momento)}, el {Number(alerta.porcentaje_alcanzado).toFixed(1)}% de su valor de reposición ({moneda(alerta.valor_reposicion)}), por encima del umbral del {Number(alerta.porcentaje_umbral).toFixed(0)}%.</p>
        <Aviso tipo="info">Aceptar genera un trabajo especial de reemplazo en estado creado para que el prestador lo cotice y lo envíe a tu validación. Posponer exige razón documentada.</Aviso>
        <Campo etiqueta="Razón (obligatoria al posponer)" value={razon} onChange={(e) => setRazon(e.target.value)} />
        <div className="flex gap-2">
          <Boton onClick={() => void alDecidir('aceptado', razon)}>Aceptar: generar trabajo especial</Boton>
          <Boton variante="secundario" disabled={razon.trim().length < 3} onClick={() => void alDecidir('pospuesto', razon)}>Posponer</Boton>
        </div>
      </div>
    </Modal>
  )
}
