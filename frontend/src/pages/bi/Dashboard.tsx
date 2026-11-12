import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { Aviso, Boton, Campo, Encabezado, Insignia, Selector, Tabla, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { useRecurso } from '../../hooks/useRecurso'
import { mensajeDeError } from '../../services/api'
import { tablero as cargarTablero } from '../../services/sla'
import type { GrupoUN, UnidadNegocio } from '../../types/api'
import type { NivelJerarquia, Tablero } from '../../types/sla'
import { fecha as fmtFecha } from '../folios/comunes'

// Paleta accesible (contraste suficiente en claro y oscuro); cada valor va además en texto junto a la gráfica.
const COLORES = ['#1C3D8F', '#A2C62B', '#D97706', '#B91C1C', '#0E7490', '#7C3AED', '#64748B']

function moneda(v: string | number | null | undefined) {
  return v == null ? '—' : `$${Number(v).toLocaleString('es-MX', { minimumFractionDigits: 2 })}`
}
function primeroDelMes() {
  const h = new Date()
  return new Date(h.getFullYear(), h.getMonth(), 1).toISOString().slice(0, 10)
}

/** Identificador estable para las pruebas: sin acentos ni signos. */
function slug(texto: string) {
  return texto.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
}

function KPI({ titulo, valor, detalle, variacion }: { titulo: string; valor: string; detalle?: string; variacion?: number | null }) {
  const signo = variacion == null ? null : variacion > 0 ? '▲' : variacion < 0 ? '▼' : '='
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3" data-testid={`kpi-${slug(titulo)}`}>
      <p className="text-xs uppercase text-slate-500">{titulo}</p>
      <p className="text-2xl font-semibold text-slate-900">{valor}</p>
      {detalle && <p className="text-xs text-slate-600">{detalle}</p>}
      {signo && (
        <p className={`text-xs ${variacion! > 0 ? 'text-green-700' : variacion! < 0 ? 'text-red-700' : 'text-slate-500'}`}>
          {signo} {Math.abs(variacion!).toFixed(1)} % contra el período anterior
        </p>
      )}
    </div>
  )
}

/** Tablero de BI según el rol (§5.1, §5.2, §7.5). Gráficas con Recharts (código abierto, compatible con React 19). */
export function Dashboard() {
  const { usuario } = useAuth()
  const [params, setParams] = useSearchParams()
  const [datos, setDatos] = useState<Tablero | null>(null)
  const [error, setError] = useState<string | null>(null)
  const desde = params.get('desde') ?? primeroDelMes()
  const hasta = params.get('hasta') ?? new Date().toISOString().slice(0, 10)
  const grupoId = params.get('grupo_id') ?? ''
  const unId = params.get('un_id') ?? ''
  const unidades = useRecurso<UnidadNegocio[]>('/unidades-negocio')
  const grupos = useRecurso<GrupoUN[]>('/grupos-un')

  const cargar = useCallback(async () => {
    setError(null)
    try {
      setDatos(await cargarTablero({ desde, hasta, grupo_id: grupoId || undefined, un_id: unId || undefined }))
    } catch (e) { setError(mensajeDeError(e)) }
  }, [desde, hasta, grupoId, unId])
  useEffect(() => { void cargar() }, [cargar])

  function ir(cambios: Record<string, string>) {
    const p = new URLSearchParams(params)
    for (const [k, v] of Object.entries(cambios)) { if (v) p.set(k, v); else p.delete(k) }
    setParams(p)
  }
  if (!usuario) return null

  return (
    <div>
      <Encabezado titulo="Inteligencia de negocio"
        descripcion="Indicadores del período con la jerarquía cliente → grupo → unidad de negocio. Cada valor se muestra también en texto; los cálculos se hacen en el servidor y se guardan 120 segundos en caché."
        acciones={<Link className="text-sm text-primario underline" to="/bi/reportes">Reportes ejecutivos</Link>} />
      <div className="mb-4 flex flex-wrap items-end gap-2">
        <Campo etiqueta="Desde" type="date" value={desde} onChange={(e) => ir({ desde: e.target.value })} />
        <Campo etiqueta="Hasta" type="date" value={hasta} onChange={(e) => ir({ hasta: e.target.value })} />
        <Selector etiqueta="Grupo de UNs" value={grupoId} onChange={(e) => ir({ grupo_id: e.target.value, un_id: '' })}
          opciones={[{ valor: '', texto: 'Todos' }, ...(grupos.datos ?? []).map((g) => ({ valor: g.id, texto: g.nombre }))]} />
        <Selector etiqueta="Unidad de negocio" value={unId} onChange={(e) => ir({ un_id: e.target.value, grupo_id: '' })}
          opciones={[{ valor: '', texto: 'Todas' }, ...(unidades.datos ?? []).map((u) => ({ valor: u.id, texto: `${u.codigo} · ${u.nombre}` }))]} />
        <Boton variante="secundario" onClick={() => void cargar()}>Actualizar</Boton>
      </div>
      {error && <Aviso>{error}</Aviso>}
      {!datos ? <p className="text-sm text-slate-500">Cargando el tablero…</p> : (
        <div className="space-y-4" data-testid={`tablero-${datos.tipo}`}>
          <p className="text-xs text-slate-500">
            Período {datos.periodo.desde} a {datos.periodo.hasta} · rol {datos.rol}
            {datos.cache && <> · <Insignia>desde caché ({datos.ttl_cache_segundos} s)</Insignia></>}
            {datos.solo_lectura && <> · <Insignia>solo lectura</Insignia></>}
          </p>
          {datos.aviso && <Aviso tipo="info">{datos.aviso}</Aviso>}
          {datos.jornada && <BarraJornada d={datos} />}
          {datos.tipo === 'cliente' && <TableroCliente d={datos} />}
          {datos.tipo === 'supervision' && <TableroSupervision d={datos} />}
          {datos.tipo === 'prestador' && <TableroPrestador d={datos} />}
          {datos.tipo === 'direccion' && <TableroDireccion d={datos} />}
        </div>
      )}
    </div>
  )
}

function BarraJornada({ d }: { d: Tablero }) {
  const j = d.jornada!
  return (
    <Tarjeta titulo="Indicadores globales de jornada">
      <div className="grid gap-3 sm:grid-cols-4" data-testid="barra-jornada">
        <KPI titulo="Folios completados" valor={`${j.completados} / ${j.total_dia}`} detalle="del día en curso" />
        <KPI titulo="Técnicos activos" valor={String(j.tecnicos_activos)} detalle="con folios en curso" />
        <KPI titulo="Alertas abiertas" valor={String(j.alertas_abiertas)} detalle="sin atender" />
        <KPI titulo="Atención promedio" valor={`${j.tiempo_promedio_atencion_horas} h`} detalle="de inicio a cierre" />
      </div>
      <p className="mt-2 text-xs text-slate-500">{j.aviso_fase_2}</p>
      {d.folios_por_estado && <EstadosGrafica estados={d.folios_por_estado} />}
    </Tarjeta>
  )
}

function EstadosGrafica({ estados }: { estados: Record<string, number> }) {
  const filas = Object.entries(estados).map(([estado, n]) => ({ estado, n }))
  if (filas.length === 0) return <p className="text-sm text-slate-500">Sin folios en el período.</p>
  return (
    <div className="mt-3">
      <div className="h-48" aria-hidden="true">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={filas}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="estado" tick={{ fontSize: 11 }} />
            <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
            <Tooltip />
            <Bar dataKey="n" name="Folios" fill={COLORES[0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <ul className="mt-1 flex flex-wrap gap-x-4 text-xs text-slate-600" data-testid="folios-por-estado">
        {filas.map((f) => <li key={f.estado}>{f.estado}: <strong>{f.n}</strong></li>)}
      </ul>
    </div>
  )
}

function SeveridadGrafica({ severidades }: { severidades: Record<string, number> }) {
  const filas = Object.entries(severidades).map(([nombre, n]) => ({ nombre, n }))
  if (filas.length === 0) return <p className="text-sm text-slate-500">Sin folios con severidad en el período.</p>
  return (
    <div>
      <div className="h-48" aria-hidden="true">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={filas} dataKey="n" nameKey="nombre" outerRadius={70}>
              {filas.map((_, i) => <Cell key={i} fill={COLORES[i % COLORES.length]} />)}
            </Pie>
            <Legend />
            <Tooltip />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <ul className="mt-1 flex flex-wrap gap-x-4 text-xs text-slate-600" data-testid="folios-por-severidad">
        {filas.map((f) => <li key={f.nombre}>{f.nombre}: <strong>{f.n}</strong></li>)}
      </ul>
    </div>
  )
}

function Jerarquia({ titulo, filas, testid }: { titulo: string; filas: NivelJerarquia[]; testid: string }) {
  if (filas.length === 0) return null
  const datos = filas.map((f) => ({ nombre: f.nombre, cumplimiento: Number(f.sla_resolucion_pct), folios: f.folios }))
  return (
    <Tarjeta titulo={titulo}>
      <div className="h-56" aria-hidden="true">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={datos} layout="vertical" margin={{ left: 60 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 11 }} />
            <YAxis type="category" dataKey="nombre" tick={{ fontSize: 10 }} width={120} />
            <Tooltip />
            <Bar dataKey="cumplimiento" name="Cumplimiento de resolución %" fill={COLORES[1]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div data-testid={testid}>
        <Tabla filas={filas} vacio="Sin datos" columnas={[
          { titulo: 'Nivel', celda: (f) => f.nombre },
          { titulo: 'Folios', celda: (f) => f.folios },
          { titulo: 'Cerrados', celda: (f) => f.cerrados },
          { titulo: 'Resolución', celda: (f) => `${f.sla_resolucion_pct} %` },
          { titulo: 'Costo', celda: (f) => moneda(f.costo) },
        ]} />
      </div>
    </Tarjeta>
  )
}

/** F2-05 (§6.9.3): distribución por nivel, activos A sin plan y acciones vencidas. Es el estado de hoy del parque,
 * así que no lleva comparativo contra el período anterior. */
function Criticidad({ d }: { d: Tablero }) {
  const c = d.criticidad!
  const NIVELES: ('A' | 'B' | 'C' | 'D')[] = ['A', 'B', 'C', 'D']
  const ETIQUETA: Record<string, string> = { A: 'Crítico', B: 'Importante', C: 'Estándar', D: 'No crítico' }
  return (
    <Tarjeta titulo="Gestión de activos ISO 55000"
      acciones={<Link className="text-xs text-primario underline" to="/iso55000">Ver el módulo</Link>}>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" data-testid="criticidad-tablero">
        {NIVELES.map((n) => (
          <KPI key={n} titulo={`Nivel ${n} · ${ETIQUETA[n]}`} valor={String(c.por_nivel[n] ?? 0)}
            detalle={`de ${c.total} activo(s) evaluados`} />
        ))}
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <KPI titulo="Activos A sin plan" valor={String(c.criticos_sin_plan)} detalle="§6.9.3 pide PM obligatorio con plan" />
        <KPI titulo="Mitigaciones vencidas" valor={String(c.mitigaciones_vencidas)} detalle="Acciones comprometidas sin implementar" />
        <KPI titulo="Revisiones vencidas" valor={String(c.revisiones_vencidas)} detalle="Clasificación por revisar" />
      </div>
    </Tarjeta>
  )
}

function CumplimientoTabla({ d }: { d: Tablero }) {
  const sla = d.cumplimiento_sla!
  return (
    <Tarjeta titulo="Cumplimiento de SLA">
      <div className="grid gap-3 sm:grid-cols-3">
        <KPI titulo="Folios medidos" valor={String(sla.total)} />
        <KPI titulo="Respuesta" valor={`${sla.respuesta_pct} %`} />
        <KPI titulo="Resolución" valor={`${sla.resolucion_pct} %`} />
      </div>
      <table className="mt-3 w-full text-xs" data-testid="sla-por-severidad">
        <thead className="text-slate-500"><tr><th className="text-left">Severidad</th><th>Folios</th><th>Respuesta</th><th>Resolución</th><th>Penalizados</th></tr></thead>
        <tbody>{Object.entries(sla.por_severidad).map(([nombre, v]) => (
          <tr key={nombre}><td className="py-0.5">{nombre}</td><td className="text-center">{v.total}</td>
            <td className="text-center">{v.respuesta_pct} %</td><td className="text-center">{v.resolucion_pct} %</td>
            <td className="text-center">{v.penalizados}</td></tr>
        ))}</tbody>
      </table>
    </Tarjeta>
  )
}

function TableroCliente({ d }: { d: Tablero }) {
  const anterior = d.comparativo_periodo?.anterior
  const variacion = (actual: number, previo: number | undefined) =>
    previo == null || previo === 0 ? null : ((actual - previo) / previo) * 100
  const cerrados = d.folios_por_estado?.cerrado ?? 0
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <KPI titulo="Gasto contra presupuesto" valor={`${d.gasto_vs_presupuesto?.porcentaje ?? '0'} %`}
          detalle={`${moneda(d.gasto_vs_presupuesto?.consumido)} de ${moneda(d.gasto_vs_presupuesto?.monto)}`} />
        <KPI titulo="Disponible" valor={moneda(d.gasto_vs_presupuesto?.disponible)} />
        <KPI titulo="MTTR" valor={`${d.mttr?.horas ?? '0'} h`} detalle={`${d.mttr?.folios ?? 0} correctivos cerrados`} />
        <KPI titulo="MTBF" valor={`${d.mtbf?.horas ?? '0'} h`} detalle={d.mtbf?.aviso || `${d.mtbf?.equipos ?? 0} equipos`} />
        <KPI titulo="Folios cerrados" valor={String(cerrados)} variacion={variacion(cerrados, anterior?.cerrados)} />
        <KPI titulo="Costo del período" valor={moneda(d.costo?.total)} />
        <KPI titulo="Preventivos" valor={`${d.preventivos?.cumplimiento_pct ?? '0'} %`}
          detalle={`${d.preventivos?.ejecutados ?? 0} de ${d.preventivos?.programados ?? 0} · desvío ${d.preventivos?.desvio_promedio_dias ?? '0'} días`} />
        <KPI titulo="Hallazgos cotizados" valor={`${d.hallazgos?.conversion_pct ?? '0'} %`}
          detalle={`${d.hallazgos?.convertidos_a_cotizacion ?? 0} de ${d.hallazgos?.total ?? 0}`} />
      </div>
      {d.calificacion_admin_un && (
        <Aviso tipo="info">Tu calificación del período {d.calificacion_admin_un.periodo}: <strong>{d.calificacion_admin_un.calificacion}</strong> ·
          {' '}{d.calificacion_admin_un.clasificados_en_plazo} folios clasificados en plazo, {d.calificacion_admin_un.tardios} tardíos.</Aviso>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        {d.folios_por_estado && <Tarjeta titulo="Folios por estado"><EstadosGrafica estados={d.folios_por_estado} /></Tarjeta>}
        {d.folios_por_severidad && <Tarjeta titulo="Distribución por severidad"><SeveridadGrafica severidades={d.folios_por_severidad} /></Tarjeta>}
      </div>
      {d.criticidad && d.criticidad.total > 0 && <Criticidad d={d} />}
      {d.cumplimiento_sla && <CumplimientoTabla d={d} />}
      {d.comparativo_periodo && <Comparativo d={d} />}
      {d.jerarquia && <Jerarquia titulo="Comparativo por grupo de unidades" filas={d.jerarquia.grupos} testid="jerarquia-grupos" />}
      {d.jerarquia && <Jerarquia titulo="Comparativo por unidad de negocio" filas={d.jerarquia.unidades} testid="jerarquia-unidades" />}
      <div className="grid gap-4 md:grid-cols-2">
        <Tarjeta titulo="Top 10 equipos por costo">
          <div data-testid="top-costo">
            <Tabla filas={(d.top_equipos_costo ?? []).map((x) => ({ ...x, id: x.equipo_id }))} vacio="Sin equipos con costo" columnas={[
              { titulo: 'Código', celda: (x) => <Link className="font-mono text-xs text-primario underline" to={`/activos/${x.equipo_id}`}>{x.codigo}</Link> },
              { titulo: 'Equipo', celda: (x) => <span className="text-sm">{x.nombre}</span> },
              { titulo: 'Costo', celda: (x) => moneda(x.valor) },
              { titulo: 'Fallas', celda: (x) => x.fallas },
            ]} />
          </div>
        </Tarjeta>
        <Tarjeta titulo="Top 10 equipos por número de fallas">
          <div data-testid="top-fallas">
            <Tabla filas={(d.top_equipos_fallas ?? []).map((x) => ({ ...x, id: x.equipo_id }))} vacio="Sin fallas en el período" columnas={[
              { titulo: 'Código', celda: (x) => <Link className="font-mono text-xs text-primario underline" to={`/activos/${x.equipo_id}`}>{x.codigo}</Link> },
              { titulo: 'Equipo', celda: (x) => <span className="text-sm">{x.nombre}</span> },
              { titulo: 'Fallas', celda: (x) => x.fallas },
            ]} />
          </div>
        </Tarjeta>
      </div>
      {d.trabajos_especiales && (
        <Tarjeta titulo="Trabajos especiales">
          <p className="text-sm">{d.trabajos_especiales.total} en el período · {d.trabajos_especiales.urgencias} de urgencia</p>
          <ul className="mt-1 flex flex-wrap gap-x-4 text-xs text-slate-600">
            {Object.entries(d.trabajos_especiales.por_estado).map(([e, n]) => <li key={e}>{e}: <strong>{n}</strong></li>)}
          </ul>
        </Tarjeta>
      )}
    </>
  )
}

function Comparativo({ d }: { d: Tablero }) {
  const c = d.comparativo_periodo!
  const filas = [
    { periodo: 'Actual', folios: d.folios_por_estado ? Object.values(d.folios_por_estado).reduce((a, b) => a + b, 0) : 0,
      cerrados: d.folios_por_estado?.cerrado ?? 0, resolucion: Number(d.cumplimiento_sla?.resolucion_pct ?? 0), costo: Number(d.costo?.total ?? 0) },
    { periodo: 'Anterior', folios: c.anterior.folios, cerrados: c.anterior.cerrados, resolucion: Number(c.anterior.sla_resolucion_pct), costo: Number(c.anterior.costo) },
    { periodo: 'Año anterior', folios: c.anio_anterior.folios, cerrados: c.anio_anterior.cerrados, resolucion: Number(c.anio_anterior.sla_resolucion_pct), costo: Number(c.anio_anterior.costo) },
  ]
  return (
    <Tarjeta titulo="Comparativo multi-período">
      <div className="h-56" aria-hidden="true">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={filas}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="periodo" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip />
            <Legend />
            <Line type="monotone" dataKey="cerrados" name="Folios cerrados" stroke={COLORES[0]} />
            <Line type="monotone" dataKey="resolucion" name="Cumplimiento %" stroke={COLORES[1]} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div data-testid="comparativo-periodos">
        <Tabla filas={filas.map((f) => ({ ...f, id: f.periodo }))} vacio="" columnas={[
          { titulo: 'Período', celda: (f) => f.periodo },
          { titulo: 'Folios', celda: (f) => f.folios },
          { titulo: 'Cerrados', celda: (f) => f.cerrados },
          { titulo: 'Resolución', celda: (f) => `${f.resolucion} %` },
          { titulo: 'Costo', celda: (f) => moneda(f.costo) },
        ]} />
      </div>
    </Tarjeta>
  )
}

function TableroSupervision({ d }: { d: Tablero }) {
  return (
    <>
      <div className="grid gap-4 md:grid-cols-2">
        {d.folios_por_estado && <Tarjeta titulo="Folios por estado"><EstadosGrafica estados={d.folios_por_estado} /></Tarjeta>}
        {d.folios_por_severidad && <Tarjeta titulo="Distribución por severidad"><SeveridadGrafica severidades={d.folios_por_severidad} /></Tarjeta>}
      </div>
      <Tarjeta titulo="SLA en riesgo">
        <div data-testid="sla-en-riesgo">
          <Tabla filas={(d.sla_en_riesgo ?? []).map((a) => ({ ...a, id: a.id }))} vacio="Sin alertas de SLA en riesgo" columnas={[
            { titulo: 'Alerta', celda: (a) => <span className="font-mono text-xs">{a.clave}</span> },
            { titulo: 'Folio', celda: (a) => <span className="text-xs">{String(a.datos.numero_folio ?? '—')}</span> },
            { titulo: 'Disparo', celda: (a) => <span className="text-xs">{fmtFecha(a.disparo)}</span> },
            { titulo: 'Estado', celda: (a) => <Insignia tono={a.atendida ? 'ok' : 'alerta'}>{a.atendida ? 'Atendida' : 'Abierta'}</Insignia> },
          ]} />
        </div>
      </Tarjeta>
    </>
  )
}

function TableroPrestador({ d }: { d: Tablero }) {
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <KPI titulo="Cumplimiento de resolución" valor={`${d.cumplimiento_sla?.resolucion_pct ?? '0'} %`}
          detalle={`${d.cumplimiento_sla?.total ?? 0} folios medidos`} />
        <KPI titulo="Penalización del período" valor={moneda(d.penalizaciones?.monto)}
          detalle={`${d.penalizaciones?.folios_incumplidos ?? 0} folios incumplidos`} />
        <KPI titulo="Cotizaciones" valor={`${d.cotizaciones?.conversion_pct ?? '0'} %`}
          detalle={`${d.cotizaciones?.autorizadas ?? 0} de ${d.cotizaciones?.total ?? 0} · ${moneda(d.cotizaciones?.monto_autorizado)}`} />
        <KPI titulo="MTTR" valor={`${d.mttr?.horas ?? '0'} h`} />
      </div>
      {d.cumplimiento_sla && <CumplimientoTabla d={d} />}
      <Tarjeta titulo="Folios por cliente">
        <div data-testid="folios-por-cliente">
          <Tabla filas={(d.folios_por_cliente ?? []).map((x) => ({ ...x, id: x.cliente }))} vacio="Sin folios en el período" columnas={[
            { titulo: 'Cliente', celda: (x) => x.cliente },
            { titulo: 'Total', celda: (x) => x.total },
            { titulo: 'Cerrados', celda: (x) => x.por_estado.cerrado ?? 0 },
            { titulo: 'Abiertos', celda: (x) => x.total - (x.por_estado.cerrado ?? 0) - (x.por_estado.cancelado ?? 0) },
          ]} />
        </div>
      </Tarjeta>
      {(d.iguala ?? []).length > 0 && (
        <Tarjeta titulo="Consumo de iguala">
          <ul className="space-y-1 text-sm" data-testid="iguala-tablero">{(d.iguala ?? []).map((x) => (
            <li key={`${x.contrato}-${x.periodo}`}>{x.contrato} · {x.periodo}: correctivos {x.correctivos_atendidos} de {x.correctivos_incluidos}
              {x.correctivos_adicionales > 0 && <strong className="text-red-700"> · {x.correctivos_adicionales} adicionales</strong>}
              {' '}· preventivos {x.preventivos_ejecutados} de {x.preventivos_incluidos}</li>
          ))}</ul>
        </Tarjeta>
      )}
      {d.criticidad && d.criticidad.total > 0 && <Criticidad d={d} />}
      <Tarjeta titulo="Carga de trabajo por técnico">
        <div className="h-56" aria-hidden="true">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={(d.carga_por_tecnico ?? []).map((t) => ({ nombre: t.nombre, asignados: t.asignados, cerrados: t.cerrados }))}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="nombre" tick={{ fontSize: 10 }} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
              <Tooltip />
              <Legend />
              <Bar dataKey="asignados" name="Asignados" fill={COLORES[0]} />
              <Bar dataKey="cerrados" name="Cerrados" fill={COLORES[1]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div data-testid="carga-tecnicos">
          <Tabla filas={(d.carga_por_tecnico ?? []).map((x) => ({ ...x, id: x.tecnico_id }))} vacio="Sin folios asignados" columnas={[
            { titulo: 'Técnico', celda: (x) => x.nombre },
            { titulo: 'Asignados', celda: (x) => x.asignados },
            { titulo: 'Cerrados', celda: (x) => x.cerrados },
          ]} />
        </div>
        <p className="mt-1 text-xs text-slate-500">La productividad y la venta por técnico llegan en Fase 2.</p>
      </Tarjeta>
      <div className="grid gap-4 md:grid-cols-2">
        <Tarjeta titulo="Preventivos">
          <p className="text-sm">{d.preventivos?.ejecutados ?? 0} de {d.preventivos?.programados ?? 0} ejecutados
            ({d.preventivos?.cumplimiento_pct ?? '0'} %) · desvío promedio {d.preventivos?.desvio_promedio_dias ?? '0'} días</p>
        </Tarjeta>
        <Tarjeta titulo="Inventario y caja chica">
          <ul className="text-sm" data-testid="inventario-tablero">
            <li>{d.inventario_y_caja?.existencias_bajo_minimo ?? 0} existencias en o bajo el mínimo</li>
            <li>{d.inventario_y_caja?.fondos ?? 0} fondos con {moneda(d.inventario_y_caja?.saldo_fondos)} de saldo</li>
            <li>{d.inventario_y_caja?.gastos ?? 0} gastos por {moneda(d.inventario_y_caja?.monto_gastos)} · {d.inventario_y_caja?.gastos_por_aprobar ?? 0} por aprobar</li>
          </ul>
        </Tarjeta>
      </div>
      {d.comparativo_periodo && <Comparativo d={d} />}
    </>
  )
}

function TableroDireccion({ d }: { d: Tablero }) {
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-3">
        <KPI titulo="Cumplimiento de resolución" valor={`${d.cumplimiento_sla?.resolucion_pct ?? '0'} %`} />
        <KPI titulo="Penalización acumulada" valor={moneda(d.penalizaciones?.monto)} />
        <KPI titulo="Costo del período" valor={moneda(d.costo?.total)} />
      </div>
      {d.folios_por_estado && <Tarjeta titulo="Folios por estado"><EstadosGrafica estados={d.folios_por_estado} /></Tarjeta>}
      <Tarjeta titulo="Histórico de alertas de escalación">
        <div data-testid="escalaciones-direccion">
          <Tabla filas={(d.escalaciones ?? []).map((a) => ({ ...a, id: a.id }))} vacio="Sin escalaciones en el período" columnas={[
            { titulo: 'Alerta', celda: (a) => <span className="font-mono text-xs">{a.clave}</span> },
            { titulo: 'Origen', celda: (a) => <span className="text-xs">{String(a.datos.clave_origen ?? '—')}</span> },
            { titulo: 'Disparo', celda: (a) => <span className="text-xs">{fmtFecha(a.disparo)}</span> },
            { titulo: 'Estado', celda: (a) => <Insignia tono={a.atendida ? 'ok' : 'alerta'}>{a.atendida ? 'Atendida' : 'Abierta'}</Insignia> },
          ]} />
        </div>
      </Tarjeta>
      {d.comparativo_periodo && <Comparativo d={d} />}
    </>
  )
}
