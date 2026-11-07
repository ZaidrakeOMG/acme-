import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { Aviso, Boton, Campo, Encabezado, Insignia, Modal, Selector, Tabla, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { useRecurso } from '../../hooks/useRecurso'
import { api, mensajeDeError } from '../../services/api'
import { configurarEscalacion, escalaciones as cargarEscalaciones } from '../../services/sla'
import type { AlertaEfectiva, Prestador, Rol, Tenant } from '../../types/api'
import { fecha as fmtFecha } from '../folios/comunes'

const UNIDADES: Record<string, string> = { porcentaje: '%', minutos: 'min', horas: 'h', dias: 'días', metros: 'm', cantidad: '' }
const CANALES: { valor: string; texto: string }[] = [
  { valor: 'app', texto: 'Bandeja' }, { valor: 'push', texto: 'Push' }, { valor: 'email', texto: 'Correo' },
  { valor: 'whatsapp', texto: 'WhatsApp (Fase 2)' }, { valor: 'sms', texto: 'SMS (Fase 2)' },
]
const CANALES_FASE_2 = new Set(['whatsapp', 'sms'])
const ROLES: Rol[] = ['admin_empresa', 'admin_un', 'supervisor_operadores', 'operador', 'admin_prestador', 'mesa_control',
                      'despachador', 'tecnico', 'supervisor_prestador', 'direccion_prestador']
const NOMBRE_MODULO: Record<string, string> = {
  contratos: 'Contratos y SLA', sla: 'Contratos y SLA', folios: 'Folios', preventivos: 'Preventivos',
  minuta: 'Minuta del día', seguimiento: 'Seguimiento', cotizaciones: 'Cotizaciones', presupuestos: 'Presupuestos',
  inventario: 'Inventario', caja_chica: 'Caja chica', activos: 'Equipos y activos', trabajos_especiales: 'Trabajos especiales',
  clasificacion: 'Clasificación', catalogos: 'Catálogos', formularios: 'Formularios', tecnicos: 'Técnicos',
}
type Vista = 'catalogo' | 'escalaciones' | 'supresiones' | 'historial'

interface Supresion {
  id: string; clave_alerta: string; entidad_id: string | null; razon: string; desde: string; hasta: string; activa: boolean
}
interface Historial {
  id: string; clave_alerta: string; entidad_tipo: string | null; entidad_id: string | null; umbral_en_momento: string | null
  datos_contexto_json: Record<string, unknown>; estado: string; timestamp_disparo: string; timestamp_vista: string | null
  atendida_at: string | null; nota_atencion: string; escalada: boolean
}

/** Configuración central de alertas y umbrales (§6.9.6): un solo lugar para umbral, canales, roles, escalaciones y supresiones. */
export function Alertas() {
  const { usuario } = useAuth()
  const esSuper = usuario?.rol === 'superadmin'
  const [params, setParams] = useSearchParams()
  const vista = (params.get('vista') as Vista) || 'catalogo'
  const tenants = useRecurso<Tenant[]>(esSuper ? '/tenants' : null)
  const prestadores = useRecurso<Prestador[]>(esSuper ? '/prestadores' : null)
  const [ambito, setAmbito] = useState('')
  const consulta = esSuper && ambito ? { [ambito.split(':')[0] === 't' ? 'tenant_id' : 'prestador_id']: ambito.split(':')[1] } : undefined
  const { datos, error, recargar } = useRecurso<AlertaEfectiva[]>(!esSuper || ambito ? '/alertas/configuracion' : null, consulta)
  const [editar, setEditar] = useState<AlertaEfectiva | null>(null)
  function ir(v: Vista) {
    const p = new URLSearchParams(params)
    p.set('vista', v)
    setParams(p)
  }
  const porModulo = new Map<string, AlertaEfectiva[]>()
  for (const a of datos ?? []) {
    const clave = NOMBRE_MODULO[a.modulo_origen] ?? a.modulo_origen
    porModulo.set(clave, [...(porModulo.get(clave) ?? []), a])
  }

  return (
    <div>
      <Encabezado titulo="Configuración central de alertas"
        descripcion="Un solo lugar para todos los umbrales del sistema. El Superadmin fija el valor por defecto y el rango; cada cliente y cada prestador ajustan su umbral, sus canales y sus roles destinatarios dentro de ese rango. Las alertas cuya fuente de datos llega en Fase 2 se muestran etiquetadas y no se pueden activar." />
      <div className="mb-3 flex flex-wrap gap-1" role="tablist" aria-label="Vistas de alertas">
        {([['catalogo', 'Catálogo y umbrales'], ['escalaciones', 'Escalaciones a Dirección'], ['supresiones', 'Supresiones'], ['historial', 'Historial']] as [Vista, string][]).map(([v, texto]) => (
          <button key={v} role="tab" aria-selected={vista === v} onClick={() => ir(v)}
            className={`rounded-lg px-3 py-1.5 text-sm ${vista === v ? 'bg-primario text-white' : 'border border-slate-300'}`}>{texto}</button>
        ))}
      </div>
      {esSuper && (
        <div className="mb-4 max-w-sm">
          <Selector etiqueta="Ámbito" value={ambito} onChange={(e) => setAmbito(e.target.value)}
            opciones={[
              { valor: '', texto: 'Selecciona un cliente o prestador…' },
              ...(tenants.datos ?? []).map((t) => ({ valor: `t:${t.id}`, texto: `Cliente · ${t.razon_social}` })),
              ...(prestadores.datos ?? []).map((p) => ({ valor: `p:${p.id}`, texto: `Prestador · ${p.razon_social}` })),
            ]} />
        </div>
      )}

      {vista === 'catalogo' && (
        <div className="space-y-4" data-testid="catalogo-alertas">
          {error && <Aviso>{error}</Aviso>}
          {porModulo.size === 0 && <p className="text-sm text-slate-500">{esSuper && !ambito ? 'Selecciona un ámbito' : 'Sin alertas'}</p>}
          {[...porModulo.entries()].sort().map(([modulo, filas]) => (
            <Tarjeta key={modulo} titulo={modulo}>
              <Tabla
                filas={filas.map((a) => ({ ...a, id: a.clave }))}
                columnas={[
                  { titulo: 'Alerta', celda: (a) => <div><p className="font-mono text-xs font-medium">{a.clave}</p>
                    <p className="text-xs text-slate-500">{a.descripcion}</p></div> },
                  { titulo: 'Default', celda: (a) => <span className="whitespace-nowrap text-xs text-slate-500">{Number(a.umbral_default)} {UNIDADES[a.tipo_umbral]}</span> },
                  { titulo: 'Rango', celda: (a) => <span className="whitespace-nowrap text-xs text-slate-500">{Number(a.umbral_min)}–{Number(a.umbral_max)}</span> },
                  { titulo: 'Umbral propio', celda: (a) => <span className="whitespace-nowrap">{Number(a.umbral_valor)} {UNIDADES[a.tipo_umbral]}
                    {a.personalizada && <> <Insignia tono="acento">propio</Insignia></>}</span> },
                  { titulo: 'Canales', celda: (a) => <span className="text-xs">{a.canales.join(', ')}</span> },
                  { titulo: 'Roles', celda: (a) => <span className="text-xs text-slate-500">{a.destinatarios_roles.join(', ') || '—'}</span> },
                  { titulo: 'Fase 2', celda: (a) => a.fase === 2
                    ? <Insignia tono="alerta">Fase 2</Insignia>
                    : <span className="text-xs text-slate-400">—</span> },
                  { titulo: 'Estado', celda: (a) => (a.activa ? <Insignia tono="ok">Activa</Insignia> : <Insignia>Inactiva</Insignia>) },
                  { titulo: '', celda: (a) => <Boton variante="fantasma" onClick={() => setEditar(a)}>{a.fase === 2 ? 'Ver' : 'Ajustar'}</Boton> },
                ]}
              />
            </Tarjeta>
          ))}
        </div>
      )}
      {vista === 'escalaciones' && <Escalaciones alertas={datos ?? []} />}
      {vista === 'supresiones' && <Supresiones consulta={consulta} alertas={datos ?? []} />}
      {vista === 'historial' && <HistorialAlertas />}

      <Modal titulo={editar?.clave ?? ''} abierto={editar !== null} alCerrar={() => setEditar(null)}>
        {editar && <FormularioAlerta alerta={editar} params={consulta} alGuardar={async () => { setEditar(null); await recargar() }} />}
      </Modal>
    </div>
  )
}

function FormularioAlerta({ alerta, params, alGuardar }: { alerta: AlertaEfectiva; params: Record<string, string | undefined> | undefined; alGuardar: () => Promise<void> }) {
  const [umbral, setUmbral] = useState(String(Number(alerta.umbral_valor)))
  const [canales, setCanales] = useState<Set<string>>(new Set(alerta.canales))
  const [roles, setRoles] = useState<Set<string>>(new Set(alerta.destinatarios_roles))
  const [activa, setActiva] = useState(alerta.activa)
  const [error, setError] = useState<string | null>(null)
  const min = Number(alerta.umbral_min)
  const max = Number(alerta.umbral_max)
  const fase2 = alerta.fase === 2

  async function guardar() {
    const valor = Number(umbral)
    if (Number.isNaN(valor) || valor < min || valor > max) return setError(`El umbral debe estar entre ${min} y ${max}`)
    if (canales.size === 0) return setError('Selecciona al menos un canal')
    try {
      await api(`/alertas/configuracion/${alerta.clave}`, {
        metodo: 'PUT',
        params,
        cuerpo: { umbral_valor: valor, canales: [...canales], activa: fase2 ? false : activa,
                  parametros: alerta.parametros, destinatarios_roles: [...roles] },
      })
      await alGuardar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  async function restablecer() {
    try {
      await api(`/alertas/configuracion/${alerta.clave}`, { metodo: 'DELETE', params })
      await alGuardar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  return (
    <div className="space-y-4" data-testid="form-alerta">
      <p className="text-sm text-slate-600">{alerta.descripcion}</p>
      {fase2 && <Aviso tipo="info">La fuente de datos de esta alerta (GPS o medidores) llega en Fase 2:
        puedes dejar su umbral preparado, pero no se puede activar.</Aviso>}
      {alerta.escalacion_de && <Aviso tipo="info">Escala desde <strong>{alerta.escalacion_de}</strong>: el umbral se mide
        desde que esa alerta se disparó, no desde el hecho original.</Aviso>}
      {error && <Aviso>{error}</Aviso>}
      <label className="block text-sm">
        <span className="mb-1 block font-medium text-slate-700">Umbral ({UNIDADES[alerta.tipo_umbral] || alerta.tipo_umbral}) — rango {min} a {max}, default {Number(alerta.umbral_default)}</span>
        <input type="number" min={min} max={max} value={umbral} onChange={(e) => setUmbral(e.target.value)}
          aria-label="Umbral" className="w-full rounded-lg border border-slate-300 px-3 py-2" />
      </label>
      <fieldset className="text-sm">
        <legend className="mb-1 font-medium text-slate-700">Canales</legend>
        <div className="flex flex-wrap gap-4">
          {CANALES.map((c) => (
            <label key={c.valor} className="flex items-center gap-2">
              <input type="checkbox" checked={canales.has(c.valor)} disabled={CANALES_FASE_2.has(c.valor)}
                onChange={(e) => { const s = new Set(canales); if (e.target.checked) s.add(c.valor); else s.delete(c.valor); setCanales(s) }} />
              {c.texto}
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset className="text-sm">
        <legend className="mb-1 font-medium text-slate-700">Roles destinatarios</legend>
        <div className="grid grid-cols-2 gap-1">
          {ROLES.map((r) => (
            <label key={r} className="flex items-center gap-2 text-xs">
              <input type="checkbox" checked={roles.has(r)}
                onChange={(e) => { const s = new Set(roles); if (e.target.checked) s.add(r); else s.delete(r); setRoles(s) }} />
              {r}
            </label>
          ))}
        </div>
      </fieldset>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={activa && !fase2} disabled={fase2} onChange={(e) => setActiva(e.target.checked)} /> Alerta activa
      </label>
      <div className="flex gap-2">
        <Boton className="flex-1" onClick={() => void guardar()}>Guardar</Boton>
        {alerta.personalizada && <Boton variante="secundario" onClick={() => void restablecer()}>Restablecer default</Boton>}
      </div>
    </div>
  )
}

function Escalaciones({ alertas }: { alertas: AlertaEfectiva[] }) {
  const { usuario } = useAuth()
  const [filas, setFilas] = useState<AlertaEfectiva[]>([])
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [cadena, setCadena] = useState<Record<string, string>>({})
  const cargar = useCallback(async () => {
    try { setFilas(await cargarEscalaciones()) } catch (e) { setError(mensajeDeError(e)) }
  }, [])
  useEffect(() => { void cargar() }, [cargar])
  const configura = usuario?.rol === 'superadmin' || usuario?.rol === 'admin_prestador'

  async function guardar(clave: string, origen: string | null) {
    setError(null)
    try {
      await configurarEscalacion(clave, origen)
      setAviso(origen ? `${clave} escala desde ${origen}` : `${clave} ya no escala de ninguna alerta`)
      await cargar()
    } catch (e) { setError(mensajeDeError(e)) }
  }

  return (
    <Tarjeta titulo="Escalaciones a la Dirección del prestador">
      <p className="mb-2 text-sm text-slate-600">§6.9.6: una escalación se mide desde el momento en que se disparó su alerta
        origen, no desde el hecho que la provocó, y su umbral se configura de forma independiente. Así la Dirección solo
        recibe lo que la operación no resolvió en el tiempo pactado.</p>
      {error && <Aviso>{error}</Aviso>}
      {aviso && <Aviso tipo="exito">{aviso}</Aviso>}
      <div data-testid="escalaciones-alertas">
        <Tabla filas={filas.map((f) => ({ ...f, id: f.clave }))} vacio="Sin escalaciones configuradas" columnas={[
          { titulo: 'Escalación', celda: (a) => <div><p className="font-mono text-xs font-medium">{a.clave}</p>
            <p className="text-xs text-slate-500">{a.descripcion}</p></div> },
          { titulo: 'Se mide desde', celda: (a) => <span className="font-mono text-xs">{a.escalacion_de}</span> },
          { titulo: 'Umbral', celda: (a) => <span className="whitespace-nowrap">{Number(a.umbral_valor)} {UNIDADES[a.tipo_umbral]}</span> },
          { titulo: 'Destinatarios', celda: (a) => <span className="text-xs text-slate-500">{a.destinatarios_roles.join(', ')}</span> },
          { titulo: 'Cambiar origen', celda: (a) => configura ? (
            <div className="flex flex-wrap items-end gap-1">
              <select aria-label={`Origen de ${a.clave}`} value={cadena[a.clave] ?? a.escalacion_de ?? ''}
                onChange={(e) => setCadena({ ...cadena, [a.clave]: e.target.value })}
                className="rounded border border-slate-300 px-2 py-1 text-xs">
                <option value="">(sin escalación)</option>
                {alertas.filter((x) => x.clave !== a.clave).map((x) => <option key={x.clave} value={x.clave}>{x.clave}</option>)}
              </select>
              <Boton variante="secundario" onClick={() => void guardar(a.clave, cadena[a.clave] || null)}>Guardar</Boton>
            </div>
          ) : <span className="text-xs text-slate-500">—</span> },
        ]} />
      </div>
    </Tarjeta>
  )
}

function Supresiones({ consulta, alertas }: { consulta: Record<string, string | undefined> | undefined; alertas: AlertaEfectiva[] }) {
  const [filas, setFilas] = useState<Supresion[]>([])
  const [soloActivas, setSoloActivas] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [nueva, setNueva] = useState(false)
  const cargar = useCallback(async () => {
    try { setFilas(await api<Supresion[]>('/alertas/supresiones', { params: { ...consulta, solo_activas: soloActivas } })) }
    catch (e) { setError(mensajeDeError(e)) }
  }, [consulta, soloActivas])
  useEffect(() => { void cargar() }, [cargar])

  async function ejecutar(fn: () => Promise<unknown>, texto: string) {
    setError(null)
    try { await fn(); setNueva(false); setAviso(texto); await cargar() } catch (e) { setError(mensajeDeError(e)) }
  }

  return (
    <Tarjeta titulo="Supresiones temporales" acciones={<Boton onClick={() => setNueva(true)}>Suprimir una alerta</Boton>}>
      <p className="mb-2 text-sm text-slate-600">Silencia una alerta por un período, con razón documentada. Solo los roles
        administradores pueden hacerlo; al vencer, la alerta vuelve sola.</p>
      <label className="mb-2 flex items-center gap-1 text-sm"><input type="checkbox" checked={soloActivas}
        onChange={(e) => setSoloActivas(e.target.checked)} /> Solo las vigentes</label>
      {error && <Aviso>{error}</Aviso>}
      {aviso && <Aviso tipo="exito">{aviso}</Aviso>}
      <div data-testid="supresiones-alertas">
        <Tabla filas={filas} vacio="Sin supresiones" columnas={[
          { titulo: 'Alerta', celda: (s) => <span className="font-mono text-xs">{s.clave_alerta}</span> },
          { titulo: 'Alcance', celda: (s) => <span className="text-xs">{s.entidad_id ? 'una entidad' : 'toda la clave'}</span> },
          { titulo: 'Período', celda: (s) => <span className="text-xs">{fmtFecha(s.desde)} → {fmtFecha(s.hasta)}</span> },
          { titulo: 'Razón', celda: (s) => <span className="text-xs">{s.razon}</span> },
          { titulo: 'Estado', celda: (s) => s.activa ? <Insignia tono="alerta">Vigente</Insignia> : <Insignia>Terminada</Insignia> },
          { titulo: '', celda: (s) => s.activa
            ? <Boton variante="secundario" onClick={() => void ejecutar(() => api(`/alertas/supresiones/${s.id}/desactivar`, { metodo: 'POST', params: consulta }), 'Supresión terminada')}>Terminar</Boton>
            : null },
        ]} />
      </div>
      {nueva && <FormSupresion alertas={alertas} alCerrar={() => setNueva(false)}
        alGuardar={(cuerpo) => ejecutar(() => api('/alertas/supresiones', { metodo: 'POST', params: consulta, cuerpo }), 'Alerta suprimida')} />}
    </Tarjeta>
  )
}

function FormSupresion({ alertas, alCerrar, alGuardar }: {
  alertas: AlertaEfectiva[]
  alCerrar: () => void
  alGuardar: (cuerpo: Record<string, unknown>) => Promise<void>
}) {
  const enUnaSemana = new Date(Date.now() + 7 * 86400000)
  const [d, setD] = useState({ clave: alertas[0]?.clave ?? '', razon: '', hasta: enUnaSemana.toISOString().slice(0, 10) })
  return (
    <Modal titulo="Suprimir una alerta temporalmente" abierto alCerrar={alCerrar}>
      <div className="space-y-3" data-testid="form-supresion">
        <Selector etiqueta="Alerta" value={d.clave} onChange={(e) => setD({ ...d, clave: e.target.value })}
          opciones={alertas.map((a) => ({ valor: a.clave, texto: a.clave }))} />
        <Campo etiqueta="Hasta" type="date" value={d.hasta} onChange={(e) => setD({ ...d, hasta: e.target.value })} />
        <Campo etiqueta="Razón" value={d.razon} onChange={(e) => setD({ ...d, razon: e.target.value })} />
        <div className="flex gap-2">
          <Boton disabled={!d.clave || d.razon.trim().length < 3} onClick={() => void alGuardar({
            clave_alerta: d.clave, razon: d.razon, hasta: new Date(`${d.hasta}T23:59:00`).toISOString(),
          })}>Suprimir</Boton>
          <Boton variante="secundario" onClick={alCerrar}>Cancelar</Boton>
        </div>
      </div>
    </Modal>
  )
}

function HistorialAlertas() {
  const [clave, setClave] = useState('')
  const { datos, error } = useRecurso<Historial[]>('/alertas/historial', { clave: clave || undefined, limite: '200' })
  return (
    <Tarjeta titulo="Historial de alertas disparadas">
      <div className="mb-2 max-w-sm"><Campo etiqueta="Filtrar por clave" value={clave} onChange={(e) => setClave(e.target.value)} /></div>
      {error && <Aviso>{error}</Aviso>}
      <div data-testid="historial-alertas">
        <Tabla filas={datos ?? []} vacio="Sin alertas disparadas" columnas={[
          { titulo: 'Alerta', celda: (h) => <span className="font-mono text-xs">{h.clave_alerta}</span> },
          { titulo: 'Disparo', celda: (h) => <span className="text-xs">{fmtFecha(h.timestamp_disparo)}</span> },
          { titulo: 'Umbral', celda: (h) => h.umbral_en_momento == null ? '—' : Number(h.umbral_en_momento) },
          { titulo: 'Entidad', celda: (h) => <span className="text-xs text-slate-500">{h.entidad_tipo ?? '—'}</span> },
          { titulo: 'Estado', celda: (h) => <div className="flex flex-wrap gap-1">
            <Insignia tono={h.atendida_at ? 'ok' : h.timestamp_vista ? 'acento' : 'alerta'}>
              {h.atendida_at ? 'Atendida' : h.timestamp_vista ? 'Vista' : 'Sin ver'}</Insignia>
            {h.escalada && <Insignia tono="alerta">Escalada</Insignia>}
          </div> },
          { titulo: 'Nota', celda: (h) => <span className="text-xs text-slate-500">{h.nota_atencion || '—'}</span> },
        ]} />
      </div>
    </Tarjeta>
  )
}
