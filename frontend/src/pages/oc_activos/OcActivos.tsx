import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { Aviso, Boton, Campo, Encabezado, Insignia, Modal, Selector, Tabla } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { useRecurso } from '../../hooks/useRecurso'
import { mensajeDeError } from '../../services/api'
import { obtenerOC, pendientesOC, registrarEstatusOC } from '../../services/trabajos_especiales'
import type { Tenant } from '../../types/api'
import type { AutorizacionActivoDetalle, EstatusOC, PendienteOC } from '../../types/trabajos_especiales'
import { NOMBRE_ESTATUS_OC, ROLES_REGISTRAN_OC } from '../../types/trabajos_especiales'
import { EstadoInsignia, fecha as fmtFecha } from '../folios/comunes'

const TONO: Record<EstatusOC, 'neutro' | 'ok' | 'alerta' | 'acento'> = { pendiente_iniciar_tramite: 'alerta', oc_en_tramite: 'acento', oc_autorizada: 'ok', listo_para_asignar: 'ok', oc_rechazada: 'neutro' }

/** Seguimiento de OC para instalación de activos (§6.10.7): folios de activos pendientes de autorización, registro del número de OC y estatus, historial y decisión ante rechazo. */
export function OcActivos() {
  const { usuario } = useAuth()
  const [params, setParams] = useSearchParams()
  const folioId = params.get('folio')
  const esPrestador = usuario?.dominio === 'prestador' || usuario?.rol === 'superadmin'
  const [filtros, setFiltros] = useState({ tenant_id: '', incluir_resueltos: false })
  const [pendientes, setPendientes] = useState<PendienteOC[]>([])
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const tenants = useRecurso<Tenant[]>(esPrestador ? '/tenants' : null)
  const cargar = useCallback(async () => {
    try { setPendientes(await pendientesOC({ tenant_id: filtros.tenant_id || undefined, incluir_resueltos: filtros.incluir_resueltos })) } catch (e) { setError(mensajeDeError(e)) }
  }, [filtros])
  useEffect(() => { void cargar() }, [cargar])
  function ir(cambios: Record<string, string | null>) {
    const p = new URLSearchParams(params)
    for (const [k, v] of Object.entries(cambios)) { if (v) p.set(k, v); else p.delete(k) }
    setParams(p)
  }
  if (!usuario) return null
  return (
    <div>
      <Encabezado titulo="OC de activos" descripcion="Folios de instalación de activo que esperan la orden de compra del cliente. ACMA no genera la OC en el ERP: el Admin empresa registra aquí el número y el estatus del trámite; con la OC autorizada el folio entra al flujo de asignación y, al cerrarse, el equipo se da de alta." />
      <div className="mb-4 flex flex-wrap items-end gap-2">
        {esPrestador && <Selector etiqueta="Cliente" value={filtros.tenant_id} onChange={(e) => setFiltros({ ...filtros, tenant_id: e.target.value })} opciones={[{ valor: '', texto: 'Todos' }, ...(tenants.datos ?? []).map((t) => ({ valor: t.id, texto: t.razon_social }))]} />}
        <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={filtros.incluir_resueltos} onChange={(e) => setFiltros({ ...filtros, incluir_resueltos: e.target.checked })} /> Incluir resueltos</label>
      </div>
      {error && <div className="mb-3"><Aviso>{error}</Aviso></div>}
      {aviso && <div className="mb-3"><Aviso tipo="exito">{aviso}</Aviso></div>}
      <div className="rounded-xl border border-slate-200 bg-white p-2">
        <Tabla
          filas={pendientes}
          vacio="No hay folios de activos pendientes de autorización."
          columnas={[
            { titulo: 'Folio', celda: (p) => <button className="text-left font-mono text-sm text-primario underline" onClick={() => ir({ folio: p.folio_id })} data-testid={`oc-${p.folio.numero_folio}`}>{p.folio.numero_folio}</button> },
            { titulo: 'Descripción', celda: (p) => <span className="text-sm">{p.folio.descripcion.slice(0, 80)}</span> },
            { titulo: 'UN', celda: (p) => <span>{p.folio.un_codigo} <span className="text-xs text-slate-500">{p.folio.un_nombre}</span></span> },
            { titulo: 'Estatus de la OC', celda: (p) => <Insignia tono={TONO[p.estatus_multinivel]}>{NOMBRE_ESTATUS_OC[p.estatus_multinivel]}</Insignia> },
            { titulo: 'OC', celda: (p) => <span className="font-mono text-xs">{p.numero_oc_definitivo ?? p.numero_oc_provisional ?? '—'}</span> },
            { titulo: 'Días en el estatus', celda: (p) => <span className={p.dias_en_estatus > 5 && p.estatus_multinivel === 'pendiente_iniciar_tramite' ? 'font-semibold text-red-700' : ''}>{p.dias_en_estatus}</span> },
            { titulo: 'Folio', celda: (p) => <EstadoInsignia estado={p.folio.estado} /> },
          ]}
        />
      </div>
      {folioId && <DetalleOC folioId={folioId} alCerrar={() => ir({ folio: null })} alCambiar={async (texto) => { setAviso(texto); await cargar() }} />}
    </div>
  )
}

function DetalleOC({ folioId, alCerrar, alCambiar }: { folioId: string; alCerrar: () => void; alCambiar: (texto: string) => Promise<void> }) {
  const { usuario } = useAuth()
  const [a, setA] = useState<AutorizacionActivoDetalle | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [f, setF] = useState({ estatus: '' as EstatusOC | '', provisional: '', definitivo: '', fecha: '', notas: '', decision: '' as '' | 'cancelar' | 'reprogramar_periodo', periodo: '' })
  const cargar = useCallback(async () => { try { setA(await obtenerOC(folioId)) } catch (e) { setError(mensajeDeError(e)) } }, [folioId])
  useEffect(() => { void cargar() }, [cargar])
  if (!a || !usuario) return <Modal titulo="OC de activo" abierto alCerrar={alCerrar}>{error ? <Aviso>{error}</Aviso> : <p className="text-sm text-slate-500">Cargando…</p>}</Modal>
  const registra = ROLES_REGISTRAN_OC.includes(usuario.rol) && a.destinos.length > 0
  const datos = a.datos_equipo as Record<string, string | undefined>
  async function guardar() {
    setError(null)
    if (!f.estatus) return
    try {
      await registrarEstatusOC(folioId, { estatus: f.estatus, numero_oc_provisional: f.provisional || null, numero_oc_definitivo: f.definitivo || null, fecha_autorizacion_erp: f.fecha || null, notas: f.notas,
                                          decision_rechazo: f.estatus === 'oc_rechazada' ? (f.decision || null) : null, periodo_presupuestal_destino: f.periodo || null })
      await cargar()
      await alCambiar(`${a!.folio.numero_folio}: ${NOMBRE_ESTATUS_OC[f.estatus as EstatusOC]}`)
    } catch (e) { setError(mensajeDeError(e)) }
  }
  const faltaDato = (f.estatus === 'oc_autorizada' && (!f.definitivo || !f.fecha)) || (f.estatus === 'oc_rechazada' && (!f.decision || (f.decision === 'reprogramar_periodo' && !f.periodo)))
  return (
    <Modal titulo={`${a.folio.numero_folio} · ${NOMBRE_ESTATUS_OC[a.estatus_multinivel]}`} abierto alCerrar={alCerrar}>
      {error && <div className="mb-2"><Aviso>{error}</Aviso></div>}
      <div className="space-y-3 text-sm" data-testid="detalle-oc">
        <p className="text-slate-800">{a.folio.descripcion} <Link className="text-primario underline" to={`/folios/${a.folio_id}`}>ver folio</Link></p>
        <div className="flex flex-wrap gap-1"><Insignia tono={TONO[a.estatus_multinivel]}>{NOMBRE_ESTATUS_OC[a.estatus_multinivel]}</Insignia><EstadoInsignia estado={a.folio.estado} /><Insignia>{a.dias_en_estatus} días</Insignia></div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
          <dt className="text-slate-500">OC provisional</dt><dd>{a.numero_oc_provisional ?? '—'}</dd>
          <dt className="text-slate-500">OC definitiva</dt><dd>{a.numero_oc_definitivo ?? '—'}{a.fecha_autorizacion_erp && ` · autorizada en el ERP el ${a.fecha_autorizacion_erp}`}</dd>
          <dt className="text-slate-500">Equipo a instalar</dt><dd>{[datos.tipo_equipo, datos.marca, datos.modelo, datos.numero_serie].filter(Boolean).join(' · ') || 'sin datos en el formulario'}{datos.valor_reposicion && ` · $${datos.valor_reposicion}`}</dd>
          {a.decision_rechazo && <><dt className="text-slate-500">Rechazo</dt><dd>{a.decision_rechazo === 'cancelar' ? 'Folio cancelado' : `Reprogramado al período ${a.periodo_presupuestal_destino}`}</dd></>}
          {a.equipo_instalado && <><dt className="text-slate-500">Equipo dado de alta</dt><dd data-testid="equipo-instalado">{a.equipo_instalado.codigo} · {a.equipo_instalado.nombre} <Insignia tono={a.equipo_instalado.estado === 'activo' ? 'ok' : 'alerta'}>{a.equipo_instalado.estado}</Insignia></dd></>}
        </dl>
        {registra && (
          <div className="rounded-lg border border-slate-200 p-2" data-testid="registrar-oc">
            <p className="mb-1 font-medium">Registrar estatus del trámite en el ERP</p>
            <div className="grid gap-2 sm:grid-cols-2">
              <Selector etiqueta="Nuevo estatus" value={f.estatus} onChange={(e) => setF({ ...f, estatus: e.target.value as EstatusOC })} opciones={[{ valor: '', texto: 'Elegir…' }, ...a.destinos.map((d) => ({ valor: d, texto: NOMBRE_ESTATUS_OC[d as EstatusOC] }))]} />
              <Campo etiqueta="Número de OC provisional" value={f.provisional} onChange={(e) => setF({ ...f, provisional: e.target.value })} />
              {f.estatus === 'oc_autorizada' && <><Campo etiqueta="Número de OC definitivo" value={f.definitivo} onChange={(e) => setF({ ...f, definitivo: e.target.value })} /><Campo etiqueta="Fecha de autorización en el ERP" type="date" value={f.fecha} onChange={(e) => setF({ ...f, fecha: e.target.value })} /></>}
              {f.estatus === 'oc_rechazada' && <><Selector etiqueta="Decisión" value={f.decision} onChange={(e) => setF({ ...f, decision: e.target.value as 'cancelar' | 'reprogramar_periodo' })} opciones={[{ valor: '', texto: 'Elegir…' }, { valor: 'cancelar', texto: 'Cancelar el folio' }, { valor: 'reprogramar_periodo', texto: 'Reprogramar a un período presupuestal' }]} />
                {f.decision === 'reprogramar_periodo' && <Campo etiqueta="Período destino (p. ej. 2027-T1)" value={f.periodo} onChange={(e) => setF({ ...f, periodo: e.target.value })} />}</>}
              <Campo etiqueta="Notas" value={f.notas} onChange={(e) => setF({ ...f, notas: e.target.value })} />
            </div>
            <div className="mt-2"><Boton disabled={!f.estatus || faltaDato} onClick={() => void guardar()}>Registrar</Boton></div>
          </div>
        )}
        <div>
          <h3 className="text-xs font-semibold uppercase text-slate-500">Historial del trámite</h3>
          <ul className="text-xs text-slate-600" data-testid="historial-oc">{a.historial.map((h) => <li key={h.id}>{fmtFecha(h.timestamp)} · {h.estatus_anterior ? `${NOMBRE_ESTATUS_OC[h.estatus_anterior as EstatusOC] ?? h.estatus_anterior} → ` : ''}{NOMBRE_ESTATUS_OC[h.estatus_nuevo as EstatusOC] ?? h.estatus_nuevo} · {h.actor_nombre ?? h.actor_rol}{h.notas && ` · ${h.notas}`}</li>)}</ul>
        </div>
      </div>
    </Modal>
  )
}
