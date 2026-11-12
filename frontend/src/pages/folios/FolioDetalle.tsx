import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'
import { ChatFolio } from '../../components/chat/ChatFolio'
import { Aviso, Boton, Campo, Insignia, Modal, Selector, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import type { Severidad, Tecnico } from '../../types/api'
import type { EstadoFolio, FolioDetalle as Detalle, RazonRechazo } from '../../types/folios'
import { NOMBRE_ESTADO, NOMBRE_TRIGGER, RAZONES_RECHAZO } from '../../types/folios'
import { api, mensajeDeError } from '../../services/api'
import { ACCIONES, accionFolio, aprobarFolio, comentarFolio, fijarMonto, obtenerFolio, overrideSeveridad, rechazarFolio, transiciones } from '../../services/folios'
import { notificar } from '../../services/notificaciones'
import { ROLES_AUTORIZAN, ROLES_REASIGNAN, ROLES_SOLICITAN } from '../../types/preventivos'
import { PanelPreventivo, ReasignarModal } from './Reasignar'
import { AvisosFolio } from './AvisosFolio'
import { Financiero } from './Financiero'
import { SeccionSLA } from './SeccionSLA'
import { EstadoInsignia, SeveridadInsignia, fecha, resumenCertificaciones } from './comunes'

type Accion = (typeof ACCIONES)[number]

/** Archivo completo del folio (§6.8.6) con línea de tiempo, acciones válidas por rol/estado y panel de aprobación. */
export function FolioDetalle() {
  const { folioId } = useParams()
  const { usuario } = useAuth()
  const [d, setD] = useState<Detalle | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [accion, setAccion] = useState<Accion | null>(null)
  const [texto, setTexto] = useState('')
  const [tecnicoId, setTecnicoId] = useState('')
  const [tecnicos, setTecnicos] = useState<Tecnico[]>([])
  const [rechazando, setRechazando] = useState(false)
  const [razon, setRazon] = useState<RazonRechazo | null>(null)
  const [comentario, setComentario] = useState('')
  const [monto, setMonto] = useState('')
  const [severidades, setSeveridades] = useState<Severidad[]>([])
  const [override, setOverride] = useState({ severidad_id: '', razon: '' })
  const [destinosTabla, setDestinosTabla] = useState<Set<string>>(new Set())
  const [reasignando, setReasignando] = useState(false)

  const cargar = useCallback(async () => {
    if (!folioId) return
    try {
      const det = await obtenerFolio(folioId)
      setD(det)
      setMonto(det.folio.monto_estimado ?? '')
      const tabla = await transiciones()
      setDestinosTabla(new Set(tabla.filter((t) => t.origen === det.folio.estado && (usuario?.rol === 'superadmin' || t.roles.includes(usuario?.rol ?? ''))).map((t) => t.destino)))
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }, [folioId, usuario?.rol])

  useEffect(() => { void cargar() }, [cargar])

  async function ejecutar(a: Accion) {
    if (!d) return
    if (a.campo && !accion) {
      setAccion(a)
      setTexto('')
      if (a.campo === 'tecnico' && tecnicos.length === 0) api<Tecnico[]>('/catalogos/tecnicos', { params: { solo_activos: true } }).then(setTecnicos).catch(() => setTecnicos([]))
      return
    }
    try {
      const cuerpo: Record<string, unknown> = a.campo === 'razon' ? { razon: texto } : a.campo === 'notas' ? { notas: texto } : a.campo === 'tecnico' ? { tecnico_id: tecnicoId, razon: texto || null } : {}
      await accionFolio(d.folio.id, a.ruta, cuerpo)
      setAccion(null)
      setAviso(`${a.etiqueta}: listo`)
      await cargar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  async function decidir(aprobar: boolean) {
    if (!d) return
    try {
      if (aprobar) {
        await aprobarFolio(d.folio.id, 'app')
        notificar(`Folio ${d.folio.numero_folio} aprobado`, `Nivel ${d.aprobacion?.nivel_actual ?? ''}`)
      } else {
        if (!razon) return
        await rechazarFolio(d.folio.id, razon, 'app')
        notificar(`Folio ${d.folio.numero_folio} rechazado`, RAZONES_RECHAZO.find((r) => r.valor === razon)?.destino ?? '')
      }
      setRechazando(false)
      setRazon(null)
      await cargar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  if (error && !d) return <Aviso>{error}</Aviso>
  if (!d || !usuario) return <p className="text-sm text-slate-500">Cargando folio…</p>
  const f = d.folio
  // Botones solo si la transición es válida según la tabla §6.8.6 (servidor) para el estado actual y el rol.
  const acciones = ACCIONES.filter((a) => d.acciones.includes(a.destino) && destinosTabla.has(a.destino) && (!a.desde || a.desde.includes(f.estado)))
  const esPrestador = ['mesa_control', 'despachador', 'admin_prestador', 'superadmin'].includes(usuario.rol)
  const puedeOverride = ['despachador', 'admin_prestador', 'superadmin'].includes(usuario.rol) && f.estado === 'en_revision'
  const final = f.estado === 'cerrado' || f.estado === 'cancelado'
  const puedeReasignar = ROLES_REASIGNAN.includes(usuario.rol) && ['asignado', 'pendiente_refaccion'].includes(f.estado)
  const esPreventivo = f.tipo_folio === 'preventivo'

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link to="/folios" className="text-xs text-primario underline">← Folios</Link>
          <h1 className="font-mono text-2xl font-semibold text-slate-900">{f.numero_folio}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <EstadoInsignia estado={f.estado} />
            <SeveridadInsignia severidad={f.severidad} />
            {f.severidad_origen === 'override_admin' && <Insignia tono="alerta">Severidad modificada</Insignia>}
            <Insignia tono={esPreventivo ? 'acento' : 'neutro'}>{esPreventivo ? `Preventivo${f.plan_nombre ? ` · ${f.plan_nombre}` : ''}` : f.tipo_folio}</Insignia>
            {f.criticidad && <Insignia tono="acento">Criticidad {f.criticidad}</Insignia>}
            {final && <Insignia>Archivo inmutable</Insignia>}
          </div>
        </div>
        <div className="flex flex-wrap gap-2" data-testid="acciones">
          {puedeReasignar && <Boton variante="secundario" onClick={() => setReasignando(true)}>Reasignar</Boton>}
          {acciones.map((a) => (
            <Boton key={a.ruta} variante={a.destino === 'cancelado' ? 'peligro' : a.destino === 'cerrado' || a.destino === 'autorizado' ? 'primario' : 'secundario'} onClick={() => void ejecutar(a)}>
              {a.etiqueta}
            </Boton>
          ))}
        </div>
      </div>
      {error && <Aviso>{error}</Aviso>}
      {aviso && <Aviso tipo="exito">{aviso}</Aviso>}

      {d.triggers_revision.length > 0 && (
        <Tarjeta titulo="Triggers de revisión manual">
          <ul className="space-y-1 text-sm">
            {d.triggers_revision.map((t) => (
              <li key={t.id} className="flex flex-wrap items-center gap-2">
                <Insignia tono={t.resuelto ? 'ok' : 'alerta'}>{NOMBRE_TRIGGER[t.trigger_tipo]}</Insignia>
                <span className="text-slate-700">{t.descripcion}</span>
                <span className="text-xs text-slate-400">{fecha(t.timestamp)}</span>
              </li>
            ))}
          </ul>
        </Tarjeta>
      )}

      {d.aprobacion && (
        <Tarjeta titulo="Aprobación multinivel" acciones={<Insignia tono={d.aprobacion.estado === 'aprobado' ? 'ok' : d.aprobacion.estado === 'rechazado' ? 'alerta' : 'acento'}>{d.aprobacion.estado}</Insignia>}>
          <p className="text-sm text-slate-700">
            Nivel actual <strong>{d.aprobacion.nivel_actual}</strong> de {d.aprobacion.nivel_maximo_requerido} requerido
            {d.aprobacion.rol_aprobador_actual && <> · aprobador: {d.aprobacion.rol_aprobador_actual}</>}
            {d.aprobacion.vence_at && <> · vence {fecha(d.aprobacion.vence_at)}</>}
          </p>
          {d.puede_aprobar && !rechazando && (
            <div className="mt-3 flex gap-2">
              <Boton onClick={() => void decidir(true)}>Aprobar</Boton>
              <Boton variante="peligro" onClick={() => setRechazando(true)}>Rechazar</Boton>
            </div>
          )}
          {rechazando && (
            <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3">
              <p className="mb-2 text-sm font-medium text-red-900">Razón del rechazo (obligatoria)</p>
              <div className="grid gap-2 sm:grid-cols-2">
                {RAZONES_RECHAZO.map((r) => (
                  <label key={r.valor} className={`cursor-pointer rounded-lg border p-2 text-sm ${razon === r.valor ? 'border-red-500 bg-white' : 'border-red-100 bg-white/60'}`}>
                    <input type="radio" name="razon" className="mr-2" checked={razon === r.valor} onChange={() => setRazon(r.valor)} />
                    {r.texto} <span className="block text-xs text-slate-500">{r.destino}</span>
                  </label>
                ))}
              </div>
              <div className="mt-2 flex gap-2">
                <Boton variante="peligro" disabled={!razon} onClick={() => void decidir(false)}>Confirmar rechazo</Boton>
                <Boton variante="fantasma" onClick={() => { setRechazando(false); setRazon(null) }}>Volver</Boton>
              </div>
            </div>
          )}
          {d.decisiones.length > 0 && (
            <ul className="mt-3 divide-y divide-slate-100 text-sm">
              {d.decisiones.map((x) => (
                <li key={x.id} className="py-1">
                  <span className="font-medium">Nivel {x.nivel} · {x.decision}</span> · {x.actor_nombre ?? 'sistema'} · canal {x.canal} · {fecha(x.timestamp)}
                  {x.razon_rechazo && <span className="text-red-800"> · {x.razon_rechazo} → {x.modulo_destino}</span>}
                </li>
              ))}
            </ul>
          )}
        </Tarjeta>
      )}

      {esPreventivo && (
        <PanelPreventivo folio={f} puedeSolicitar={ROLES_SOLICITAN.includes(usuario.rol) && !final} puedeAutorizar={ROLES_AUTORIZAN.includes(usuario.rol)} alCambiar={cargar} />
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <Tarjeta titulo="Datos de captura">
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
            <dt className="text-slate-500">Capturado por</dt><dd>{d.captura.capturado_por_nombre} · {fecha(d.captura.capturado_at)}</dd>
            <dt className="text-slate-500">UN</dt><dd>{d.captura.un.codigo} · {d.captura.un.nombre}<span className="block text-xs text-slate-500">{d.captura.un.direccion}</span></dd>
            <dt className="text-slate-500">Equipo</dt><dd>{d.captura.equipo.codigo} · {d.captura.equipo.nombre}</dd>
            <dt className="text-slate-500">Tipo de falla</dt><dd>{d.captura.tipo_falla}</dd>
            <dt className="text-slate-500">Descripción</dt><dd className="whitespace-pre-wrap">{d.captura.descripcion}</dd>
            <dt className="text-slate-500">Confirmación de UN</dt>
            <dd>{d.captura.confirmacion_un ? <Insignia tono="ok">Confirmada {fecha(d.captura.confirmacion_un_timestamp)}</Insignia> : <Insignia tono="alerta">Pendiente</Insignia>}</dd>
            {d.captura.folio_duplicado_ref_numero && (<><dt className="text-slate-500">Duplicado de</dt><dd>{d.captura.folio_duplicado_ref_numero}: {d.captura.folio_duplicado_justificacion}</dd></>)}
            {d.captura.geolat_captura != null && (<><dt className="text-slate-500">Geolocalización</dt><dd className="font-mono text-xs">{d.captura.geolat_captura}, {d.captura.geolng_captura}</dd></>)}
          </dl>
          {d.formulario_captura && (
            <details className="mt-3 text-sm"><summary className="cursor-pointer text-primario">Formulario de captura · {d.formulario_captura.formulario_nombre} v{d.formulario_captura.version_formulario}</summary>
              <pre className="mt-2 overflow-x-auto rounded bg-slate-50 p-2 text-xs">{JSON.stringify(d.formulario_captura.respuestas_json, null, 2)}</pre></details>
          )}
          {esPrestador && (f.estado === 'capturado' || f.estado === 'en_revision') && (
            <form className="mt-3 flex items-end gap-2" onSubmit={async (e) => { e.preventDefault(); try { await fijarMonto(f.id, Number(monto)); await cargar() } catch (err) { setError(mensajeDeError(err)) } }}>
              <Campo etiqueta="Monto estimado (MXN)" type="number" min={0} step="0.01" value={monto} onChange={(e) => setMonto(e.target.value)} />
              <Boton type="submit" variante="secundario">Guardar monto</Boton>
            </form>
          )}
          {puedeOverride && (
            <form className="mt-3 grid gap-2 sm:grid-cols-[1fr_1fr_auto]" onSubmit={async (e) => { e.preventDefault(); try { await overrideSeveridad(f.id, override.severidad_id, override.razon); await cargar() } catch (err) { setError(mensajeDeError(err)) } }}>
              <Selector etiqueta="Cambiar severidad" value={override.severidad_id} onFocus={() => severidades.length === 0 && api<Severidad[]>('/catalogos/severidades').then(setSeveridades).catch(() => undefined)}
                        onChange={(e) => setOverride({ ...override, severidad_id: e.target.value })} opciones={[{ valor: '', texto: 'Elegir…' }, ...severidades.map((s) => ({ valor: s.id, texto: s.nombre }))]} />
              <Campo etiqueta="Razón" value={override.razon} onChange={(e) => setOverride({ ...override, razon: e.target.value })} />
              <Boton type="submit" variante="secundario" disabled={!override.severidad_id || override.razon.length < 3}>Aplicar</Boton>
            </form>
          )}
        </Tarjeta>

        <Tarjeta titulo="Asignación y ejecución">
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
            <dt className="text-slate-500">Técnico</dt><dd>{d.asignacion.tecnico_nombre ?? '—'} {d.asignacion.vehiculo && <span className="text-xs text-slate-500">· {d.asignacion.vehiculo}</span>}</dd>
            <dt className="text-slate-500">Asignado</dt><dd>{fecha(d.asignacion.asignado_at)}</dd>
            <dt className="text-slate-500">Inicio de atención</dt><dd>{fecha(f.fecha_inicio_atencion)}</dd>
            <dt className="text-slate-500">Cierre</dt><dd>{fecha(f.fecha_cierre)}</dd>
            {f.razon_cancelacion && (<><dt className="text-slate-500">Cancelación</dt><dd className="text-red-800">{f.razon_cancelacion}</dd></>)}
          </dl>
          <h3 className="mt-3 text-xs font-semibold uppercase text-slate-500">SLA</h3>
          {d.sla ? (
            <p className="text-sm">Comprometido: respuesta {d.sla.tiempo_respuesta_prometido_horas} h · resolución
              {' '}{d.sla.tiempo_resolucion_prometido_horas} h
              <span className="text-xs text-slate-500"> · los tiempos reales y las pausas están más abajo</span></p>
          ) : <p className="text-sm text-slate-500">Se fija al autorizar.</p>}
          <h3 className="mt-3 text-xs font-semibold uppercase text-slate-500">Evidencias ({d.evidencias.length})</h3>
          <ul className="text-sm">{d.evidencias.map((e) => <li key={e.id}><Insignia>{e.tipo}</Insignia> <span className="font-mono text-xs">{e.archivo_key}</span> · {fecha(e.timestamp_captura)}</li>)}</ul>
          {d.formulario_atencion && (
            <details className="mt-3 text-sm"><summary className="cursor-pointer text-primario">Formulario de atención · {d.formulario_atencion.formulario_nombre} v{d.formulario_atencion.version_formulario}</summary>
              <pre className="mt-2 overflow-x-auto rounded bg-slate-50 p-2 text-xs">{JSON.stringify(d.formulario_atencion.respuestas_json, null, 2)}</pre></details>
          )}
          <h3 className="mt-3 text-xs font-semibold uppercase text-slate-500">Refacciones ({d.refacciones.length})</h3>
          <ul className="text-sm">{d.refacciones.map((r) => <li key={r.id}>{r.cantidad} × {r.descripcion} · {r.origen} · ${r.costo_unitario}</li>)}</ul>
          {d.folio.estado === 'pendiente_refaccion' && (
            <p className="mt-1 text-sm"><Link className="text-primario underline" to={`/inventario?vista=ordenes`}>Generar orden de compra</Link> para la refacción que falta.</p>
          )}
          <h3 className="mt-3 text-xs font-semibold uppercase text-slate-500">Encuesta</h3>
          <p className="text-sm">{d.encuesta ? `NPS ${d.encuesta.nps_score}` : 'Sin encuesta.'}</p>
          <h3 className="mt-3 text-xs font-semibold uppercase text-slate-500">Reasignaciones ({d.reasignaciones.length})</h3>
          {d.reasignaciones.length === 0 ? <p className="text-sm text-slate-500">Sin reasignaciones.</p> : (
            <ul className="text-sm" data-testid="reasignaciones">
              {d.reasignaciones.map((r) => (
                <li key={r.id}>{r.tecnico_origen_nombre ?? '—'} → <strong>{r.tecnico_destino_nombre}</strong> · {r.razon ?? 'sin razón'}{r.comentario && <span className="text-slate-600"> · {r.comentario}</span>} <span className="text-xs text-slate-500">· {r.despachador_nombre ?? r.tipo} · {fecha(r.timestamp)}</span></li>
              ))}
            </ul>
          )}
          <h3 className="mt-3 text-xs font-semibold uppercase text-slate-500">Hallazgos ({d.hallazgos.length})</h3>
          {d.hallazgos.length === 0 ? <p className="text-sm text-slate-500">Sin hallazgos.</p> : (
            <ul className="text-sm" data-testid="hallazgos-folio">{d.hallazgos.map((h) => <li key={h.id}>{h.descripcion} <Insignia tono={h.nivel_urgencia === 'alta' || h.nivel_urgencia === 'critica' ? 'alerta' : 'neutro'}>{h.nivel_urgencia}</Insignia> <span className="text-xs text-slate-500">· {h.origen} · {h.estado_respuesta === 'respondido' ? `respondido: ${h.opcion_respuesta}` : 'pendiente en la minuta'}</span></li>)}</ul>
          )}
          <h3 className="mt-3 text-xs font-semibold uppercase text-slate-500">Módulos de seguimiento ({d.derivaciones.length})</h3>
          {d.derivaciones.length === 0 ? <p className="text-sm text-slate-500">Sin derivaciones.</p> : (
            <ul className="text-sm" data-testid="derivaciones-folio">{d.derivaciones.map((x) => <li key={x.registro_id}><Link className="text-primario underline" to={`/seguimiento?modulo=${x.ruta}&registro=${x.registro_id}`}>{x.numero ?? x.modulo}</Link> · {x.estado} <span className="text-xs text-slate-500">· {x.origen}</span></li>)}</ul>
          )}
          {d.clasificacion && <p className="mt-2 text-sm" data-testid="clasificacion-folio">Clasificado como <strong>{d.clasificacion.opcion}</strong> {d.clasificacion.dentro_de_plazo ? 'dentro del plazo' : `con ${d.clasificacion.horas_retraso} h de retraso`} · {fecha(d.clasificacion.timestamp)}</p>}
          {d.folio.es_instalacion_activo && d.oc_activo && (
            <p className="mt-2 text-sm" data-testid="oc-activo-folio"><Insignia tono={d.oc_activo.estatus_multinivel === 'listo_para_asignar' ? 'ok' : 'alerta'}>{d.oc_activo.estatus_multinivel === 'listo_para_asignar' ? 'OC autorizada' : 'Esperando OC del cliente'}</Insignia> {d.oc_activo.estatus_nombre}{d.oc_activo.numero_oc_definitivo && ` · OC ${d.oc_activo.numero_oc_definitivo}`} · <Link className="text-primario underline" to={`/oc-activos?folio=${d.folio.id}`}>seguimiento de la OC</Link>{d.oc_activo.equipo_instalado && <> · equipo dado de alta <strong>{d.oc_activo.equipo_instalado.codigo}</strong> ({d.oc_activo.equipo_instalado.estado})</>}</p>
          )}
          {d.trabajo_especial && (
            <p className="mt-2 text-sm" data-testid="te-folio"><Insignia tono="acento">Trabajo especial</Insignia> <Link className="font-mono text-primario underline" to={`/trabajos-especiales?registro=${d.trabajo_especial.id}`}>{d.trabajo_especial.numero}</Link> · {d.trabajo_especial.estado}{d.trabajo_especial.urgencia && <> <Insignia tono="alerta">Urgencia</Insignia></>}</p>
          )}
          <h3 className="mt-3 text-xs font-semibold uppercase text-slate-500">Datos financieros</h3>
          <Financiero folioId={d.folio.id} alCambiar={cargar} />
          <h3 className="mt-3 text-xs font-semibold uppercase text-slate-500">Nivel de servicio (SLA)</h3>
          <SeccionSLA folioId={d.folio.id} alCambiar={cargar} />
        </Tarjeta>
      </div>

      <AvisosFolio folioId={f.id} />

      <Tarjeta titulo="Chat del folio">
        <ChatFolio folioId={f.id} />
      </Tarjeta>

      <Tarjeta titulo="Línea de tiempo">
        <ol className="relative ml-2 border-l border-slate-200 text-sm">
          {d.historial.map((h) => (
            <li key={h.id} className="mb-3 ml-4">
              <span className="absolute -left-1.5 mt-1.5 h-3 w-3 rounded-full border border-white bg-primario" aria-hidden />
              <div className="flex flex-wrap items-center gap-2">
                {h.evento === 'transicion' ? (
                  <span className="font-medium">{h.estado_anterior ? `${NOMBRE_ESTADO[h.estado_anterior]} → ` : ''}{NOMBRE_ESTADO[h.estado_nuevo]}</span>
                ) : (
                  <Insignia>{h.evento}</Insignia>
                )}
                <span className="text-xs text-slate-500">{h.actor_nombre ?? h.actor_rol} · {fecha(h.timestamp)}</span>
              </div>
              {h.notas && <p className="text-slate-700">{h.notas}</p>}
            </li>
          ))}
        </ol>
        <form className="mt-2 flex gap-2" onSubmit={async (e) => { e.preventDefault(); if (!comentario.trim()) return; try { await comentarFolio(f.id, comentario); setComentario(''); await cargar() } catch (err) { setError(mensajeDeError(err)) } }}>
          <input aria-label="Comentario" value={comentario} onChange={(e) => setComentario(e.target.value)} placeholder="Comentario administrativo…" className="flex-1 rounded-lg border border-slate-300 px-3 py-1.5 text-sm" />
          <Boton type="submit" variante="secundario">Comentar</Boton>
        </form>
      </Tarjeta>

      {reasignando && <ReasignarModal folio={f} alCerrar={() => setReasignando(false)} alReasignar={async (nombre) => { setReasignando(false); setAviso(`Folio reasignado a ${nombre}`); await cargar() }} />}

      <Modal titulo={accion?.etiqueta ?? ''} abierto={accion !== null} alCerrar={() => setAccion(null)}>
        {accion && (
          <form onSubmit={(e) => { e.preventDefault(); void ejecutar(accion) }} className="space-y-3">
            {accion.campo === 'tecnico' && (
              <Selector etiqueta="Técnico" value={tecnicoId} onChange={(e) => setTecnicoId(e.target.value)}
                        opciones={[{ valor: '', texto: 'Elegir técnico…' }, ...tecnicos.map((t) => ({ valor: t.usuario_id, texto: `${t.nombre} · ${resumenCertificaciones(t.habilidades)}` }))]} />
            )}
            {/* F2-05 (§6.9.3): la criticidad del activo pide un perfil de técnico, junto al indicador de
                certificación de F2-01. Si el cliente la activó como restricción, el servidor la exige. */}
            {accion.campo === 'tecnico' && (f.criticidad === 'A' || f.criticidad === 'B') && (
              <Aviso tipo="info">
                {`El activo es de criticidad ${f.criticidad}: §6.9.3 pide ${
                  f.criticidad === 'A' ? 'técnico especialista' : 'técnico certificado'} y respuesta en ${
                  f.criticidad === 'A' ? 4 : 8} horas.`}
              </Aviso>
            )}
            <Campo etiqueta={accion.campo === 'razon' ? 'Razón (obligatoria)' : accion.campo === 'tecnico' ? 'Razón (solo si no tiene la habilidad certificada)' : 'Notas'} value={texto} onChange={(e) => setTexto(e.target.value)} />
            <div className="flex justify-end gap-2">
              <Boton type="button" variante="fantasma" onClick={() => setAccion(null)}>Cancelar</Boton>
              <Boton type="submit" disabled={(accion.campo === 'razon' && texto.trim().length < 3) || (accion.campo === 'tecnico' && !tecnicoId)}>{accion.etiqueta}</Boton>
            </div>
          </form>
        )}
      </Modal>
    </div>
  )
}

export type { EstadoFolio }
