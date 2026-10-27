import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'
import { Aviso, Boton, Campo, Insignia, Selector, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { mensajeDeError } from '../../services/api'
import { aprobarFolio, configuracionAprobacion, guardarNiveles, guardarPoliticas, guardarReglas, pendientesAprobacion, rechazarFolio, reglasConUmbrales, umbralesDe } from '../../services/folios'
import { notificar } from '../../services/notificaciones'
import type { ConfiguracionAprobacion, NivelConfig, PendienteAprobacion, RazonRechazo } from '../../types/folios'
import { NOMBRE_TIMEOUT, RAZONES_RECHAZO } from '../../types/folios'
import { SeveridadInsignia, antiguedad, fecha } from './comunes'

/** Bandeja del aprobador (§6.8.7): solo Aprobar / Rechazar; el rechazo exige una de las cuatro razones. */
export function Aprobaciones() {
  const { usuario } = useAuth()
  const [pendientes, setPendientes] = useState<PendienteAprobacion[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [rechazando, setRechazando] = useState<string | null>(null)
  const [razon, setRazon] = useState<RazonRechazo | null>(null)

  const cargar = useCallback(async () => {
    try {
      setPendientes(await pendientesAprobacion())
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }, [])
  useEffect(() => { void cargar() }, [cargar])

  async function aprobar(p: PendienteAprobacion) {
    try {
      await aprobarFolio(p.folio.id, 'app')
      notificar(`Folio ${p.folio.numero_folio} aprobado en Nivel ${p.flujo.nivel_actual}`)
      setAviso(`Folio ${p.folio.numero_folio} aprobado`)
      await cargar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  async function rechazar(p: PendienteAprobacion) {
    if (!razon) return
    try {
      await rechazarFolio(p.folio.id, razon, 'app')
      notificar(`Folio ${p.folio.numero_folio} rechazado`, RAZONES_RECHAZO.find((r) => r.valor === razon)?.destino ?? '')
      setAviso(`Folio ${p.folio.numero_folio} rechazado y derivado a ${RAZONES_RECHAZO.find((r) => r.valor === razon)?.destino ?? ''}`)
      setRechazando(null)
      setRazon(null)
      await cargar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  if (!usuario) return null
  return (
    <div className="space-y-6">
      <div>
        <Link to="/folios" className="text-xs text-primario underline">← Folios</Link>
        <h1 className="text-2xl font-semibold text-slate-900">Folios pendientes de tu autorización</h1>
        <p className="text-sm text-slate-600">Tienes exactamente dos acciones: Aprobar o Rechazar. El rechazo nunca es un callejón sin salida: cada razón deriva el folio a un módulo de seguimiento.</p>
      </div>
      {error && <Aviso>{error}</Aviso>}
      {aviso && <Aviso tipo="exito">{aviso}</Aviso>}
      {pendientes === null ? <p className="text-sm text-slate-500">Cargando…</p> : pendientes.length === 0 ? (
        <p className="text-sm text-slate-500">No tienes folios pendientes de autorización.</p>
      ) : (
        <div className="space-y-3">
          {pendientes.map((p) => (
            <article key={p.folio.id} data-testid={`pendiente-${p.folio.numero_folio}`} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Link to={`/folios/${p.folio.id}`} className="font-mono text-sm font-semibold text-primario underline">{p.folio.numero_folio}</Link>
                    <SeveridadInsignia severidad={p.folio.severidad} />
                    <Insignia tono="acento">Nivel {p.flujo.nivel_actual} de {p.flujo.nivel_maximo_requerido}</Insignia>
                    {p.flujo.estado === 'bloqueado' && <Insignia tono="alerta">Bloqueado por timeout</Insignia>}
                    {p.folio.criticidad && <Insignia>Criticidad {p.folio.criticidad}</Insignia>}
                  </div>
                  <p className="mt-1 text-sm text-slate-800">{p.folio.descripcion}</p>
                  <p className="mt-1 text-xs text-slate-500">
                    {p.folio.un_codigo} · {p.folio.un_nombre} · {p.folio.equipo_codigo} {p.folio.equipo_nombre} · {p.folio.tipo_falla} · {p.folio.tipo_folio}
                    {p.folio.monto_estimado && <> · monto estimado ${Number(p.folio.monto_estimado).toLocaleString('es-MX')}</>}
                    · hace {antiguedad(p.folio.antiguedad_horas)}{p.vence_at && <> · vence {fecha(p.vence_at)}</>}
                  </p>
                </div>
                {rechazando !== p.folio.id && (
                  <div className="flex gap-2">
                    <Boton onClick={() => void aprobar(p)}>Aprobar</Boton>
                    <Boton variante="peligro" onClick={() => { setRechazando(p.folio.id); setRazon(null) }}>Rechazar</Boton>
                  </div>
                )}
              </div>
              {rechazando === p.folio.id && (
                <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3" data-testid="razones-rechazo">
                  <p className="mb-2 text-sm font-medium text-red-900">Razón del rechazo</p>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {RAZONES_RECHAZO.map((r) => (
                      <label key={r.valor} className={`cursor-pointer rounded-lg border p-2 text-sm ${razon === r.valor ? 'border-red-500 bg-white' : 'border-red-100 bg-white/60'}`}>
                        <input type="radio" name={`razon-${p.folio.id}`} className="mr-2" checked={razon === r.valor} onChange={() => setRazon(r.valor)} />
                        {r.texto} <span className="block text-xs text-slate-500">{r.destino}</span>
                      </label>
                    ))}
                  </div>
                  <div className="mt-2 flex gap-2">
                    <Boton variante="peligro" disabled={!razon} onClick={() => void rechazar(p)}>Confirmar rechazo</Boton>
                    <Boton variante="fantasma" onClick={() => { setRechazando(null); setRazon(null) }}>Volver</Boton>
                  </div>
                </div>
              )}
            </article>
          ))}
        </div>
      )}
      {(usuario.rol === 'admin_empresa' || usuario.rol === 'superadmin') && <ConfiguracionFlujo />}
    </div>
  )
}

const ROLES_APROBADOR = [{ valor: 'admin_un', texto: 'Admin UN' }, { valor: 'supervisor_operadores', texto: 'Supervisor de operadores (regional)' }, { valor: 'admin_empresa', texto: 'Admin empresa' }]

/** Configuración del flujo para el Admin empresa: umbrales A/B, reglas por criterio, actor y timeout por nivel, políticas. */
function ConfiguracionFlujo() {
  const [cfg, setCfg] = useState<ConfiguracionAprobacion | null>(null)
  const [umbrales, setUmbrales] = useState({ a: '5000', b: '20000' })
  const [niveles, setNiveles] = useState<NivelConfig[]>([])
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)

  const cargar = useCallback(async () => {
    try {
      const c = await configuracionAprobacion()
      setCfg(c)
      const u = umbralesDe(c.reglas)
      setUmbrales({ a: String(u.a), b: String(u.b) })
      const porDefecto: NivelConfig['rol_aprobador'][] = ['admin_un', 'supervisor_operadores', 'admin_empresa']
      setNiveles([1, 2, 3].map((n): NivelConfig => c.niveles.find((x) => x.nivel === n) ?? { nivel: n, rol_aprobador: porDefecto[n - 1]!, tiempo_limite_horas: 24, comportamiento_timeout: 'bloquear_alertar', notificar_por_json: ['push', 'app'] }))
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }, [])
  useEffect(() => { void cargar() }, [cargar])

  if (!cfg) return null
  const tieneRegla = (criterio: string, nivel: number) => cfg.reglas.some((r) => r.criterio === criterio && r.nivel === nivel && r.activa)

  async function guardar() {
    if (!cfg) return
    setError(null)
    try {
      await guardarReglas(reglasConUmbrales(cfg.reglas, Number(umbrales.a), Number(umbrales.b)))
      await guardarNiveles(niveles)
      setAviso('Configuración guardada')
      await cargar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  async function alternarRegla(criterio: 'criticidad' | 'tipo_trabajo', nivel: number, regla: { operador: string; valor_json: Record<string, unknown> }) {
    if (!cfg) return
    const existe = tieneRegla(criterio, nivel)
    const otras = cfg.reglas.filter((r) => !(r.criterio === criterio && r.nivel === nivel))
    const nuevas = existe ? otras : [...otras, { nivel, criterio, activa: true, ...regla }]
    try {
      await guardarReglas(nuevas)
      await cargar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  async function politica(clave: keyof ConfiguracionAprobacion['politicas'], valor: boolean | string) {
    try {
      await guardarPoliticas({ [clave]: valor })
      await cargar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  return (
    <Tarjeta titulo="Configuración del flujo de aprobación (Admin empresa)">
      {error && <div className="mb-3"><Aviso>{error}</Aviso></div>}
      {aviso && <div className="mb-3"><Aviso tipo="exito">{aviso}</Aviso></div>}
      <div className="grid gap-5 lg:grid-cols-2">
        <section>
          <h3 className="mb-2 text-sm font-semibold text-slate-800">Umbrales por monto estimado (MXN)</h3>
          <div className="grid grid-cols-2 gap-2">
            <Campo etiqueta="Umbral A (Nivel 1 si monto < A)" type="number" min={0} value={umbrales.a} onChange={(e) => setUmbrales({ ...umbrales, a: e.target.value })} />
            <Campo etiqueta="Umbral B (Nivel 3 si monto ≥ B)" type="number" min={0} value={umbrales.b} onChange={(e) => setUmbrales({ ...umbrales, b: e.target.value })} />
          </div>
          <h3 className="mb-2 mt-4 text-sm font-semibold text-slate-800">Otros criterios (la regla más restrictiva gana)</h3>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={tieneRegla('criticidad', 2)} onChange={() => void alternarRegla('criticidad', 2, { operador: 'en', valor_json: { valores: ['A', 'B'] } })} /> Activos A/B suben al menos a Nivel 2</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={tieneRegla('tipo_trabajo', 1)} onChange={() => void alternarRegla('tipo_trabajo', 1, { operador: 'igual', valor_json: { tipo: 'preventivo' } })} /> Preventivo → Nivel 1</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={tieneRegla('tipo_trabajo', 2)} onChange={() => void alternarRegla('tipo_trabajo', 2, { operador: 'igual', valor_json: { tipo: 'especial' } })} /> Trabajo especial → mínimo Nivel 2</label>
          <h3 className="mb-2 mt-4 text-sm font-semibold text-slate-800">Políticas</h3>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={cfg.politicas.autorizacion_automatica_criticos} onChange={(e) => void politica('autorizacion_automatica_criticos', e.target.checked)} /> Autorización automática de activos críticos (A/B)</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={cfg.politicas.aprobacion_secuencial} onChange={(e) => void politica('aprobacion_secuencial', e.target.checked)} /> Flujo secuencial (inicia en Nivel 1 y sube hasta el requerido)</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={cfg.politicas.bloqueo_total_duplicados} onChange={(e) => void politica('bloqueo_total_duplicados', e.target.checked)} /> Bloqueo total de folios duplicados</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={cfg.politicas.revision_obligatoria_garantia} onChange={(e) => void politica('revision_obligatoria_garantia', e.target.checked)} /> Revisión obligatoria de equipos en garantía</label>
          <p className="mt-2 text-xs text-slate-500">Prefijo de folio: <span className="font-mono">{cfg.politicas.prefijo_folio}</span> · último número {cfg.politicas.ultimo_numero}</p>
        </section>
        <section>
          <h3 className="mb-2 text-sm font-semibold text-slate-800">Niveles: actor, tiempo límite y comportamiento ante timeout</h3>
          <div className="space-y-3">
            {niveles.map((n, i) => (
              <div key={n.nivel} className="rounded-lg border border-slate-200 p-3">
                <p className="mb-2 text-sm font-medium">Nivel {n.nivel}{n.nivel === 3 && <span className="ml-2 text-xs font-normal text-slate-500">(nunca escala ni autoriza automáticamente)</span>}</p>
                <div className="grid gap-2 sm:grid-cols-3">
                  <Selector etiqueta="Aprobador" value={n.rol_aprobador} onChange={(e) => setNiveles(niveles.map((x, j) => (j === i ? { ...x, rol_aprobador: e.target.value as NivelConfig['rol_aprobador'] } : x)))} opciones={ROLES_APROBADOR} />
                  <Campo etiqueta="Tiempo límite (h)" type="number" min={1} value={n.tiempo_limite_horas} onChange={(e) => setNiveles(niveles.map((x, j) => (j === i ? { ...x, tiempo_limite_horas: Number(e.target.value) } : x)))} />
                  <Selector etiqueta="Al vencer" value={n.comportamiento_timeout} onChange={(e) => setNiveles(niveles.map((x, j) => (j === i ? { ...x, comportamiento_timeout: e.target.value as NivelConfig['comportamiento_timeout'] } : x)))}
                            opciones={(Object.keys(NOMBRE_TIMEOUT) as (keyof typeof NOMBRE_TIMEOUT)[]).filter((k) => n.nivel < 3 || k === 'bloquear_alertar' || k === 'depende_criticidad').map((k) => ({ valor: k, texto: NOMBRE_TIMEOUT[k] }))} />
                </div>
              </div>
            ))}
          </div>
          <div className="mt-3 flex justify-end"><Boton onClick={() => void guardar()}>Guardar umbrales y niveles</Boton></div>
        </section>
      </div>
    </Tarjeta>
  )
}
