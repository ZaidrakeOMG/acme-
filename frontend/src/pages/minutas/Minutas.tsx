import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { Aviso, Boton, Campo, Encabezado, Insignia, Selector, Tabla, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { useRecurso } from '../../hooks/useRecurso'
import { mensajeDeError } from '../../services/api'
import { configuracionMinuta, generarMinuta, guardarConfiguracionMinuta, listarMinutas } from '../../services/minutas'
import type { Tenant, UnidadNegocio } from '../../types/api'
import type { EstadoMinuta, MinutaConfiguracion, MinutaResumen } from '../../types/minutas'
import { NOMBRE_ESTADO_MINUTA, ROLES_VALIDAN } from '../../types/minutas'
import { fecha as fmtFecha } from '../folios/comunes'

const TONO: Record<EstadoMinuta, 'neutro' | 'ok' | 'alerta' | 'acento'> = { borrador: 'neutro', pendiente_validacion: 'alerta', enviada: 'acento', respondida: 'ok', vencida: 'alerta' }
const COLOR = { rojo: 'bg-red-500', amarillo: 'bg-amber-400', verde: 'bg-green-500' } as Record<string, string>

/** Minutas del día (§7.1–7.5): lista por fecha, UN y estado; bandeja de validación del despachador; configuración por cliente. */
export function Minutas() {
  const { usuario } = useAuth()
  const esPrestador = usuario?.dominio === 'prestador' || usuario?.rol === 'superadmin'
  const [desde, setDesde] = useState(() => { const d = new Date(); d.setDate(d.getDate() - 7); return d.toISOString().slice(0, 10) })
  const [hasta, setHasta] = useState(new Date().toISOString().slice(0, 10))
  const [estado, setEstado] = useState(() => new URLSearchParams(window.location.search).get('estado') ?? '')
  const [unId, setUnId] = useState('')
  const [tenantId, setTenantId] = useState('')
  const [minutas, setMinutas] = useState<MinutaResumen[]>([])
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const tenants = useRecurso<Tenant[]>(esPrestador ? '/tenants' : null)
  const unidades = useRecurso<UnidadNegocio[]>('/unidades-negocio', { tenant_id: tenantId || undefined })

  useEffect(() => { if (esPrestador && !tenantId && tenants.datos?.[0]) setTenantId(tenants.datos[0].id) }, [esPrestador, tenantId, tenants.datos])

  async function cargar() {
    try { setMinutas(await listarMinutas({ desde, hasta, estado: estado || undefined, un_id: unId || undefined, tenant_id: tenantId || undefined })) } catch (e) { setError(mensajeDeError(e)) }
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void cargar() }, [desde, hasta, estado, unId, tenantId])

  async function generar() {
    if (!tenantId) return
    try {
      const creadas = await generarMinuta(tenantId, hasta, true)
      setAviso(creadas.length ? `${creadas.length} minuta(s) generadas para ${hasta}` : 'Ya existían las minutas de esa fecha')
      await cargar()
    } catch (e) { setError(mensajeDeError(e)) }
  }

  const pendientes = minutas.filter((m) => m.estado === 'pendiente_validacion')
  return (
    <div>
      <Encabezado titulo="Minuta del día" descripcion="Cierre de jornada por UN y global del cliente (§7.1): estatus de los módulos de seguimiento, preventivos, hallazgos, cotizaciones y peticiones. Se entrega por correo con PDF, push y aquí."
                  acciones={esPrestador && usuario && ROLES_VALIDAN.includes(usuario.rol) ? <Boton variante="secundario" onClick={() => void generar()} disabled={!tenantId}>Generar minuta de {hasta}</Boton> : undefined} />
      <div className="mb-4 flex flex-wrap items-end gap-2">
        <Campo etiqueta="Desde" type="date" value={desde} onChange={(e) => setDesde(e.target.value)} />
        <Campo etiqueta="Hasta" type="date" value={hasta} onChange={(e) => setHasta(e.target.value)} />
        {esPrestador && <Selector etiqueta="Cliente" value={tenantId} onChange={(e) => setTenantId(e.target.value)} opciones={[{ valor: '', texto: 'Todos' }, ...(tenants.datos ?? []).map((t) => ({ valor: t.id, texto: t.razon_social }))]} />}
        <Selector etiqueta="UN" value={unId} onChange={(e) => setUnId(e.target.value)} opciones={[{ valor: '', texto: 'Todas (incluye global)' }, ...(unidades.datos ?? []).map((u) => ({ valor: u.id, texto: `${u.codigo} · ${u.nombre}` }))]} />
        <Selector etiqueta="Estado" value={estado} onChange={(e) => setEstado(e.target.value)} opciones={[{ valor: '', texto: 'Todos' }, ...(Object.keys(NOMBRE_ESTADO_MINUTA) as EstadoMinuta[]).map((e) => ({ valor: e, texto: NOMBRE_ESTADO_MINUTA[e] }))]} />
      </div>
      {error && <div className="mb-3"><Aviso>{error}</Aviso></div>}
      {aviso && <div className="mb-3"><Aviso tipo="exito">{aviso}</Aviso></div>}
      {pendientes.length > 0 && usuario && ROLES_VALIDAN.includes(usuario.rol) && (
        <div className="mb-4 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900" data-testid="bandeja-validacion">
          <strong>{pendientes.length} minuta(s) pendientes de tu validación.</strong> Tienes una ventana de {pendientes.length ? '30' : ''} minutos (configurable) para revisar, anotar y aprobar; después se envían automáticamente.
          <ul className="mt-1 list-disc pl-5">{pendientes.map((m) => <li key={m.id}><Link className="underline" to={`/minutas/${m.id}`}>{m.fecha} · {m.tipo === 'global' ? 'Global' : `${m.un_codigo} ${m.un_nombre}`}</Link></li>)}</ul>
        </div>
      )}
      <div className="rounded-xl border border-slate-200 bg-white p-2">
        <Tabla
          filas={minutas}
          vacio="Sin minutas en el período"
          columnas={[
            { titulo: 'Fecha', celda: (m) => <Link to={`/minutas/${m.id}`} className="font-mono text-xs font-semibold text-primario underline">{m.fecha}</Link> },
            { titulo: 'Ámbito', celda: (m) => m.tipo === 'global' ? <span>Global <span className="text-xs text-slate-500">{m.tenant_nombre}</span></span> : <span>{m.un_codigo} <span className="text-xs text-slate-500">{m.un_nombre}</span></span> },
            { titulo: 'Estado', celda: (m) => <div className="flex flex-wrap gap-1"><Insignia tono={TONO[m.estado]}>{NOMBRE_ESTADO_MINUTA[m.estado]}</Insignia>{m.urgente && <Insignia tono="alerta">Urgente</Insignia>}{m.enviada_sin_validacion && <Insignia>Sin validación</Insignia>}</div> },
            { titulo: 'Módulos', celda: (m) => <span className="flex gap-1" title="Cotizaciones · Presupuesto · Interno · Reprogramación">{['cotizaciones', 'por_presupuesto', 'seguimiento_interno', 'reprogramacion'].map((k) => <span key={k} className={`inline-block h-3 w-3 rounded-full ${COLOR[m.colores[k] ?? 'verde']}`} />)}</span> },
            { titulo: 'Hallazgos', celda: (m) => <span>{m.hallazgos} <span className="text-xs text-slate-500">({m.hallazgos_pendientes} por responder)</span></span> },
            { titulo: 'Envío', celda: (m) => <span className="text-xs text-slate-600">{fmtFecha(m.timestamp_envio)}{m.vence_respuesta_at && m.estado === 'enviada' && <span className="block">vence {fmtFecha(m.vence_respuesta_at)}</span>}</span> },
          ]}
        />
      </div>
      {usuario?.rol === 'admin_prestador' && tenantId && <ConfiguracionMinuta tenantId={tenantId} />}
    </div>
  )
}

function ConfiguracionMinuta({ tenantId }: { tenantId: string }) {
  const [c, setC] = useState<MinutaConfiguracion | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  useEffect(() => { configuracionMinuta(tenantId).then(setC).catch((e) => setError(mensajeDeError(e))) }, [tenantId])
  if (!c) return null
  async function guardar() {
    if (!c) return
    try { setC(await guardarConfiguracionMinuta(c, tenantId)); setAviso('Configuración guardada') } catch (e) { setError(mensajeDeError(e)) }
  }
  return (
    <div className="mt-6">
      <Tarjeta titulo="Configuración de la minuta de este cliente (§7.2)">
        {error && <Aviso>{error}</Aviso>}
        {aviso && <Aviso tipo="exito">{aviso}</Aviso>}
        <div className="grid gap-3 sm:grid-cols-3">
          <Selector etiqueta="Modo" value={c.modo} onChange={(e) => setC({ ...c, modo: e.target.value as MinutaConfiguracion['modo'] })} opciones={[{ valor: 'automatica', texto: 'Automático sin validación' }, { valor: 'con_validacion', texto: 'Con validación del despachador' }]} />
          <Campo etiqueta="Hora de envío" type="time" value={c.hora_envio.slice(0, 5)} onChange={(e) => setC({ ...c, hora_envio: e.target.value + ':00' })} />
          <Campo etiqueta="Ventana de validación (min)" type="number" min={5} max={240} value={c.ventana_validacion_min} onChange={(e) => setC({ ...c, ventana_validacion_min: Number(e.target.value) })} />
          <Campo etiqueta="Plazo de respuesta (h)" type="number" min={1} value={c.plazo_respuesta_horas} onChange={(e) => setC({ ...c, plazo_respuesta_horas: Number(e.target.value) })} />
          <Campo etiqueta="Cotización sin respuesta (días, rojo)" type="number" min={1} value={c.dias_cotizacion_sin_respuesta} onChange={(e) => setC({ ...c, dias_cotizacion_sin_respuesta: Number(e.target.value) })} />
          <Campo etiqueta="Presupuesto sin revisión (días, amarillo)" type="number" min={1} value={c.dias_presupuesto_sin_revision} onChange={(e) => setC({ ...c, dias_presupuesto_sin_revision: Number(e.target.value) })} />
          <Campo etiqueta="Interno sin actualización (días, amarillo)" type="number" min={1} value={c.dias_interno_sin_actualizar} onChange={(e) => setC({ ...c, dias_interno_sin_actualizar: Number(e.target.value) })} />
        </div>
        <div className="mt-3"><Boton onClick={() => void guardar()}>Guardar configuración</Boton></div>
      </Tarjeta>
    </div>
  )
}
