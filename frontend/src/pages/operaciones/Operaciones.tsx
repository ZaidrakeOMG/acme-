import { Component, lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ErrorInfo, ReactNode } from 'react'
import { Link } from 'react-router'
import { Aviso, Boton, Encabezado, Insignia, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { mensajeDeError } from '../../services/api'
import { atenderAlerta, cerrarJornadaDe, recorridoDe, suscribirOperacion, tablero } from '../../services/operacion'
import { aceptarPropuesta, propuestasPendientes, rechazarPropuesta } from '../../services/rutas'
import type { Propuesta } from '../../types/rutas'
import { NOMBRE_DISPARADOR, hora as horaRuta } from '../../types/rutas'
import type {
  AlertaEnTablero, EventoOperacion, FolioEnTablero, PuntoRecorrido, Tablero, TecnicoEnTablero,
} from '../../types/operaciones'
import { COLOR_ESTATUS, NOMBRE_ESTATUS } from '../../types/operaciones'
import { fecha as fmtFecha } from '../folios/comunes'

const Mapa = lazy(() => import('./MapaOperaciones'))

const NOMBRE_ALERTA: Record<string, string> = {
  TECNICO_TIEMPO_MUERTO: 'Técnico detenido',
  TECNICO_SIN_SENAL: 'Técnico sin señal',
  TECNICO_DESVIO_RUTA: 'Desvío de ruta',
  SLA_RESPUESTA_EN_RIESGO: 'SLA de respuesta en riesgo',
  SLA_RESOLUCION_EN_RIESGO: 'SLA de resolución en riesgo',
  SLA_INCUMPLIDO: 'SLA incumplido',
  FOLIO_AUTORIZADO_SIN_TECNICO: 'Folio autorizado sin técnico',
}

/** Un fallo del mapa no debe tumbar el tablero: los paneles son lo que el despachador necesita para trabajar. */
class SiFallaElMapa extends Component<{ children: ReactNode }, { fallo: boolean }> {
  constructor(props: { children: ReactNode }) {
    super(props)
    this.state = { fallo: false }
  }

  static getDerivedStateFromError() {
    return { fallo: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.warn('El mapa no se pudo dibujar', error, info)
  }

  render() {
    if (this.state.fallo) {
      return (
        <div className="flex h-40 items-center justify-center rounded-xl border border-slate-200 bg-slate-50 text-sm text-slate-600">
          El mapa no se pudo dibujar en este navegador. Los paneles siguen funcionando.
        </div>
      )
    }
    return this.props.children
  }
}

/**
 * Pantalla de operaciones en tiempo real (§6.8.4): mapa en vivo, panel de técnicos, folios activos con el contador
 * de SLA, feed de alertas con acción directa e indicadores globales de jornada. Se actualiza por WebSocket (con
 * respaldo SSE) y refresca el tablero completo cada minuto por si se perdió algún evento.
 *
 * F2-06 cerró lo que faltaba: el desvío de ruta pinta la fila de amarillo y las propuestas de reasignación
 * automática se aceptan desde aquí. La hora estimada de llegada por parada vive en «Rutas del día», que es donde
 * está la ruta completa; lo único que sigue dependiendo de un proveedor de pago es el ETA **con tráfico**.
 */
export function Operaciones() {
  const { usuario } = useAuth()
  const [datos, setDatos] = useState<Tablero | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [conexion, setConexion] = useState<'conectando' | 'en_vivo' | 'reconectando'>('conectando')
  const [ultimoEvento, setUltimoEvento] = useState<string | null>(null)
  const [seleccionado, setSeleccionado] = useState<string | null>(null)
  const [recorrido, setRecorrido] = useState<PuntoRecorrido[]>([])
  const [centrarEn, setCentrarEn] = useState<{ lat: number; lng: number; zoom?: number } | null>(null)
  const [orden, setOrden] = useState<'estatus' | 'folios' | 'tiempo'>('estatus')
  const vivo = useRef(true)

  const cargar = useCallback(async () => {
    try {
      const t = await tablero()
      if (vivo.current) setDatos(t)
    } catch (e) {
      if (vivo.current) setError(mensajeDeError(e))
    }
  }, [])

  useEffect(() => {
    vivo.current = true
    void cargar()
    const refresco = setInterval(() => void cargar(), 60000)
    return () => { vivo.current = false; clearInterval(refresco) }
  }, [cargar])

  // Eventos en vivo: se aplican sobre el estado que ya está, sin volver a pedir el tablero completo.
  useEffect(() => {
    const cerrar = suscribirOperacion((e: EventoOperacion) => {
      if (e.evento === 'pong' || e.evento === 'conectado') return
      setUltimoEvento(new Date().toISOString())
      setDatos((previo) => aplicarEvento(previo, e))
      if (e.evento === 'alerta' || e.evento === 'escalacion') void cargar()
    }, setConexion)
    return cerrar
  }, [cargar])

  async function verRecorrido(tecnicoId: string) {
    setSeleccionado(tecnicoId)
    setError(null)
    try {
      const r = await recorridoDe(tecnicoId, datos?.parametros.horas_recorrido ?? 2)
      setRecorrido(r.puntos)
      const ultimo = r.puntos.at(-1)
      if (ultimo) setCentrarEn({ lat: ultimo.lat, lng: ultimo.lng, zoom: 15 })
    } catch (e) { setError(mensajeDeError(e)) }
  }

  const tecnicos = useMemo(() => ordenarTecnicos(datos?.tecnicos ?? [], orden), [datos?.tecnicos, orden])
  const elegido = tecnicos.find((t) => t.tecnico_id === seleccionado) ?? null
  const enJornada = tecnicos.filter((t) => t.en_jornada)

  if (!usuario) return null

  return (
    <div>
      <Encabezado titulo="Operaciones en tiempo real"
        descripcion="Dónde está cada técnico, qué está haciendo, qué folios están por incumplir el SLA y qué alertas piden acción. La pantalla se actualiza sola."
        acciones={
          <div className="flex items-center gap-2">
            <Insignia tono={conexion === 'en_vivo' ? 'ok' : 'alerta'}>
              {conexion === 'en_vivo' ? 'Datos en vivo' : conexion === 'conectando' ? 'Conectando…' : 'Reconectando…'}
            </Insignia>
            <Boton variante="secundario" onClick={() => void cargar()}>Actualizar</Boton>
          </div>
        } />

      {error && <div className="mb-3"><Aviso>{error}</Aviso></div>}
      {aviso && <div className="mb-3"><Aviso tipo="exito">{aviso}</Aviso></div>}
      {datos?.solo_lectura && (
        <div className="mb-3"><Aviso tipo="info">Tu rol ve esta pantalla en modo lectura.</Aviso></div>
      )}

      <Indicadores datos={datos} enJornada={enJornada.length} ultimoEvento={ultimoEvento} />

      <div className="mt-4 grid gap-4 xl:grid-cols-[2fr_1fr]">
        <div className="space-y-4">
          <SiFallaElMapa>
            <Suspense fallback={<div className="h-40 animate-pulse rounded-xl bg-slate-100" />}>
              <Mapa tecnicos={enJornada} unidades={datos?.unidades ?? []} recorrido={recorrido}
                    seleccionado={seleccionado} centrarEn={centrarEn}
                    alElegirTecnico={(id) => void verRecorrido(id)} />
            </Suspense>
          </SiFallaElMapa>
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
            <span className="font-medium">Centrar:</span>
            {enJornada.filter((t) => t.lat != null).map((t) => (
              <button key={t.tecnico_id} className="rounded border border-slate-300 px-2 py-0.5 hover:bg-slate-50"
                onClick={() => setCentrarEn({ lat: t.lat!, lng: t.lng!, zoom: 16 })}>{t.nombre}</button>
            ))}
            {(datos?.unidades ?? []).map((u) => (
              <button key={u.un_id} className="rounded border border-slate-300 px-2 py-0.5 hover:bg-slate-50"
                onClick={() => setCentrarEn({ lat: u.lat, lng: u.lng, zoom: 16 })}>{u.codigo}</button>
            ))}
            <button className="rounded border border-slate-300 px-2 py-0.5 hover:bg-slate-50"
              onClick={() => setCentrarEn({ lat: 19.4326, lng: -99.1332, zoom: 11 })}>Todo el mercado</button>
            <span className="text-slate-400">· Fila roja: alerta activa. Fila amarilla: desvío de ruta (§6.8.4).</span>
          </div>

          <PanelFolios folios={datos?.folios ?? []} />
        </div>

        <div className="space-y-4">
          <PanelPropuestas />
          <PanelTecnicos tecnicos={tecnicos} orden={orden} alOrdenar={setOrden} seleccionado={seleccionado}
            alElegir={(id) => void verRecorrido(id)} />
          {elegido && (
            <DetalleTecnico tecnico={elegido} recorrido={recorrido}
              folios={(datos?.folios ?? []).filter((f) => f.tecnico_id === elegido.usuario_id)}
              soloLectura={datos?.solo_lectura ?? false}
              alCerrarJornada={async (jornadaId) => {
                try {
                  await cerrarJornadaDe(jornadaId)
                  setAviso('Jornada cerrada')
                  await cargar()
                } catch (e) { setError(mensajeDeError(e)) }
              }} />
          )}
          <PanelAlertas alertas={datos?.alertas ?? []} tecnicos={datos?.tecnicos ?? []}
            alVerTecnico={(id) => void verRecorrido(id)}
            alAtender={async (id) => {
              try {
                await atenderAlerta(id)
                setAviso('Alerta marcada como atendida')
                await cargar()
              } catch (e) { setError(mensajeDeError(e)) }
            }} />
        </div>
      </div>
    </div>
  )
}

/** Aplica un evento del WebSocket al tablero: solo toca al técnico que cambió (§6.8.4). */
export function aplicarEvento(previo: Tablero | null, e: EventoOperacion): Tablero | null {
  if (!previo || !e.tecnico_id) return previo
  const tecnicos = previo.tecnicos.map((t) => {
    if (t.tecnico_id !== e.tecnico_id) return t
    if (e.evento === 'posicion') {
      return { ...t, lat: e.lat ?? t.lat, lng: e.lng ?? t.lng,
               ultima_posicion_at: e.capturada_at ?? t.ultima_posicion_at,
               bateria_pct: e.bateria_pct ?? t.bateria_pct,
               estatus: e.estatus ?? t.estatus,
               estatus_texto: e.estatus ? NOMBRE_ESTATUS[e.estatus] : t.estatus_texto }
    }
    if (e.evento === 'estatus' && e.estatus) {
      return { ...t, estatus: e.estatus, estatus_texto: NOMBRE_ESTATUS[e.estatus] }
    }
    if (e.evento === 'jornada') {
      const cerrada = e.estado === 'cerrada'
      return { ...t, en_jornada: !cerrada, estatus: cerrada ? 'fuera_de_jornada' : t.estatus,
               estatus_texto: cerrada ? NOMBRE_ESTATUS.fuera_de_jornada : t.estatus_texto }
    }
    if (e.evento === 'alerta') {
      return { ...t, alerta: { tipo: e.clave ?? e.tipo ?? '', desde: new Date().toISOString(), escalada: false } }
    }
    if (e.evento === 'escalacion' && t.alerta) {
      return { ...t, alerta: { ...t.alerta, escalada: true } }
    }
    if (e.evento === 'respuesta_alerta') {
      return { ...t, alerta: null, respuesta_tecnico: e.respuesta ?? null }
    }
    return t
  })
  return { ...previo, tecnicos }
}

/** 219 minutos se lee peor que «3 h 39 min». */
function minutosLegibles(minutos: number): string {
  if (minutos < 60) return `${minutos} min`
  const horas = Math.floor(minutos / 60)
  const resto = minutos % 60
  return resto === 0 ? `${horas} h` : `${horas} h ${resto} min`
}

function ordenarTecnicos(tecnicos: TecnicoEnTablero[], orden: 'estatus' | 'folios' | 'tiempo') {
  const peso: Record<string, number> = { sin_senal: 0, en_servicio: 1, en_ruta: 2, pausa: 3, fuera_de_jornada: 4 }
  const copia = [...tecnicos]
  if (orden === 'folios') copia.sort((a, b) => b.folios_pendientes - a.folios_pendientes)
  else if (orden === 'tiempo') copia.sort((a, b) => (b.minutos_en_estatus ?? 0) - (a.minutos_en_estatus ?? 0))
  else copia.sort((a, b) => (peso[a.estatus] ?? 9) - (peso[b.estatus] ?? 9) || a.nombre.localeCompare(b.nombre))
  return copia
}

function Indicadores({ datos, enJornada, ultimoEvento }: {
  datos: Tablero | null
  enJornada: number
  ultimoEvento: string | null
}) {
  const i = (datos?.indicadores ?? {}) as Record<string, unknown>
  const celdas: [string, string][] = [
    ['Folios del día', String(i.total_dia ?? '—')],
    ['Completados', String(i.completados ?? '—')],
    ['Técnicos en jornada', String(enJornada)],
    ['Técnicos con folio activo', String(i.tecnicos_activos ?? '—')],
    ['Alertas abiertas', String(i.alertas_abiertas ?? '—')],
    ['Atención promedio (h)', String(i.tiempo_promedio_atencion_horas ?? '—')],
  ]
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6" data-testid="indicadores-jornada">
      {celdas.map(([titulo, valor]) => (
        <div key={titulo} className="rounded-xl border border-slate-200 bg-white px-3 py-2">
          <p className="text-xs text-slate-500">{titulo}</p>
          <p className="text-lg font-semibold text-slate-900">{valor}</p>
        </div>
      ))}
      {ultimoEvento && (
        <p className="col-span-full text-right text-xs text-slate-400">
          Último evento recibido: {fmtFecha(ultimoEvento)}
        </p>
      )}
    </div>
  )
}

/**
 * Propuestas de reasignación automática por decidir (§6.8.2). F2-06.
 *
 * Vive en el tablero porque es donde el despachador está mirando cuando algo se mueve, y se acepta o se rechaza
 * con un toque. Mientras nadie decide, **nada cambia**: eso es lo que dice el texto de la tarjeta.
 */
function PanelPropuestas() {
  const [propuestas, setPropuestas] = useState<Propuesta[]>([])
  const [error, setError] = useState<string | null>(null)

  const cargar = useCallback(async () => {
    try { setPropuestas(await propuestasPendientes()) } catch { setPropuestas([]) }
  }, [])
  useEffect(() => { void cargar() }, [cargar])

  if (propuestas.length === 0) return null
  return (
    <Tarjeta titulo={`Reasignaciones propuestas (${propuestas.length})`}>
      <p className="mb-2 text-xs text-slate-600">Nada cambia hasta que aceptas.</p>
      <ul className="space-y-2 text-sm" data-testid="panel-propuestas">
        {error && <li className="text-xs text-red-700">{error}</li>}
        {propuestas.map((p) => (
          <li key={p.id} className="rounded-lg border border-amber-200 bg-amber-50 p-2">
            <p className="font-medium text-slate-800">{NOMBRE_DISPARADOR[p.disparador]}</p>
            <p className="text-xs text-slate-600">{p.motivo}</p>
            <ul className="mt-1 space-y-0.5 text-xs text-slate-700">
              {p.movimientos.slice(0, 4).map((m) => (
                <li key={m.folio_id}>{`${m.numero_folio} → llega ${horaRuta(m.llegada_estimada)}`}</li>
              ))}
              {p.movimientos.length > 4 && <li>{`y ${p.movimientos.length - 4} más`}</li>}
            </ul>
            <div className="mt-2 flex gap-2">
              <Boton onClick={async () => {
                setError(null)
                try { await aceptarPropuesta(p.id); await cargar() } catch (e) { setError(mensajeDeError(e)) }
              }}>Aceptar</Boton>
              <Boton variante="secundario" onClick={async () => {
                setError(null)
                try { await rechazarPropuesta(p.id, 'Rechazada desde el tablero'); await cargar() }
                catch (e) { setError(mensajeDeError(e)) }
              }}>Rechazar</Boton>
            </div>
          </li>
        ))}
      </ul>
    </Tarjeta>
  )
}


/** §6.8.4: el desvío pinta la fila de amarillo; cualquier otra alerta, de rojo. F2-06. */
function esDesvio(t: TecnicoEnTablero): boolean {
  return (t.alerta?.tipo ?? '').toUpperCase().includes('DESVIO')
}


function PanelTecnicos({ tecnicos, orden, alOrdenar, seleccionado, alElegir }: {
  tecnicos: TecnicoEnTablero[]
  orden: 'estatus' | 'folios' | 'tiempo'
  alOrdenar: (o: 'estatus' | 'folios' | 'tiempo') => void
  seleccionado: string | null
  alElegir: (id: string) => void
}) {
  return (
    <Tarjeta titulo={`Técnicos · ${tecnicos.filter((t) => t.en_jornada).length} en jornada`}
      acciones={
        <div className="flex gap-1 text-xs">
          {([['estatus', 'Estatus'], ['folios', 'Folios'], ['tiempo', 'Tiempo']] as const).map(([v, texto]) => (
            <button key={v} aria-pressed={orden === v}
              className={`rounded px-2 py-0.5 ${orden === v ? 'bg-primario text-white' : 'border border-slate-300'}`}
              onClick={() => alOrdenar(v)}>{texto}</button>
          ))}
        </div>
      }>
      <ul className="max-h-80 space-y-1 overflow-y-auto text-sm" data-testid="panel-tecnicos">
        {tecnicos.length === 0 && <li className="text-slate-400">Sin técnicos activos.</li>}
        {tecnicos.map((t) => (
          <li key={t.tecnico_id}
            className={`rounded-lg border p-2 ${esDesvio(t) ? 'border-amber-300 bg-amber-50'
              : t.alerta ? 'border-red-300 bg-red-50' : 'border-slate-200'} ${
              t.tecnico_id === seleccionado ? 'ring-2 ring-primario/30' : ''}`}>
            <button className="w-full text-left" onClick={() => alElegir(t.tecnico_id)}>
              <div className="flex flex-wrap items-center justify-between gap-1">
                <span className="font-medium text-slate-800">{t.nombre}</span>
                <span className={`rounded-full border px-2 py-0.5 text-xs ${COLOR_ESTATUS[t.estatus]}`}>
                  {t.estatus_texto}
                </span>
              </div>
              <p className="text-xs text-slate-500">
                {t.folios_pendientes} folio(s) pendiente(s)
                {t.minutos_en_estatus != null && ` · ${minutosLegibles(t.minutos_en_estatus)} en este estatus`}
                {t.bateria_pct != null && ` · batería ${t.bateria_pct}%`}
              </p>
              {t.estatus === 'sin_senal' && t.ultima_posicion_at && (
                <p className="text-xs text-slate-600">Sin señal desde {fmtFecha(t.ultima_posicion_at)}</p>
              )}
              {t.alerta && (
                <p className="text-xs font-medium text-red-700">
                  {NOMBRE_ALERTA[t.alerta.tipo] ?? t.alerta.tipo}
                  {t.alerta.escalada && ' · escalada al Admin prestador'}
                </p>
              )}
              {t.respuesta_tecnico && (
                <p className="text-xs text-slate-700">
                  Respondió: {t.respuesta_tecnico === 'necesito_apoyo' ? 'Necesito apoyo' : 'Estoy bien'}
                </p>
              )}
            </button>
          </li>
        ))}
      </ul>
    </Tarjeta>
  )
}

function DetalleTecnico({ tecnico, recorrido, folios, soloLectura, alCerrarJornada }: {
  tecnico: TecnicoEnTablero
  recorrido: PuntoRecorrido[]
  folios: FolioEnTablero[]
  soloLectura: boolean
  alCerrarJornada: (jornadaId: string) => Promise<void>
}) {
  return (
    <Tarjeta titulo={`${tecnico.nombre} · ${tecnico.estatus_texto}`}>
      <div className="space-y-2 text-sm" data-testid="detalle-tecnico">
        <p className="text-xs text-slate-500">
          {tecnico.numero_empleado && `Empleado ${tecnico.numero_empleado} · `}
          {tecnico.vehiculo_placas && `placas ${tecnico.vehiculo_placas} · `}
          {tecnico.jornada_desde ? `jornada desde ${fmtFecha(tecnico.jornada_desde)}` : 'sin jornada abierta'}
        </p>
        <p className="text-xs text-slate-500">
          {recorrido.length} punto(s) en las últimas horas
          {tecnico.ultima_posicion_at && ` · última posición ${fmtFecha(tecnico.ultima_posicion_at)}`}
          {tecnico.precision_m && ` · precisión ${tecnico.precision_m} m`}
        </p>
        <div>
          <p className="text-xs font-semibold uppercase text-slate-500">Sus folios</p>
          <ul className="space-y-1">
            {folios.length === 0 && <li className="text-xs text-slate-400">Sin folios activos.</li>}
            {folios.map((f) => (
              <li key={f.folio_id}>
                <Link to={`/folios/${f.folio_id}`} className="text-primario hover:underline">{f.numero_folio}</Link>
                <span className="text-xs text-slate-500"> · {f.sucursal} · {f.estado.replace('_', ' ')}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="flex flex-wrap gap-2">
          {tecnico.telefono && (
            <a href={`tel:${tecnico.telefono}`} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm">
              Llamar
            </a>
          )}
          {folios[0] && (
            <Link to={`/folios/${folios[0].folio_id}`}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm">
              Escribirle por el chat del folio
            </Link>
          )}
          {!soloLectura && tecnico.en_jornada && (
            <Boton variante="secundario"
              onClick={() => void alCerrarJornada(tecnico.tecnico_id)}>Cerrar su jornada</Boton>
          )}
        </div>
      </div>
    </Tarjeta>
  )
}

function PanelFolios({ folios }: { folios: FolioEnTablero[] }) {
  const [orden, setOrden] = useState<'urgencia' | 'hora'>('urgencia')
  const lista = useMemo(() => {
    const copia = [...folios]
    if (orden === 'hora') copia.sort((a, b) => b.capturado_at.localeCompare(a.capturado_at))
    return copia
  }, [folios, orden])
  return (
    <Tarjeta titulo={`Folios activos y del día · ${folios.length}`}
      acciones={
        <div className="flex gap-1 text-xs">
          {([['urgencia', 'Por urgencia'], ['hora', 'Por hora']] as const).map(([v, texto]) => (
            <button key={v} aria-pressed={orden === v}
              className={`rounded px-2 py-0.5 ${orden === v ? 'bg-primario text-white' : 'border border-slate-300'}`}
              onClick={() => setOrden(v)}>{texto}</button>
          ))}
        </div>
      }>
      <div className="max-h-72 overflow-y-auto">
        <table className="w-full text-left text-sm" data-testid="panel-folios">
          <thead className="text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="py-1">Folio</th><th className="py-1">Sucursal</th><th className="py-1">Técnico</th>
              <th className="py-1">Estado</th><th className="py-1">SLA</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {lista.length === 0 && (
              <tr><td colSpan={5} className="py-4 text-center text-slate-400">Sin folios del día.</td></tr>
            )}
            {lista.map((f) => (
              <tr key={f.folio_id} className={f.incumplido ? 'bg-red-50' : f.en_riesgo ? 'bg-amber-50' : ''}>
                <td className="py-1">
                  <Link to={`/folios/${f.folio_id}`} className="text-primario hover:underline">{f.numero_folio}</Link>
                </td>
                <td className="py-1 text-xs">{f.sucursal}</td>
                <td className="py-1 text-xs">{f.tecnico ?? '—'}</td>
                <td className="py-1 text-xs">{f.estado.replace(/_/g, ' ')}</td>
                <td className="py-1 text-xs">
                  {!f.sla_disponible ? <span className="text-slate-400">sin SLA</span>
                    : f.incumplido ? <span className="font-medium text-red-700">incumplido</span>
                      : <span className={f.en_riesgo ? 'font-medium text-amber-700' : ''}>
                          {f.minutos_restantes != null ? `${f.minutos_restantes} min` : '—'}
                          {f.en_riesgo && ' · en riesgo'}
                        </span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Tarjeta>
  )
}

function PanelAlertas({ alertas, tecnicos, alVerTecnico, alAtender }: {
  alertas: AlertaEnTablero[]
  tecnicos: TecnicoEnTablero[]
  alVerTecnico: (id: string) => void
  alAtender: (id: string) => Promise<void>
}) {
  return (
    <Tarjeta titulo={`Alertas · ${alertas.length}`}>
      <ul className="max-h-80 space-y-2 overflow-y-auto text-sm" data-testid="panel-alertas">
        {alertas.length === 0 && <li className="text-slate-400">Sin alertas abiertas.</li>}
        {alertas.map((a, i) => {
          const tecnico = a.entidad_tipo === 'tecnico'
            ? tecnicos.find((t) => t.tecnico_id === a.entidad_id) : undefined
          const folioId = a.entidad_tipo === 'folio' ? a.entidad_id
            : (a.datos.folio_id as string | undefined) ?? null
          return (
            <li key={a.id ?? `${a.clave}-${i}`} className="rounded-lg border border-slate-200 p-2">
              <div className="flex flex-wrap items-center justify-between gap-1">
                <span className="font-medium text-slate-800">
                  {NOMBRE_ALERTA[a.clave] ?? a.nombre ?? a.clave}
                </span>
                <span className="text-xs text-slate-500">{fmtFecha(a.timestamp)}</span>
              </div>
              <p className="text-xs text-slate-600">
                {[tecnico?.nombre ?? (a.datos.tecnico as string | undefined),
                  a.datos.numero_folio as string | undefined,
                  a.datos.sucursal as string | undefined,
                  a.datos.etiqueta as string | undefined,
                  a.escalada ? 'escalada' : undefined].filter(Boolean).join(' · ')}
              </p>
              <div className="mt-1 flex flex-wrap gap-2 text-xs">
                {tecnico && (
                  <button className="rounded border border-slate-300 px-2 py-0.5"
                    onClick={() => alVerTecnico(tecnico.tecnico_id)}>Ver en el mapa</button>
                )}
                {tecnico?.telefono && (
                  <a className="rounded border border-slate-300 px-2 py-0.5" href={`tel:${tecnico.telefono}`}>Llamar</a>
                )}
                {folioId && (
                  <Link className="rounded border border-slate-300 px-2 py-0.5" to={`/folios/${folioId}`}>
                    Abrir el folio
                  </Link>
                )}
                {folioId && (
                  <Link className="rounded border border-slate-300 px-2 py-0.5"
                    to={`/reasignaciones/reporte`}>Reasignar</Link>
                )}
                {a.id && (
                  <button className="rounded border border-slate-300 px-2 py-0.5"
                    onClick={() => void alAtender(a.id!)}>Marcar atendida</button>
                )}
              </div>
            </li>
          )
        })}
      </ul>
    </Tarjeta>
  )
}
