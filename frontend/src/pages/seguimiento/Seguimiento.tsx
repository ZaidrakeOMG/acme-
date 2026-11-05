import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { Aviso, Boton, Campo, Encabezado, Insignia, Modal, Selector, Tabla, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { useRecurso } from '../../hooks/useRecurso'
import { mensajeDeError } from '../../services/api'
import { abrirBlob, actualizarInterno, cambiarEstado, confirmarTercero, convertirCotizacion, descargarReporte, descartarPresupuesto, enviarCotizacion, enviarCotizacionExterno, listarModulo, obtenerRegistro, pdfCotizacion, porUN, prepararCotizacion, reactivarPresupuesto, reporteEjecutivo, responderCotizacion, revisarPresupuesto } from '../../services/minutas'
import type { Tenant, UnidadNegocio } from '../../types/api'
import type { CambioEstado, Modulo, RegistroSeguimiento, ReporteEjecutivo } from '../../types/minutas'
import { ESTADOS_MODULO, NOMBRE_ESTADO_MODULO, NOMBRE_MODULO, ROLES_KANBAN } from '../../types/minutas'
import { fecha as fmtFecha } from '../folios/comunes'

type Vista = 'listado' | 'kanban' | 'por_un' | 'reporte'
const MODULOS: Modulo[] = ['cotizaciones', 'presupuesto', 'interno', 'reprogramacion']
const FINALES = new Set(['resuelto', 'cancelado', 'descartado', 'convertida', 'rechazada', 'reactivado'])

/** Los cuatro módulos de seguimiento (§7.7–7.8): listado con filtros, Kanban, vista por UN y reporte ejecutivo. */
export function Seguimiento() {
  const { usuario } = useAuth()
  const [params, setParams] = useSearchParams()
  const modulo = (params.get('modulo') as Modulo) || 'cotizaciones'
  const vista = (params.get('vista') as Vista) || 'listado'
  const registroId = params.get('registro')
  const esPrestador = usuario?.dominio === 'prestador' || usuario?.rol === 'superadmin'
  const [filtros, setFiltros] = useState({ tenant_id: '', un_id: '', estado: '', desde: '', hasta: '', urgencia: '' })
  const [registros, setRegistros] = useState<RegistroSeguimiento[]>([])
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const tenants = useRecurso<Tenant[]>(esPrestador ? '/tenants' : null)
  const unidades = useRecurso<UnidadNegocio[]>('/unidades-negocio', { tenant_id: filtros.tenant_id || undefined })

  const cargar = useCallback(async () => {
    try { setRegistros(await listarModulo(modulo, { ...Object.fromEntries(Object.entries(filtros).filter(([, v]) => v)) })) } catch (e) { setError(mensajeDeError(e)) }
  }, [modulo, filtros])
  useEffect(() => { void cargar() }, [cargar])

  function ir(cambios: Record<string, string | null>) {
    const p = new URLSearchParams(params)
    for (const [k, v] of Object.entries(cambios)) { if (v) p.set(k, v); else p.delete(k) }
    setParams(p)
  }
  if (!usuario) return null
  const puedeKanban = ROLES_KANBAN.includes(usuario.rol)

  return (
    <div>
      <Encabezado titulo="Módulos de seguimiento" descripcion="Cotizaciones, Por presupuesto, Seguimiento interno y Reprogramación: cada registro muestra su estado, días en el estado y próxima alerta; las tarjetas en rojo tienen alertas activas." />
      <div className="mb-3 flex flex-wrap gap-1" role="tablist" aria-label="Módulos">
        {MODULOS.map((m) => <button key={m} role="tab" aria-selected={modulo === m} className={`rounded-lg px-3 py-1.5 text-sm ${modulo === m ? 'bg-primario text-white' : 'border border-slate-300'}`} onClick={() => ir({ modulo: m, registro: null })}>{NOMBRE_MODULO[m]}</button>)}
        <span className="mx-2 border-l border-slate-200" />
        {(['listado', 'kanban', 'por_un', 'reporte'] as Vista[]).filter((v) => v !== 'kanban' || puedeKanban).map((v) => (
          <button key={v} className={`rounded-lg px-3 py-1.5 text-sm ${vista === v ? 'bg-acento/40' : 'border border-slate-300'}`} onClick={() => ir({ vista: v })}>{{ listado: 'Listado', kanban: 'Tablero Kanban', por_un: 'Vista por UN', reporte: 'Reporte ejecutivo' }[v]}</button>
        ))}
      </div>
      {vista !== 'reporte' && (
        <div className="mb-4 flex flex-wrap items-end gap-2">
          {esPrestador && <Selector etiqueta="Cliente" value={filtros.tenant_id} onChange={(e) => setFiltros({ ...filtros, tenant_id: e.target.value, un_id: '' })} opciones={[{ valor: '', texto: 'Todos' }, ...(tenants.datos ?? []).map((t) => ({ valor: t.id, texto: t.razon_social }))]} />}
          <Selector etiqueta="UN" value={filtros.un_id} onChange={(e) => setFiltros({ ...filtros, un_id: e.target.value })} opciones={[{ valor: '', texto: 'Todas' }, ...(unidades.datos ?? []).map((u) => ({ valor: u.id, texto: `${u.codigo} · ${u.nombre}` }))]} />
          <Selector etiqueta="Estado" value={filtros.estado} onChange={(e) => setFiltros({ ...filtros, estado: e.target.value })} opciones={[{ valor: '', texto: 'Todos' }, ...ESTADOS_MODULO[modulo].map((e) => ({ valor: e, texto: NOMBRE_ESTADO_MODULO[e] ?? e }))]} />
          <Selector etiqueta="Urgencia del hallazgo" value={filtros.urgencia} onChange={(e) => setFiltros({ ...filtros, urgencia: e.target.value })} opciones={[{ valor: '', texto: 'Todas' }, ...['baja', 'media', 'alta', 'critica'].map((u) => ({ valor: u, texto: u }))]} />
          <Campo etiqueta="Desde" type="date" value={filtros.desde} onChange={(e) => setFiltros({ ...filtros, desde: e.target.value })} />
          <Campo etiqueta="Hasta" type="date" value={filtros.hasta} onChange={(e) => setFiltros({ ...filtros, hasta: e.target.value })} />
        </div>
      )}
      {error && <div className="mb-3"><Aviso>{error}</Aviso></div>}
      {aviso && <div className="mb-3"><Aviso tipo="exito">{aviso}</Aviso></div>}

      {vista === 'listado' && (
        <div className="rounded-xl border border-slate-200 bg-white p-2">
          <Tabla
            filas={registros}
            vacio="Sin registros"
            columnas={[
              { titulo: modulo === 'cotizaciones' ? 'Número' : 'Registro', celda: (r) => <button className="text-left text-sm text-primario underline" onClick={() => ir({ registro: r.id })}>{r.numero ?? r.descripcion.slice(0, 60)}</button> },
              { titulo: 'UN / equipo', celda: (r) => <span>{r.un_codigo} <span className="text-xs text-slate-500">{r.equipo_codigo ?? ''}</span></span> },
              { titulo: 'Estado', celda: (r) => <div className="flex flex-wrap gap-1"><Insignia tono={r.alertas_activas.length ? 'alerta' : FINALES.has(r.estado) ? 'ok' : 'acento'}>{NOMBRE_ESTADO_MODULO[r.estado] ?? r.estado}</Insignia>{r.urgencia_hallazgo && <Insignia>{r.urgencia_hallazgo}</Insignia>}</div> },
              { titulo: 'Días en el estado', celda: (r) => <span className={r.alertas_activas.length ? 'font-semibold text-red-700' : ''}>{r.dias_en_estado}</span> },
              { titulo: 'Próxima alerta', celda: (r) => <span className="text-xs text-slate-600">{r.alertas_activas.length ? <span className="text-red-700">{r.alertas_activas.join(', ')}</span> : r.proxima_alerta ?? '—'}</span> },
              ...(modulo === 'cotizaciones' ? [{ titulo: 'Monto', celda: (r: RegistroSeguimiento) => r.monto ? `$${Number(r.monto).toLocaleString('es-MX')}` : '—' }, { titulo: 'Estado del trabajo especial', celda: (r: RegistroSeguimiento) => <span className="text-xs text-slate-400">{r.trabajo_especial_numero ? `${r.trabajo_especial_numero} · ${r.estado_trabajo_especial}` : ''}</span> }] : []),
            ]}
          />
        </div>
      )}
      {vista === 'kanban' && puedeKanban && <Kanban modulo={modulo} registros={registros} alCambiar={async (r, estado) => { try { await cambiarEstado(modulo, r.id, { estado }); setAviso(`${r.numero ?? r.descripcion.slice(0, 40)} → ${NOMBRE_ESTADO_MODULO[estado] ?? estado}`); await cargar() } catch (e) { setError(mensajeDeError(e)) } }} alAbrir={(id) => ir({ registro: id })} />}
      {vista === 'por_un' && <PorUN unidades={unidades.datos ?? []} alAbrir={(m, id) => ir({ modulo: m, registro: id })} />}
      {vista === 'reporte' && <Reporte tenantId={filtros.tenant_id || undefined} />}
      {registroId && <DetalleRegistro modulo={modulo} registroId={registroId} alCerrar={() => ir({ registro: null })} alCambiar={async (texto) => { setAviso(texto); await cargar() }} />}
    </div>
  )
}

function Kanban({ modulo, registros, alCambiar, alAbrir }: { modulo: Modulo; registros: RegistroSeguimiento[]; alCambiar: (r: RegistroSeguimiento, estado: string) => Promise<void>; alAbrir: (id: string) => void }) {
  const [arrastrando, setArrastrando] = useState<RegistroSeguimiento | null>(null)
  return (
    <div className="flex gap-3 overflow-x-auto pb-2" data-testid="kanban">
      {ESTADOS_MODULO[modulo].map((estado) => (
        <section key={estado} aria-label={NOMBRE_ESTADO_MODULO[estado] ?? estado} className="w-64 shrink-0 rounded-xl bg-slate-100 p-2"
                 onDragOver={(e) => e.preventDefault()} onDrop={() => { if (arrastrando && arrastrando.estado !== estado) void alCambiar(arrastrando, estado); setArrastrando(null) }}>
          <h2 className="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-slate-600">{NOMBRE_ESTADO_MODULO[estado] ?? estado} <span className="text-slate-400">{registros.filter((r) => r.estado === estado).length}</span></h2>
          <div className="space-y-2">
            {registros.filter((r) => r.estado === estado).map((r) => (
              <article key={r.id} draggable onDragStart={() => setArrastrando(r)} data-testid={`tarjeta-${r.id}`}
                       className={`cursor-grab rounded-lg border bg-white p-2 text-sm shadow-sm ${r.alertas_activas.length ? 'border-red-400 bg-red-50' : 'border-slate-200'}`}>
                <button className="text-left font-medium text-slate-900" onClick={() => alAbrir(r.id)}>{r.numero ?? r.descripcion.slice(0, 50)}</button>
                <p className="text-xs text-slate-500">{r.un_codigo} · {r.dias_en_estado} d{r.alertas_activas.length ? ` · ${r.alertas_activas.join(', ')}` : ''}</p>
                {r.destinos.length > 0 && (
                  <select aria-label={`Mover ${r.numero ?? r.descripcion.slice(0, 20)}`} className="mt-1 w-full rounded border border-slate-300 px-1 py-0.5 text-xs" value="" onChange={(e) => { if (e.target.value) void alCambiar(r, e.target.value) }}>
                    <option value="">Mover a…</option>
                    {r.destinos.map((d) => <option key={d} value={d}>{NOMBRE_ESTADO_MODULO[d] ?? d}</option>)}
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

function PorUN({ unidades, alAbrir }: { unidades: UnidadNegocio[]; alAbrir: (m: Modulo, id: string) => void }) {
  const [unId, setUnId] = useState('')
  const [datos, setDatos] = useState<Record<string, RegistroSeguimiento[] | string> | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { if (unId) porUN(unId).then(setDatos).catch((e) => setError(mensajeDeError(e))); else setDatos(null) }, [unId])
  return (
    <div>
      <div className="mb-3"><Selector etiqueta="Unidad de negocio" value={unId} onChange={(e) => setUnId(e.target.value)} opciones={[{ valor: '', texto: 'Elegir UN…' }, ...unidades.map((u) => ({ valor: u.id, texto: `${u.codigo} · ${u.nombre}` }))]} /></div>
      {error && <Aviso>{error}</Aviso>}
      {datos && (
        <div className="grid gap-4 lg:grid-cols-2" data-testid="por-un">
          {([['cotizaciones', 'cotizaciones'], ['por_presupuesto', 'presupuesto'], ['seguimiento_interno', 'interno'], ['reprogramacion', 'reprogramacion']] as [string, Modulo][]).map(([clave, m]) => {
            const lista = (datos[clave] as RegistroSeguimiento[]) ?? []
            return (
              <Tarjeta key={clave} titulo={`${NOMBRE_MODULO[m]} (${lista.length})`}>
                {lista.length === 0 ? <p className="text-sm text-slate-500">Sin registros.</p> : <ul className="divide-y divide-slate-100 text-sm">{lista.map((r) => <li key={r.id} className="flex items-center justify-between py-1"><button className="text-left text-primario underline" onClick={() => alAbrir(m, r.id)}>{r.numero ?? r.descripcion.slice(0, 60)}</button><Insignia tono={r.alertas_activas.length ? 'alerta' : 'neutro'}>{NOMBRE_ESTADO_MODULO[r.estado] ?? r.estado} · {r.dias_en_estado} d</Insignia></li>)}</ul>}
              </Tarjeta>
            )
          })}
        </div>
      )}
    </div>
  )
}

function Reporte({ tenantId }: { tenantId?: string }) {
  const [desde, setDesde] = useState(() => { const d = new Date(); d.setMonth(d.getMonth() - 1); return d.toISOString().slice(0, 10) })
  const [hasta, setHasta] = useState(new Date().toISOString().slice(0, 10))
  const [r, setR] = useState<ReporteEjecutivo | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { reporteEjecutivo({ desde, hasta, tenant_id: tenantId }).then(setR).catch((e) => setError(mensajeDeError(e))) }, [desde, hasta, tenantId])
  return (
    <div className="space-y-4" data-testid="reporte-ejecutivo">
      <div className="flex flex-wrap items-end gap-2">
        <Campo etiqueta="Desde" type="date" value={desde} onChange={(e) => setDesde(e.target.value)} />
        <Campo etiqueta="Hasta" type="date" value={hasta} onChange={(e) => setHasta(e.target.value)} />
        <Boton variante="secundario" onClick={() => void descargarReporte('xlsx', { desde, hasta, tenant_id: tenantId }).then((b) => abrirBlob(b, 'reporte-seguimiento.xlsx')).catch((e) => setError(mensajeDeError(e)))}>Exportar Excel</Boton>
        <Boton variante="secundario" onClick={() => void descargarReporte('pdf', { desde, hasta, tenant_id: tenantId }).then((b) => abrirBlob(b, 'reporte-seguimiento.pdf')).catch((e) => setError(mensajeDeError(e)))}>Exportar PDF</Boton>
      </div>
      {error && <Aviso>{error}</Aviso>}
      {r && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Tarjeta titulo="Tiempo promedio de resolución por módulo (días)">
            <ul className="text-sm">{Object.entries(r.totales).map(([k, v]) => <li key={k} className="flex justify-between border-b border-slate-100 py-1"><span>{k}</span><span>{v} registros · {r.tiempo_promedio_resolucion_dias[k] ?? '—'} d</span></li>)}</ul>
          </Tarjeta>
          <Tarjeta titulo="Cotizaciones">
            <p className="text-2xl font-bold">{`${r.tasa_conversion_cotizaciones}%`} <span className="text-sm font-normal text-slate-500">tasa de conversión</span></p>
            <ul className="text-sm">{Object.entries(r.cotizaciones).map(([k, v]) => <li key={k}>{NOMBRE_ESTADO_MODULO[k] ?? k}: {v}</li>)}</ul>
          </Tarjeta>
          <Tarjeta titulo="Hallazgos recurrentes por tipo de equipo">
            {r.hallazgos_recurrentes.length === 0 ? <p className="text-sm text-slate-500">Sin hallazgos en el período.</p> : <ul className="text-sm">{r.hallazgos_recurrentes.map((h) => <li key={h.tipo_equipo}>{h.tipo_equipo}: {h.total}</li>)}</ul>}
          </Tarjeta>
          <Tarjeta titulo="Trabajo potencial diferido por UN">
            {r.monto_potencial.length === 0 ? <p className="text-sm text-slate-500">Sin diferidos.</p> : <ul className="text-sm">{r.monto_potencial.map((m) => <li key={m.un_id}>{m.un_codigo}: {m.diferidos} diferidos · ${Number(m.monto_potencial).toLocaleString('es-MX')}</li>)}</ul>}
          </Tarjeta>
        </div>
      )}
    </div>
  )
}

function DetalleRegistro({ modulo, registroId, alCerrar, alCambiar }: { modulo: Modulo; registroId: string; alCerrar: () => void; alCambiar: (texto: string) => Promise<void> }) {
  const { usuario } = useAuth()
  const [r, setR] = useState<RegistroSeguimiento | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [campos, setCampos] = useState<CambioEstado & { destinatarios?: string; comentario?: string; monto?: string | null }>({ estado: '', notas: '' })
  const cargar = useCallback(async () => { try { setR(await obtenerRegistro(modulo, registroId)) } catch (e) { setError(mensajeDeError(e)) } }, [modulo, registroId])
  useEffect(() => { void cargar() }, [cargar])
  if (!r || !usuario) return <Modal titulo="Registro" abierto alCerrar={alCerrar}>{error ? <Aviso>{error}</Aviso> : <p className="text-sm text-slate-500">Cargando…</p>}</Modal>
  const esCliente = usuario.dominio === 'tenant'
  const esPrestador = usuario.dominio === 'prestador' || usuario.rol === 'superadmin'

  async function ejecutar(fn: () => Promise<unknown>, texto: string) {
    setError(null)
    try { await fn(); await cargar(); await alCambiar(texto) } catch (e) { setError(mensajeDeError(e)) }
  }
  const necesitaProveedor = campos.estado === 'con_proveedor' || campos.estado === 'fecha_asignada' || campos.estado === 'tercero_confirmado'
  return (
    <Modal titulo={`${NOMBRE_MODULO[modulo]} · ${r.numero ?? r.un_codigo ?? ''}`} abierto alCerrar={alCerrar}>
      {error && <div className="mb-2"><Aviso>{error}</Aviso></div>}
      <div className="space-y-3 text-sm" data-testid="detalle-registro">
        <p className="text-slate-800">{r.descripcion}</p>
        <p className="text-xs text-slate-500">{r.un_codigo} · {r.un_nombre}{r.equipo_codigo && ` · ${r.equipo_codigo}`}{r.numero_folio && <> · <Link className="text-primario underline" to={`/folios/${r.folio_id}`}>{r.numero_folio}</Link></>} · origen {r.origen}</p>
        <div className="flex flex-wrap gap-1"><Insignia tono={r.alertas_activas.length ? 'alerta' : 'acento'}>{NOMBRE_ESTADO_MODULO[r.estado] ?? r.estado}</Insignia><Insignia>{r.dias_en_estado} días</Insignia>{r.alertas_activas.map((a) => <Insignia key={a} tono="alerta">{a}</Insignia>)}{r.escalada_empresa && <Insignia tono="alerta">Escalada al Admin empresa</Insignia>}</div>
        {modulo === 'cotizaciones' && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            <dt className="text-slate-500">Monto</dt><dd>{r.monto ? `$${Number(r.monto).toLocaleString('es-MX')} ${r.moneda}` : 'por definir'}</dd>
            <dt className="text-slate-500">Enviada</dt><dd>{fmtFecha(r.fecha_envio)}</dd>
            <dt className="text-slate-500">Respuesta</dt><dd>{fmtFecha(r.fecha_respuesta)} {r.notas_respuesta}</dd>
            <dt className="text-slate-500">Trabajo especial</dt><dd>{r.trabajo_especial_id ? <Link className="text-primario underline" to={`/trabajos-especiales?registro=${r.trabajo_especial_id}`}>{r.trabajo_especial_numero} · {r.estado_trabajo_especial}</Link> : <span className="text-slate-400">sin convertir</span>}</dd>
          </dl>
        )}
        {(modulo === 'interno' || modulo === 'reprogramacion') && (r.proveedor || r.proveedor_tercero) && <p>Tercero: <strong>{r.proveedor ?? r.proveedor_tercero}</strong> · fecha acordada {r.fecha_acordada ?? '—'}{r.referencia_tercero && ` · ref. ${r.referencia_tercero}`}{modulo === 'reprogramacion' && ` · fechas vencidas ${r.fechas_vencidas_count}`}</p>}
        {modulo === 'reprogramacion' && r.trabajo_coordinado && <p>Trabajo coordinado · variante {r.variante} · tercero {r.tercero_completo ? 'completó su parte' : 'pendiente'}{r.motivo && ` · motivo: ${r.motivo}`}</p>}
        {modulo === 'presupuesto' && <p>Período {r.periodo_presupuestal} · última revisión {fmtFecha(r.ultima_revision)}{r.razon_descarte && ` · descartado: ${r.razon_descarte}`}{r.reactivado_como && ` · reactivado como ${r.reactivado_como}`}</p>}
        {r.justificacion_cierre && <p className="text-slate-700">Cierre: {r.justificacion_cierre}</p>}

        {/* Acciones según módulo y rol */}
        {modulo === 'cotizaciones' && esPrestador && (r.estado === 'solicitada' || r.estado === 'en_preparacion') && (
          <div className="rounded-lg border border-slate-200 p-2">
            <p className="mb-1 font-medium">Preparar</p>
            <div className="grid gap-2 sm:grid-cols-[1fr_8rem]"><Campo etiqueta="Descripción" value={campos.descripcion ?? r.descripcion} onChange={(e) => setCampos({ ...campos, descripcion: e.target.value })} /><Campo etiqueta="Monto" type="number" min={0} step="0.01" value={campos.monto ?? r.monto ?? ''} onChange={(e) => setCampos({ ...campos, monto: e.target.value })} /></div>
            <div className="mt-2 flex gap-2"><Boton variante="secundario" onClick={() => void ejecutar(() => prepararCotizacion(r.id, { descripcion: campos.descripcion ?? r.descripcion, monto: campos.monto ?? r.monto ?? undefined }), 'Cotización en preparación')}>Guardar</Boton><Boton onClick={() => void ejecutar(async () => { await prepararCotizacion(r.id, { descripcion: campos.descripcion ?? r.descripcion, monto: campos.monto ?? r.monto ?? undefined }); await enviarCotizacion(r.id) }, 'Cotización enviada al cliente')}>Enviar al cliente</Boton></div>
          </div>
        )}
        {modulo === 'cotizaciones' && r.estado === 'enviada' && esCliente && (
          <div className="flex flex-wrap items-end gap-2">
            <Campo etiqueta="Notas" value={campos.notas ?? ''} onChange={(e) => setCampos({ ...campos, notas: e.target.value })} />
            <Boton onClick={() => void ejecutar(() => responderCotizacion(r.id, true, campos.notas ?? ''), 'Cotización autorizada')}>Autorizar</Boton>
            <Boton variante="peligro" onClick={() => void ejecutar(() => responderCotizacion(r.id, false, campos.notas ?? '', campos.pasar_a_presupuesto ?? false), 'Cotización rechazada')}>Rechazar</Boton>
            <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={!!campos.pasar_a_presupuesto} onChange={(e) => setCampos({ ...campos, pasar_a_presupuesto: e.target.checked })} /> Si rechazo, pasar a Por presupuesto</label>
          </div>
        )}
        {modulo === 'cotizaciones' && esPrestador && r.estado === 'autorizada' && !r.trabajo_especial_id && (
          <Boton onClick={() => void ejecutar(() => convertirCotizacion(r.id), `${r.numero} convertida en trabajo especial`)}>Convertir en Trabajo Especial</Boton>
        )}
        {modulo === 'cotizaciones' && r.pdf_disponible && (
          <div className="rounded-lg border border-slate-200 p-2">
            <div className="flex flex-wrap gap-2"><Boton variante="secundario" onClick={() => void pdfCotizacion(r.id).then((b) => abrirBlob(b, `${r.numero}.pdf`)).catch((e) => setError(mensajeDeError(e)))}>Descargar PDF</Boton></div>
            <p className="mt-2 text-xs text-slate-500">Enviar por correo a destinatarios externos (licitación): no cambia el estado.</p>
            <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]"><Campo etiqueta="Correos (coma)" value={campos.destinatarios ?? ''} onChange={(e) => setCampos({ ...campos, destinatarios: e.target.value })} /><Campo etiqueta="Comentario" value={campos.comentario ?? ''} onChange={(e) => setCampos({ ...campos, comentario: e.target.value })} /><Boton className="self-end" variante="secundario" disabled={!campos.destinatarios} onClick={() => void ejecutar(() => enviarCotizacionExterno(r.id, (campos.destinatarios ?? '').split(/[,;\s]+/).filter(Boolean), campos.comentario ?? ''), 'PDF enviado por correo')}>Enviar por correo</Boton></div>
            {(r.envios_externos ?? []).length > 0 && <ul className="mt-1 text-xs text-slate-500">{r.envios_externos!.map((e) => <li key={e.id}>{fmtFecha(e.timestamp)} · {e.destinatarios.join(', ')} · {e.estado_entrega}</li>)}</ul>}
          </div>
        )}
        {modulo === 'presupuesto' && r.estado === 'diferido' && esCliente && (
          <div className="flex flex-wrap items-end gap-2">
            <Campo etiqueta="Notas / razón" value={campos.notas ?? ''} onChange={(e) => setCampos({ ...campos, notas: e.target.value })} />
            <Boton onClick={() => void ejecutar(() => reactivarPresupuesto(r.id, 'folio', campos.notas ?? ''), 'Reactivado como folio')}>Reactivar: folio</Boton>
            <Boton onClick={() => void ejecutar(() => reactivarPresupuesto(r.id, 'cotizacion', campos.notas ?? ''), 'Reactivado como cotización')}>Reactivar: cotización</Boton>
            <Boton variante="secundario" onClick={() => void ejecutar(() => revisarPresupuesto(r.id, campos.notas ?? ''), 'Revisado')}>Revisado</Boton>
            <Boton variante="peligro" onClick={() => void ejecutar(() => descartarPresupuesto(r.id, campos.notas ?? ''), 'Descartado definitivamente')}>Descartar (razón obligatoria)</Boton>
          </div>
        )}
        {modulo === 'interno' && !FINALES.has(r.estado) && esCliente && (
          <div className="flex flex-wrap items-end gap-2"><Campo etiqueta="Novedad" value={campos.notas ?? ''} onChange={(e) => setCampos({ ...campos, notas: e.target.value })} /><Boton variante="secundario" onClick={() => void ejecutar(() => actualizarInterno(r.id, campos.notas ?? ''), 'Novedad registrada')}>Registrar novedad</Boton></div>
        )}
        {modulo === 'reprogramacion' && r.trabajo_coordinado && r.variante === 'A' && !r.tercero_completo && !FINALES.has(r.estado) && (
          <Boton variante="secundario" onClick={() => void ejecutar(() => confirmarTercero(r.id, campos.notas ?? ''), 'Tercero confirmado: folio creado para el técnico')}>Confirmar que el tercero completó su parte</Boton>
        )}
        {r.destinos.length > 0 && (
          <div className="rounded-lg border border-slate-200 p-2" data-testid="cambiar-estado">
            <p className="mb-1 font-medium">Cambiar estado</p>
            <div className="grid gap-2 sm:grid-cols-2">
              <Selector etiqueta="Nuevo estado" value={campos.estado} onChange={(e) => setCampos({ ...campos, estado: e.target.value })} opciones={[{ valor: '', texto: 'Elegir…' }, ...r.destinos.map((d) => ({ valor: d, texto: NOMBRE_ESTADO_MODULO[d] ?? d }))]} />
              <Campo etiqueta={['resuelto', 'cancelado', 'descartado'].includes(campos.estado) ? 'Justificación (obligatoria)' : 'Notas'} value={campos.notas ?? ''} onChange={(e) => setCampos({ ...campos, notas: e.target.value })} />
              {necesitaProveedor && <><Campo etiqueta="Proveedor / tercero" value={campos.proveedor ?? ''} onChange={(e) => setCampos({ ...campos, proveedor: e.target.value })} /><Campo etiqueta="Fecha acordada" type="date" value={campos.fecha_acordada ?? ''} onChange={(e) => setCampos({ ...campos, fecha_acordada: e.target.value })} /><Campo etiqueta="Referencia (opcional)" value={campos.referencia_tercero ?? ''} onChange={(e) => setCampos({ ...campos, referencia_tercero: e.target.value })} /></>}
              {modulo === 'presupuesto' && campos.estado === 'reactivado' && <Selector etiqueta="Reactivar como" value={campos.como ?? 'cotizacion'} onChange={(e) => setCampos({ ...campos, como: e.target.value as 'folio' | 'cotizacion' })} opciones={[{ valor: 'cotizacion', texto: 'Cotización' }, { valor: 'folio', texto: 'Folio directo' }]} />}
            </div>
            <div className="mt-2"><Boton disabled={!campos.estado} onClick={() => void ejecutar(() => cambiarEstado(modulo, r.id, { ...campos, proveedor: campos.proveedor || null, fecha_acordada: campos.fecha_acordada || null, referencia_tercero: campos.referencia_tercero || null }), `Estado: ${NOMBRE_ESTADO_MODULO[campos.estado] ?? campos.estado}`)}>Aplicar</Boton></div>
          </div>
        )}
        {r.historial && (
          <div>
            <h3 className="text-xs font-semibold uppercase text-slate-500">Historial</h3>
            <ul className="text-xs text-slate-600">{r.historial.map((h) => <li key={h.id}>{fmtFecha(h.timestamp)} · {h.estado_anterior ? `${NOMBRE_ESTADO_MODULO[h.estado_anterior] ?? h.estado_anterior} → ` : ''}{NOMBRE_ESTADO_MODULO[h.estado_nuevo] ?? h.estado_nuevo} · {h.usuario_nombre ?? h.actor_rol}{h.notas && ` · ${h.notas}`}</li>)}</ul>
          </div>
        )}
      </div>
    </Modal>
  )
}
