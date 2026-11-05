import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { Aviso, Boton, Campo, Encabezado, Insignia, Modal, Selector, Tabla, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { useRecurso } from '../../hooks/useRecurso'
import { api, mensajeDeError } from '../../services/api'
import { abrirBlob } from '../../services/minutas'
import {
  aceptarTE, cambiarEstadoTE, cancelarTE, cerrarTE, cotizacionRetroactiva, crearTE, descargarReporteTE, enviarTE, iniciarTE, listarTE, obtenerTE, programarTE, rechazarTE, reporteTE,
  tecnicosDelPrestador,
} from '../../services/trabajos_especiales'
import type { Tecnico, Tenant, UnidadNegocio } from '../../types/api'
import type { EstadoTE, ReporteTE, TrabajoEspecial, TrabajoEspecialDetalle } from '../../types/trabajos_especiales'
import { ESTADOS_TE, FINALES_TE, NOMBRE_ESTADO_TE, ROLES_CREAN_TE, ROLES_KANBAN_TE, ROLES_URGENCIA } from '../../types/trabajos_especiales'
import { fecha as fmtFecha } from '../folios/comunes'

type Vista = 'listado' | 'kanban' | 'por_validar' | 'reporte'

function Urgencia({ te }: { te: { urgencia: boolean } }) {
  return te.urgencia ? <Insignia tono="alerta">Urgencia</Insignia> : null
}

/** Módulo de trabajos especiales (§6.10.6): listado filtrable, Kanban del prestador, bandeja «por validar» del cliente, detalle con acciones por rol y reporte. */
export function TrabajosEspeciales() {
  const { usuario } = useAuth()
  const [params, setParams] = useSearchParams()
  const esPrestador = usuario?.dominio === 'prestador' || usuario?.rol === 'superadmin'
  const esCliente = usuario?.dominio === 'tenant'
  const vista = (params.get('vista') as Vista) || (esCliente ? 'por_validar' : 'listado')
  const registroId = params.get('registro')
  const [filtros, setFiltros] = useState({ tenant_id: '', un_id: '', estado: '', urgencia: '', desde: '', hasta: '' })
  const [registros, setRegistros] = useState<TrabajoEspecial[]>([])
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [creando, setCreando] = useState(false)
  const tenants = useRecurso<Tenant[]>(esPrestador ? '/tenants' : null)
  const unidades = useRecurso<UnidadNegocio[]>('/unidades-negocio', { tenant_id: filtros.tenant_id || undefined })

  const cargar = useCallback(async () => {
    try {
      const limpios = Object.fromEntries(Object.entries(filtros).filter(([, v]) => v))
      setRegistros(await listarTE(vista === 'por_validar' ? { ...limpios, por_validar: true } : limpios))
    } catch (e) { setError(mensajeDeError(e)) }
  }, [filtros, vista])
  useEffect(() => { void cargar() }, [cargar])

  function ir(cambios: Record<string, string | null>) {
    const p = new URLSearchParams(params)
    for (const [k, v] of Object.entries(cambios)) { if (v) p.set(k, v); else p.delete(k) }
    setParams(p)
  }
  if (!usuario) return null
  const puedeKanban = ROLES_KANBAN_TE.includes(usuario.rol)
  const puedeCrear = ROLES_CREAN_TE.includes(usuario.rol) || ROLES_URGENCIA.includes(usuario.rol)
  const vistas: { v: Vista; texto: string }[] = [
    { v: 'listado', texto: 'Listado' }, ...(puedeKanban ? [{ v: 'kanban' as Vista, texto: 'Tablero Kanban' }] : []),
    ...(esCliente ? [{ v: 'por_validar' as Vista, texto: 'Por validar' }] : []), { v: 'reporte', texto: 'Reporte' },
  ]

  return (
    <div>
      <Encabezado titulo="Trabajos especiales" descripcion="Servicios fuera del mantenimiento regular: creación, validación del cliente por botón, programación, ejecución con formulario propio y cierre con evidencia y firma. Los TE de urgencia nacen del cliente sin monto."
        acciones={puedeCrear ? <Boton onClick={() => setCreando(true)}>{esCliente ? 'Crear TE de urgencia' : 'Nuevo trabajo especial'}</Boton> : undefined} />
      <div className="mb-3 flex flex-wrap gap-1" role="tablist" aria-label="Vistas">
        {vistas.map(({ v, texto }) => <button key={v} role="tab" aria-selected={vista === v} className={`rounded-lg px-3 py-1.5 text-sm ${vista === v ? 'bg-primario text-white' : 'border border-slate-300'}`} onClick={() => ir({ vista: v, registro: null })}>{texto}</button>)}
      </div>
      {vista !== 'reporte' && (
        <div className="mb-4 flex flex-wrap items-end gap-2">
          {esPrestador && <Selector etiqueta="Cliente" value={filtros.tenant_id} onChange={(e) => setFiltros({ ...filtros, tenant_id: e.target.value, un_id: '' })} opciones={[{ valor: '', texto: 'Todos' }, ...(tenants.datos ?? []).map((t) => ({ valor: t.id, texto: t.razon_social }))]} />}
          <Selector etiqueta="UN" value={filtros.un_id} onChange={(e) => setFiltros({ ...filtros, un_id: e.target.value })} opciones={[{ valor: '', texto: 'Todas' }, ...(unidades.datos ?? []).map((u) => ({ valor: u.id, texto: `${u.codigo} · ${u.nombre}` }))]} />
          {vista !== 'por_validar' && <Selector etiqueta="Estado" value={filtros.estado} onChange={(e) => setFiltros({ ...filtros, estado: e.target.value })} opciones={[{ valor: '', texto: 'Todos' }, ...ESTADOS_TE.map((e) => ({ valor: e, texto: NOMBRE_ESTADO_TE[e] }))]} />}
          <Selector etiqueta="Urgencia" value={filtros.urgencia} onChange={(e) => setFiltros({ ...filtros, urgencia: e.target.value })} opciones={[{ valor: '', texto: 'Todos' }, { valor: 'true', texto: 'Solo urgencias' }, { valor: 'false', texto: 'Sin urgencias' }]} />
          <Campo etiqueta="Desde" type="date" value={filtros.desde} onChange={(e) => setFiltros({ ...filtros, desde: e.target.value })} />
          <Campo etiqueta="Hasta" type="date" value={filtros.hasta} onChange={(e) => setFiltros({ ...filtros, hasta: e.target.value })} />
        </div>
      )}
      {error && <div className="mb-3"><Aviso>{error}</Aviso></div>}
      {aviso && <div className="mb-3"><Aviso tipo="exito">{aviso}</Aviso></div>}

      {(vista === 'listado' || vista === 'por_validar') && (
        <div className="rounded-xl border border-slate-200 bg-white p-2">
          {vista === 'por_validar' && <p className="px-2 pb-2 text-sm text-slate-600">Trabajos especiales enviados por el prestador que esperan tu aceptación o rechazo con comentario.</p>}
          <Tabla
            filas={registros}
            vacio={vista === 'por_validar' ? 'No tienes trabajos especiales por validar.' : 'Sin trabajos especiales'}
            columnas={[
              { titulo: 'Número', celda: (r) => <button className="text-left font-mono text-sm text-primario underline" onClick={() => ir({ registro: r.id })}>{r.numero}</button> },
              { titulo: 'Descripción', celda: (r) => <span className="text-sm">{r.descripcion.slice(0, 80)} <Urgencia te={r} /></span> },
              { titulo: 'UN / equipo', celda: (r) => <span>{r.un_codigo} <span className="text-xs text-slate-500">{r.equipo_codigo ?? ''}</span></span> },
              { titulo: 'Estado', celda: (r) => <div className="flex flex-wrap gap-1"><Insignia tono={r.alertas_activas.length ? 'alerta' : FINALES_TE.has(r.estado) ? 'ok' : 'acento'}>{NOMBRE_ESTADO_TE[r.estado]}</Insignia>{r.version_enviada > 1 && <Insignia>v{r.version_enviada}</Insignia>}</div> },
              { titulo: 'Monto', celda: (r) => r.monto ? `$${Number(r.monto).toLocaleString('es-MX')}` : <span className="text-xs text-slate-400">{r.urgencia ? 'sin monto (urgencia)' : '—'}</span> },
              { titulo: 'Fecha programada', celda: (r) => <span className="text-xs">{r.fecha_programada ?? '—'}</span> },
              { titulo: 'Días en el estado', celda: (r) => <span className={r.alertas_activas.length ? 'font-semibold text-red-700' : ''}>{r.dias_en_estado}</span> },
            ]}
          />
        </div>
      )}
      {vista === 'kanban' && puedeKanban && <Kanban registros={registros} alAbrir={(id) => ir({ registro: id })} alMover={async (r, estado) => { try { await cambiarEstadoTE(r.id, estado); setAviso(`${r.numero} → ${NOMBRE_ESTADO_TE[estado as EstadoTE]}`); await cargar() } catch (e) { setError(mensajeDeError(e)) } }} />}
      {vista === 'reporte' && <Reporte tenantId={filtros.tenant_id || undefined} />}
      {creando && <CrearTE urgencia={!!esCliente} unidades={unidades.datos ?? []} tenants={tenants.datos ?? []} alCerrar={() => setCreando(false)} alCrear={async (te) => { setCreando(false); setAviso(`${te.numero} creado`); await cargar(); ir({ registro: te.id }) }} />}
      {registroId && <DetalleTE registroId={registroId} alCerrar={() => ir({ registro: null })} alCambiar={async (texto) => { setAviso(texto); await cargar() }} />}
    </div>
  )
}

function Kanban({ registros, alAbrir, alMover }: { registros: TrabajoEspecial[]; alAbrir: (id: string) => void; alMover: (r: TrabajoEspecial, estado: string) => Promise<void> }) {
  const [arrastrando, setArrastrando] = useState<TrabajoEspecial | null>(null)
  return (
    <div className="flex gap-3 overflow-x-auto pb-2" data-testid="kanban-te">
      {ESTADOS_TE.map((estado) => (
        <section key={estado} aria-label={NOMBRE_ESTADO_TE[estado]} className="w-64 shrink-0 rounded-xl bg-slate-100 p-2"
          onDragOver={(e) => e.preventDefault()} onDrop={() => { if (arrastrando && arrastrando.estado !== estado) void alMover(arrastrando, estado); setArrastrando(null) }}>
          <h2 className="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-slate-600">{NOMBRE_ESTADO_TE[estado]} <span className="text-slate-400">{registros.filter((r) => r.estado === estado).length}</span></h2>
          <div className="space-y-2">
            {registros.filter((r) => r.estado === estado).map((r) => (
              <article key={r.id} draggable onDragStart={() => setArrastrando(r)} data-testid={`tarjeta-te-${r.id}`}
                className={`rounded-lg border bg-white p-2 text-sm shadow-sm ${r.alertas_activas.length ? 'border-red-400 bg-red-50' : 'border-slate-200'}`}>
                <button className="font-mono text-xs font-semibold text-primario underline" onClick={() => alAbrir(r.id)}>{r.numero}</button> <Urgencia te={r} />
                <p className="text-slate-700">{r.descripcion.slice(0, 70)}</p>
                <p className="text-xs text-slate-500">{r.un_codigo} · {r.dias_en_estado} d{r.alertas_activas.length ? ` · ${r.alertas_activas.join(', ')}` : ''}</p>
                {r.destinos.length > 0 && (
                  <select aria-label={`Mover ${r.numero}`} className="mt-1 w-full rounded border border-slate-300 text-xs" value="" onChange={(e) => { if (e.target.value) void alMover(r, e.target.value) }}>
                    <option value="">Mover a…</option>
                    {r.destinos.filter((d) => d !== 'programado' && d !== 'cancelado').map((d) => <option key={d} value={d}>{NOMBRE_ESTADO_TE[d as EstadoTE] ?? d}</option>)}
                  </select>
                )}
              </article>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}

function Reporte({ tenantId }: { tenantId?: string }) {
  const [r, setR] = useState<ReporteTE | null>(null)
  const [rango, setRango] = useState({ desde: '', hasta: '' })
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { reporteTE({ tenant_id: tenantId, desde: rango.desde || undefined, hasta: rango.hasta || undefined }).then(setR).catch((e) => setError(mensajeDeError(e))) }, [tenantId, rango])
  return (
    <div className="space-y-4" data-testid="reporte-te">
      <div className="flex flex-wrap items-end gap-2">
        <Campo etiqueta="Desde" type="date" value={rango.desde} onChange={(e) => setRango({ ...rango, desde: e.target.value })} />
        <Campo etiqueta="Hasta" type="date" value={rango.hasta} onChange={(e) => setRango({ ...rango, hasta: e.target.value })} />
        <Boton variante="secundario" onClick={() => void descargarReporteTE('xlsx', { tenant_id: tenantId, desde: rango.desde || undefined, hasta: rango.hasta || undefined }).then((b) => abrirBlob(b, 'trabajos-especiales.xlsx')).catch((e) => setError(mensajeDeError(e)))}>Exportar Excel</Boton>
        <Boton variante="secundario" onClick={() => void descargarReporteTE('pdf', { tenant_id: tenantId, desde: rango.desde || undefined, hasta: rango.hasta || undefined }).then((b) => abrirBlob(b, 'trabajos-especiales.pdf')).catch((e) => setError(mensajeDeError(e)))}>Exportar PDF</Boton>
      </div>
      {error && <Aviso>{error}</Aviso>}
      {r && (
        <div className="grid gap-4 md:grid-cols-2">
          <Tarjeta titulo="Totales">
            <p className="text-sm">{r.total} trabajos especiales · {r.urgencias} urgencias ({`${r.porcentaje_urgencias}%`}) · monto total ${Number(r.monto_total).toLocaleString('es-MX')}</p>
            <p className="text-xs text-slate-500">{r.sin_cotizacion_retroactiva} urgencias cerradas sin cotización retroactiva</p>
            <ul className="mt-2 text-sm">{Object.entries(r.por_estado).map(([k, v]) => <li key={k}>{NOMBRE_ESTADO_TE[k as EstadoTE] ?? k}: {v}</li>)}</ul>
          </Tarjeta>
          <Tarjeta titulo="Tiempo promedio por etapa (días)">
            <ul className="text-sm">{Object.entries(r.tiempo_promedio_etapas_dias).map(([k, v]) => <li key={k}>{k.replaceAll('_', ' ')}: {v ?? '—'}</li>)}</ul>
          </Tarjeta>
        </div>
      )}
    </div>
  )
}

function CrearTE({ urgencia, unidades, tenants, alCerrar, alCrear }: { urgencia: boolean; unidades: UnidadNegocio[]; tenants: Tenant[]; alCerrar: () => void; alCrear: (te: TrabajoEspecial) => Promise<void> }) {
  const { usuario } = useAuth()
  const [d, setD] = useState({ un_id: '', descripcion: '', monto: '', tenant_id: '' })
  const [error, setError] = useState<string | null>(null)
  const [uns, setUns] = useState<UnidadNegocio[]>(unidades)
  const [equipos, setEquipos] = useState<{ id: string; codigo: string; nombre: string }[]>([])
  const [equipoId, setEquipoId] = useState('')
  useEffect(() => { if (usuario?.rol === 'superadmin' && d.tenant_id) api<UnidadNegocio[]>('/unidades-negocio', { params: { tenant_id: d.tenant_id } }).then(setUns).catch(() => undefined) }, [d.tenant_id, usuario])
  useEffect(() => { if (d.un_id) api<{ id: string; codigo: string; nombre: string }[]>('/catalogos/equipos', { params: { un_id: d.un_id } }).then(setEquipos).catch(() => setEquipos([])) }, [d.un_id])
  async function guardar() {
    setError(null)
    try { await alCrear(await crearTE({ un_id: d.un_id, descripcion: d.descripcion, monto: urgencia || !d.monto ? null : d.monto, urgencia, equipo_id: equipoId || null, tenant_id: d.tenant_id || null })) } catch (e) { setError(mensajeDeError(e)) }
  }
  return (
    <Modal titulo={urgencia ? 'Trabajo especial de urgencia' : 'Nuevo trabajo especial'} abierto alCerrar={alCerrar}>
      <div className="space-y-3" data-testid="crear-te">
        {urgencia && <Aviso tipo="info">El TE de urgencia no lleva monto: el prestador puede programarlo de inmediato y, si lo pides, formalizar después una cotización retroactiva.</Aviso>}
        {error && <Aviso>{error}</Aviso>}
        {usuario?.rol === 'superadmin' && <Selector etiqueta="Cliente" value={d.tenant_id} onChange={(e) => setD({ ...d, tenant_id: e.target.value, un_id: '' })} opciones={[{ valor: '', texto: 'Elegir…' }, ...tenants.map((t) => ({ valor: t.id, texto: t.razon_social }))]} />}
        <Selector etiqueta="Unidad de negocio" value={d.un_id} onChange={(e) => setD({ ...d, un_id: e.target.value })} opciones={[{ valor: '', texto: 'Elegir…' }, ...uns.map((u) => ({ valor: u.id, texto: `${u.codigo} · ${u.nombre}` }))]} />
        <Selector etiqueta="Equipo (opcional)" value={equipoId} onChange={(e) => setEquipoId(e.target.value)} opciones={[{ valor: '', texto: 'Sin equipo específico' }, ...equipos.map((e) => ({ valor: e.id, texto: `${e.codigo} · ${e.nombre}` }))]} />
        <Campo etiqueta="Descripción del trabajo" value={d.descripcion} onChange={(e) => setD({ ...d, descripcion: e.target.value })} />
        {!urgencia && <Campo etiqueta="Monto (MXN)" type="number" value={d.monto} onChange={(e) => setD({ ...d, monto: e.target.value })} />}
        <div className="flex gap-2"><Boton disabled={!d.un_id || d.descripcion.length < 5} onClick={() => void guardar()}>Crear</Boton><Boton variante="secundario" onClick={alCerrar}>Cancelar</Boton></div>
      </div>
    </Modal>
  )
}

function DetalleTE({ registroId, alCerrar, alCambiar }: { registroId: string; alCerrar: () => void; alCambiar: (texto: string) => Promise<void> }) {
  const { usuario } = useAuth()
  const [t, setT] = useState<TrabajoEspecialDetalle | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [campos, setCampos] = useState({ comentario: '', notas: '', monto: '', fecha: '', tecnicos: [] as string[], responsable: '', montoRetro: '' })
  const [tecnicos, setTecnicos] = useState<Tecnico[]>([])
  const cargar = useCallback(async () => { try { setT(await obtenerTE(registroId)) } catch (e) { setError(mensajeDeError(e)) } }, [registroId])
  useEffect(() => { void cargar() }, [cargar])
  const esPrestador = usuario?.dominio === 'prestador' || usuario?.rol === 'superadmin'
  useEffect(() => { if (esPrestador && t?.estado && ['aceptado', 'creado'].includes(t.estado)) tecnicosDelPrestador().then(setTecnicos).catch(() => setTecnicos([])) }, [esPrestador, t?.estado])
  if (!t || !usuario) return <Modal titulo="Trabajo especial" abierto alCerrar={alCerrar}>{error ? <Aviso>{error}</Aviso> : <p className="text-sm text-slate-500">Cargando…</p>}</Modal>
  const puede = (d: string) => t.destinos.includes(d)
  const esTecnico = usuario.rol === 'tecnico'
  async function ejecutar(fn: () => Promise<unknown>, texto: string) {
    setError(null)
    try { await fn(); await cargar(); await alCambiar(texto) } catch (e) { setError(mensajeDeError(e)) }
  }
  return (
    <Modal titulo={`${t.numero} · ${NOMBRE_ESTADO_TE[t.estado]}`} abierto alCerrar={alCerrar}>
      {error && <div className="mb-2"><Aviso>{error}</Aviso></div>}
      <div className="space-y-3 text-sm" data-testid="detalle-te">
        <div className="flex flex-wrap gap-1"><Insignia tono={FINALES_TE.has(t.estado) ? 'ok' : 'acento'}>{NOMBRE_ESTADO_TE[t.estado]}</Insignia><Urgencia te={t} />{t.version_enviada > 0 && <Insignia>versión enviada {t.version_enviada}</Insignia>}{t.alertas_activas.map((a) => <Insignia key={a} tono="alerta">{a}</Insignia>)}</div>
        <p className="text-slate-800">{t.descripcion}</p>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
          <dt className="text-slate-500">UN / equipo</dt><dd>{t.un_codigo} · {t.un_nombre}{t.equipo_codigo && ` · ${t.equipo_codigo} ${t.equipo_nombre ?? ''}`}</dd>
          <dt className="text-slate-500">Monto</dt><dd>{t.monto ? `$${Number(t.monto).toLocaleString('es-MX')} ${t.moneda}` : t.urgencia ? 'sin monto (urgencia; cotización retroactiva opcional)' : 'por definir'}</dd>
          <dt className="text-slate-500">Creado por</dt><dd>{t.creado_por_nombre ?? '—'} ({t.creado_por_rol}) · {fmtFecha(t.created_at)}</dd>
          <dt className="text-slate-500">Cotización</dt><dd>{t.cotizacion_id ? <Link className="text-primario underline" to={`/seguimiento?modulo=cotizaciones&registro=${t.cotizacion_id}`}>{t.cotizacion_numero} ({t.cotizacion_estado})</Link> : t.cotizacion_retroactiva_id ? <Link className="text-primario underline" to={`/seguimiento?modulo=cotizaciones&registro=${t.cotizacion_retroactiva_id}`}>{t.cotizacion_retroactiva_numero} (retroactiva)</Link> : '—'}</dd>
          <dt className="text-slate-500">Programación</dt><dd>{t.fecha_programada ?? 'sin fecha'}{t.tecnicos.length > 0 && ` · ${t.tecnicos.map((x) => x.nombre ?? x.id).join(', ')}`}{t.tecnico_responsable_nombre && ` (responsable: ${t.tecnico_responsable_nombre})`}</dd>
          <dt className="text-slate-500">Folio operativo</dt><dd>{t.folio_id ? <Link className="text-primario underline" to={`/folios/${t.folio_id}`}>{t.numero_folio} · {t.estado_folio}</Link> : 'se crea al programar'}</dd>
          {t.razon_cancelacion && <><dt className="text-slate-500">Cancelación</dt><dd>{t.razon_cancelacion}</dd></>}
        </dl>
        {t.respuestas_cliente.length > 0 && (
          <div><h3 className="text-xs font-semibold uppercase text-slate-500">Respuestas del cliente</h3>
            <ul className="text-xs text-slate-600" data-testid="respuestas-cliente">{t.respuestas_cliente.map((r) => <li key={r.id}>v{r.version_enviada} · {r.decision} · {r.respondido_por_nombre ?? '—'} · {fmtFecha(r.timestamp)} · {r.canal}{r.comentario && ` · «${r.comentario}»`}</li>)}</ul></div>
        )}
        {t.evidencias.length > 0 && <p className="text-xs text-slate-600">Evidencias: {t.evidencias.map((e) => e.tipo).join(', ')}</p>}
        {t.requisitos_cierre_faltantes.length > 0 && <p className="text-xs text-amber-700">Para cerrar faltan: {t.requisitos_cierre_faltantes.join(', ')}</p>}

        {/* Acciones por rol y estado */}
        {t.puede_responder && (
          <div className="rounded-lg border border-slate-200 p-2" data-testid="validacion-cliente">
            <p className="mb-1 font-medium">Validación del cliente</p>
            <Campo etiqueta="Comentario (obligatorio al rechazar)" value={campos.comentario} onChange={(e) => setCampos({ ...campos, comentario: e.target.value })} />
            <div className="mt-2 flex gap-2">
              <Boton onClick={() => void ejecutar(() => aceptarTE(t.id, campos.comentario), `${t.numero} aceptado`)}>Aceptar</Boton>
              <Boton variante="peligro" disabled={campos.comentario.trim().length < 5} onClick={() => void ejecutar(() => rechazarTE(t.id, campos.comentario), `${t.numero} rechazado`)}>Rechazar</Boton>
            </div>
          </div>
        )}
        {esPrestador && puede('enviado_cliente') && (
          <div className="rounded-lg border border-slate-200 p-2">
            <p className="mb-1 font-medium">{t.estado === 'rechazado' ? 'Modificar y reenviar' : 'Enviar al cliente para validación'}</p>
            <div className="grid gap-2 sm:grid-cols-2"><Campo etiqueta="Monto (MXN)" type="number" value={campos.monto} onChange={(e) => setCampos({ ...campos, monto: e.target.value })} /><Campo etiqueta="Notas" value={campos.notas} onChange={(e) => setCampos({ ...campos, notas: e.target.value })} /></div>
            <div className="mt-2"><Boton onClick={() => void ejecutar(() => enviarTE(t.id, { notas: campos.notas, monto: campos.monto || null }), `${t.numero} enviado al cliente`)}>{t.estado === 'rechazado' ? 'Reenviar' : 'Enviar al cliente'}</Boton></div>
          </div>
        )}
        {esPrestador && puede('programado') && (
          <div className="rounded-lg border border-slate-200 p-2" data-testid="programar-te">
            <p className="mb-1 font-medium">Programar{t.estado === 'creado' && t.urgencia ? ' (urgencia: sin validación del cliente)' : ''}</p>
            <div className="grid gap-2 sm:grid-cols-2">
              <Campo etiqueta="Fecha programada" type="date" value={campos.fecha} onChange={(e) => setCampos({ ...campos, fecha: e.target.value })} />
              <Selector etiqueta="Técnico responsable" value={campos.responsable} onChange={(e) => setCampos({ ...campos, responsable: e.target.value, tecnicos: Array.from(new Set([e.target.value, ...campos.tecnicos].filter(Boolean))) })} opciones={[{ valor: '', texto: 'Elegir…' }, ...tecnicos.map((x) => ({ valor: x.usuario_id, texto: x.nombre }))]} />
            </div>
            <fieldset className="mt-2"><legend className="text-xs text-slate-500">Técnicos adicionales</legend>
              <div className="flex flex-wrap gap-2">{tecnicos.filter((x) => x.usuario_id !== campos.responsable).map((x) => <label key={x.id} className="text-xs"><input type="checkbox" checked={campos.tecnicos.includes(x.usuario_id)} onChange={(e) => setCampos({ ...campos, tecnicos: e.target.checked ? [...campos.tecnicos, x.usuario_id] : campos.tecnicos.filter((id) => id !== x.usuario_id) })} /> {x.nombre}</label>)}</div></fieldset>
            <div className="mt-2"><Boton disabled={!campos.fecha || !campos.responsable} onClick={() => void ejecutar(() => programarTE(t.id, { fecha_programada: campos.fecha, tecnico_ids: Array.from(new Set([campos.responsable, ...campos.tecnicos])), tecnico_responsable_id: campos.responsable, notas: campos.notas }), `${t.numero} programado: el cliente recibe la confirmación de la fecha`)}>Programar</Boton></div>
          </div>
        )}
        {esTecnico && puede('en_ejecucion') && <Boton onClick={() => void ejecutar(() => iniciarTE(t.id, campos.notas), `${t.numero} en ejecución`)}>Iniciar ejecución</Boton>}
        {esTecnico && puede('cerrado') && <Boton disabled={t.requisitos_cierre_faltantes.length > 0} onClick={() => void ejecutar(() => cerrarTE(t.id, campos.notas), `${t.numero} cerrado`)}>Cerrar trabajo especial</Boton>}
        {esPrestador && t.urgencia && !t.cotizacion_id && !t.cotizacion_retroactiva_id && !['cancelado'].includes(t.estado) && (
          <div className="flex flex-wrap items-end gap-2"><Campo etiqueta="Monto de la cotización retroactiva" type="number" value={campos.montoRetro} onChange={(e) => setCampos({ ...campos, montoRetro: e.target.value })} /><Boton variante="secundario" onClick={() => void ejecutar(() => cotizacionRetroactiva(t.id, { monto: campos.montoRetro || null }), 'Cotización retroactiva creada')}>Crear cotización retroactiva</Boton></div>
        )}
        {puede('cancelado') && (
          <div className="flex flex-wrap items-end gap-2"><Campo etiqueta="Razón de cancelación" value={campos.notas} onChange={(e) => setCampos({ ...campos, notas: e.target.value })} /><Boton variante="peligro" disabled={campos.notas.trim().length < 5} onClick={() => void ejecutar(() => cancelarTE(t.id, campos.notas), `${t.numero} cancelado`)}>Cancelar TE</Boton></div>
        )}
        <div>
          <h3 className="text-xs font-semibold uppercase text-slate-500">Línea de tiempo</h3>
          <ul className="text-xs text-slate-600" data-testid="linea-tiempo-te">{t.historial.map((h) => <li key={h.id}>{fmtFecha(h.timestamp)} · {h.estado_anterior ? `${NOMBRE_ESTADO_TE[h.estado_anterior as EstadoTE] ?? h.estado_anterior} → ` : ''}{NOMBRE_ESTADO_TE[h.estado_nuevo as EstadoTE] ?? h.estado_nuevo} · {h.actor_nombre ?? h.actor_rol}{h.notas && ` · ${h.notas}`}</li>)}</ul>
        </div>
      </div>
    </Modal>
  )
}
