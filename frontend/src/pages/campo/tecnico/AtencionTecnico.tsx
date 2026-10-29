import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router'
import { ChatFolio } from '../../../components/chat/ChatFolio'
import { Renderizador } from '../../../components/formularios/Renderizador'
import { Aviso, Boton, Insignia, Selector } from '../../../components/ui'
import { useAuth } from '../../../contexts/AuthContext'
import { useConexion } from '../../../hooks/useConexion'
import { api, mensajeDeError } from '../../../services/api'
import { agregarRefaccionCampo, folioCampo, transicionCampo, vincularAtencion } from '../../../services/campo'
import { baseLocal } from '../../../services/db'
import { ACCIONES, transiciones } from '../../../services/folios'
import { crearRespuesta, enviarRespuesta, guardarRespuesta, obtenerEvidencias } from '../../../services/formularios/respuestas'
import { validar } from '../../../services/formularios/validacion'
import { esSinConexion, syncEngine } from '../../../services/syncEngine'
import type { Evidencia, Formulario, Respuesta } from '../../../types/formularios'
import type { EstadoFolio, FolioDetalle } from '../../../types/folios'
import { EstadoInsignia, SeveridadInsignia, fecha } from '../../folios/comunes'
import { PlanDelTecnico } from './PlanDelTecnico'

const ORDEN_ACCIONES: EstadoFolio[] = ['en_camino', 'en_ejecucion', 'pendiente_refaccion', 'cerrado']

function posicion(): Promise<{ lat: number; lng: number } | null> {
  return new Promise((resolve) => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) return resolve(null)
    navigator.geolocation.getCurrentPosition((p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude }), () => resolve(null), { timeout: 4000 })
  })
}

/**
 * Atención del folio en la app del técnico: acciones del ciclo de vida (tabla de transiciones de P04), formulario de
 * atención resuelto por P03 (fotos, GPS, firma del operador en este dispositivo), refacciones consumidas y chat de campo.
 * Todo operable sin conexión.
 */
export function AtencionTecnico() {
  const { folioId } = useParams()
  const { usuario } = useAuth()
  const { enLinea } = useConexion()
  const [d, setD] = useState<FolioDetalle | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [destinos, setDestinos] = useState<Set<EstadoFolio>>(new Set())
  const [formulario, setFormulario] = useState<Formulario | null>(null)
  const [respuesta, setRespuesta] = useState<Respuesta | null>(null)
  const [valores, setValores] = useState<Record<string, unknown>>({})
  const [evidencias, setEvidencias] = useState<Record<string, Evidencia[]>>({})
  const [mostrarErrores, setMostrarErrores] = useState(false)
  const [refaccion, setRefaccion] = useState({ descripcion: '', cantidad: '1', origen: 'almacen', costo_unitario: '' })
  const [veCosto, setVeCosto] = useState(false)
  const [notas, setNotas] = useState('')
  const temporizador = useRef<ReturnType<typeof setTimeout> | null>(null)

  const cargar = useCallback(async () => {
    if (!folioId) return
    try {
      const det = await folioCampo(folioId)
      if (!det) { setError('Folio no disponible sin conexión'); return }
      setD(det)
      const tabla = await transiciones().catch(() => [])
      setDestinos(new Set(tabla.filter((t) => t.origen === det.folio.estado && t.roles.includes('tecnico')).map((t) => t.destino)))
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }, [folioId])
  useEffect(() => { void cargar() }, [cargar])
  useEffect(() => {
    api<{ clave: string; habilitado: boolean }[]>('/configuracion/mis-permisos').then((p) => setVeCosto(p.some((x) => x.clave === 'ver_costo_refacciones' && x.habilitado))).catch(() => undefined)
  }, [])

  // Formulario de atención: resuelto por P03 (en línea) o desde la caché del paquete de catálogos.
  useEffect(() => {
    if (!d || !folioId || d.formulario_atencion || !['en_ejecucion', 'pendiente_refaccion'].includes(d.folio.estado)) return
    ;(async () => {
      try {
        let f: Formulario | null = null
        if (syncEngine.enLinea()) {
          try {
            f = await api<Formulario>('/formularios/resolver', { params: { tipo: ({ preventivo: 'preventivo', especial: 'trabajo_especial' } as Record<string, string>)[d.folio.tipo_folio] ?? 'atencion_tecnico', tipo_folio: d.folio.tipo_folio, tenant_id: d.folio.tenant_id, equipo_id: d.folio.equipo_id, plan_id: d.folio.plan_id ?? undefined } })
          } catch (e) {
            if (!esSinConexion(e) && (e as { estado?: number }).estado !== 404) throw e
          }
        }
        if (!f) {
          const mapa = ((await baseLocal.metadatos.get('sync.formulario_por_folio'))?.valor as Record<string, string> | undefined) ?? {}
          const id = mapa[folioId]
          const cache = id ? await baseLocal.formularios_cache.get(id) : (await baseLocal.formularios_cache.where('tipo').equals(({ preventivo: 'preventivo', especial: 'trabajo_especial' } as Record<string, string>)[d.folio.tipo_folio] ?? 'atencion_tecnico').first())
          if (cache) f = cache.datos as unknown as Formulario
        }
        if (!f) return
        setFormulario(f)
        const borrador = (await baseLocal.respuestas_borrador.where('referencia_id').equals(folioId).toArray()).find((b) => b.estado === 'en_progreso')
        const r = borrador
          ? { id: borrador.id, formulario_id: f.id, version_id: '', numero_version: f.numero_version_publicada ?? 0, tenant_id: d.folio.tenant_id, un_id: d.folio.un_id, equipo_id: d.folio.equipo_id, origen: 'folio_atencion', referencia_id: folioId, respuestas_json: borrador.respuestas, estado: 'en_progreso' as const, iniciado_at: borrador.iniciado_at, enviado_at: null, inmutable: false, nombre_formulario: f.nombre, errores: [] }
          : await crearRespuesta(f.id, 'folio_atencion', { tenant_id: d.folio.tenant_id, un_id: d.folio.un_id, equipo_id: d.folio.equipo_id, sistema: { captura_folio: d.folio.capturado_at } }, folioId)
        setRespuesta(r)
        setValores(r.respuestas_json)
        try {
          const ev = await obtenerEvidencias(r.id)
          setEvidencias(ev.reduce<Record<string, Evidencia[]>>((acc, e) => ({ ...acc, [e.campo_clave]: [...(acc[e.campo_clave] ?? []), e] }), {}))
        } catch { /* sin red: las evidencias pendientes viven en la cola */ }
      } catch (e) {
        setError(mensajeDeError(e))
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [d?.folio.estado, d?.formulario_atencion?.respuesta_id, folioId])

  function cambiar(nuevos: Record<string, unknown>) {
    setValores(nuevos)
    if (!respuesta) return
    if (temporizador.current) clearTimeout(temporizador.current)
    temporizador.current = setTimeout(() => { guardarRespuesta(respuesta.id, nuevos).catch((e) => setError(mensajeDeError(e))) }, 600)
  }

  async function accion(destino: EstadoFolio) {
    if (!d) return
    const a = ACCIONES.find((x) => x.destino === destino && (!x.desde || x.desde.includes(d.folio.estado)))
    if (!a) return
    setError(null)
    try {
      const geo = destino === 'en_ejecucion' || destino === 'en_camino' ? await posicion() : null
      const cuerpo: Record<string, unknown> = { notas, geolat: geo?.lat ?? null, geolng: geo?.lng ?? null }
      if (a.campo === 'notas' && !notas.trim()) cuerpo.notas = a.etiqueta
      const r = await transicionCampo(d.folio.id, a.ruta, destino, cuerpo, `${a.etiqueta} — folio ${d.folio.numero_folio}`)
      setNotas('')
      setAviso(r.encolada ? `${a.etiqueta}: guardado sin conexión; se enviará con la hora real` : `${a.etiqueta}: listo`)
      await cargar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  async function enviarAtencion() {
    if (!d || !formulario || !respuesta) return
    setMostrarErrores(true)
    const ctx = { evidencias: Object.fromEntries(Object.entries(evidencias).map(([k, v]) => [k, v.map((e) => ({ tipo: e.tipo }))])), iniciadoAt: new Date(respuesta.iniciado_at) }
    const { errores } = validar(formulario.esquema_json, valores, ctx, true)
    if (errores.length) { setError(`Revisa ${errores.length} campo(s) antes de enviar`); return }
    setError(null)
    try {
      if (temporizador.current) clearTimeout(temporizador.current)
      await guardarRespuesta(respuesta.id, valores)
      const r = await enviarRespuesta(respuesta.id)
      if (syncEngine.enLinea() && !r.id.startsWith(respuesta.id) ? true : syncEngine.enLinea()) {
        try { await vincularAtencion(d.folio.id, r.id) } catch (e) { if (!esSinConexion(e)) throw e }
      }
      setAviso(syncEngine.enLinea() ? 'Formulario de atención enviado y vinculado al folio' : 'Formulario guardado; se enviará y vinculará al recuperar la señal')
      setRespuesta(r)
      await cargar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  async function agregarRefaccion() {
    if (!d || !refaccion.descripcion.trim()) return
    try {
      const r = await agregarRefaccionCampo(d.folio.id, { descripcion: refaccion.descripcion.trim(), cantidad: Number(refaccion.cantidad) || 1, origen: refaccion.origen as 'almacen' | 'oc' | 'caja_chica', costo_unitario: veCosto && refaccion.costo_unitario ? Number(refaccion.costo_unitario) : 0 })
      setRefaccion({ descripcion: '', cantidad: '1', origen: 'almacen', costo_unitario: '' })
      setAviso(r.encolada ? 'Refacción guardada sin conexión' : 'Refacción registrada')
      await cargar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  if (error && !d) return <Aviso>{error}</Aviso>
  if (!d || !usuario) return <p className="text-sm text-slate-500">Cargando…</p>
  const f = d.folio
  const acciones = ORDEN_ACCIONES.filter((x) => destinos.has(x))
  const etiqueta: Record<string, string> = { en_camino: 'Voy en camino', en_ejecucion: f.estado === 'pendiente_refaccion' ? 'Reanudar ejecución' : 'Confirmar llegada', pendiente_refaccion: 'Pendiente de refacción', cerrado: 'Cerrar folio' }
  const firmado = d.evidencias.some((e) => e.tipo === 'firma') || Object.values(evidencias).some((l) => l.some((e) => e.tipo === 'firma'))
  return (
    <div className="mx-auto max-w-lg space-y-4">
      <Link to="/campo" className="text-xs text-primario underline">← Mis folios</Link>
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="flex items-center justify-between gap-2">
          <span className="font-mono text-lg font-semibold">{f.numero_folio}</span>
          <span className="flex gap-1">{f.tipo_folio === 'preventivo' && <Insignia tono="acento">Preventivo</Insignia>}{f.tipo_folio === 'especial' && <Insignia tono="acento">Trabajo especial</Insignia>}{d.trabajo_especial?.urgencia && <Insignia tono="alerta">Urgencia</Insignia>}<EstadoInsignia estado={f.estado} /></span>
        </div>
        {f.tipo_folio === 'preventivo' && f.plan_nombre && <p className="mt-1 text-xs text-slate-600">Plan: {f.plan_nombre}</p>}
        {d.trabajo_especial && <p className="mt-1 text-xs text-slate-600">Trabajo especial {d.trabajo_especial.numero}: formulario propio del TE y puntos de verificación al cierre; la firma del cliente y la evidencia fotográfica de cierre son obligatorias.</p>}
        <p className="mt-2 text-base text-slate-800">{f.descripcion}</p>
        <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-600">
          <SeveridadInsignia severidad={f.severidad} />
          <span>{d.captura.un.codigo} · {d.captura.un.nombre}</span>
          <span>{d.captura.equipo.codigo} · {d.captura.equipo.nombre}</span>
        </div>
        <p className="mt-1 text-xs text-slate-500">{d.captura.un.direccion}</p>
        {f.fecha_inicio_atencion && <p className="mt-1 text-xs text-slate-500">Llegada: {fecha(f.fecha_inicio_atencion)}</p>}
        {!enLinea && <p className="mt-2 text-xs text-amber-800">Sin conexión: tus acciones se guardan con la hora real y se envían después.</p>}
      </div>
      {error && <Aviso>{error}</Aviso>}
      {aviso && <Aviso tipo="exito">{aviso}</Aviso>}

      {acciones.length > 0 && (
        <div className="rounded-xl border border-slate-200 bg-white p-4" data-testid="acciones-tecnico">
          <h2 className="text-sm font-semibold text-slate-800">Acciones</h2>
          {(destinos.has('pendiente_refaccion') || destinos.has('cerrado')) && (
            <input aria-label="Notas" value={notas} onChange={(e) => setNotas(e.target.value)} placeholder="Notas (opcional)" className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-base" />
          )}
          <div className="mt-2 grid gap-2">
            {acciones.map((x) => (
              <Boton key={x} className="min-h-12 text-base" variante={x === 'cerrado' ? 'primario' : 'secundario'} disabled={x === 'cerrado' && (!d.formulario_atencion && !(respuesta?.estado === 'enviado'))} onClick={() => void accion(x)}>
                {etiqueta[x]}
              </Boton>
            ))}
          </div>
          {destinos.has('cerrado') && (
            <p className="mt-2 text-xs text-slate-500">Para cerrar: formulario de atención enviado {d.formulario_atencion || respuesta?.estado === 'enviado' ? '✓' : '✗'} · firma del operador {firmado ? '✓' : '✗ (en el formulario o desde su app)'}</p>
          )}
        </div>
      )}

      {f.tipo_folio === 'preventivo' && <PlanDelTecnico folioId={f.id} alUsarMaterial={(m) => setRefaccion({ ...refaccion, descripcion: m.descripcion, cantidad: String(Number(m.cantidad_estandar) || 1) })} />}

      {formulario && respuesta && (
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-800">{formulario.nombre}</h2>
            <Insignia tono={respuesta.estado === 'enviado' ? 'ok' : 'alerta'}>{respuesta.estado === 'enviado' ? 'Enviado' : 'En progreso'}</Insignia>
          </div>
          <p className="mb-3 text-xs text-slate-500">Fotos antes/durante/después con control de calidad y GPS; al final entrega el dispositivo al operador para que firme.</p>
          <Renderizador esquema={formulario.esquema_json} respuestas={valores} onChange={cambiar} respuestaId={respuesta.id}
                        contexto={{ tenant_id: f.tenant_id, un_id: f.un_id, equipo_id: f.equipo_id, sistema: { captura_folio: f.capturado_at, asignacion: d.asignacion.asignado_at ?? '' } }}
                        evidencias={evidencias} onEvidencias={(k, l) => setEvidencias((e) => ({ ...e, [k]: l }))} soloLectura={respuesta.estado === 'enviado'}
                        mostrarErrores={mostrarErrores} iniciadoAt={new Date(respuesta.iniciado_at)} />
          {respuesta.estado !== 'enviado' && <Boton className="mt-3 min-h-12 w-full text-base" onClick={() => void enviarAtencion()}>Enviar formulario de atención</Boton>}
        </div>
      )}
      {d.formulario_atencion && <Aviso tipo="exito">Formulario de atención vinculado ({d.formulario_atencion.formulario_nombre}).</Aviso>}

      {['en_ejecucion', 'pendiente_refaccion'].includes(f.estado) && (
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <h2 className="text-sm font-semibold text-slate-800">Refacciones consumidas ({d.refacciones.length})</h2>
          <ul className="mt-1 text-sm text-slate-700">{d.refacciones.map((r) => <li key={r.id}>{r.cantidad} × {r.descripcion} · {r.origen}{veCosto && <> · ${r.costo_unitario}</>}</li>)}</ul>
          <form className="mt-2 grid gap-2" onSubmit={(e) => { e.preventDefault(); void agregarRefaccion() }}>
            <input aria-label="Refacción" placeholder="Descripción de la refacción" value={refaccion.descripcion} onChange={(e) => setRefaccion({ ...refaccion, descripcion: e.target.value })} className="rounded-lg border border-slate-300 px-3 py-2 text-base" />
            <div className="grid grid-cols-3 gap-2">
              <input aria-label="Cantidad" type="number" min={1} step="1" value={refaccion.cantidad} onChange={(e) => setRefaccion({ ...refaccion, cantidad: e.target.value })} className="rounded-lg border border-slate-300 px-3 py-2 text-base" />
              <Selector etiqueta="Origen" value={refaccion.origen} onChange={(e) => setRefaccion({ ...refaccion, origen: e.target.value })} opciones={[{ valor: 'almacen', texto: 'Almacén' }, { valor: 'oc', texto: 'Orden de compra' }, { valor: 'caja_chica', texto: 'Caja chica' }]} />
              {veCosto && <input aria-label="Costo unitario" type="number" min={0} step="0.01" placeholder="Costo" value={refaccion.costo_unitario} onChange={(e) => setRefaccion({ ...refaccion, costo_unitario: e.target.value })} className="rounded-lg border border-slate-300 px-3 py-2 text-base" />}
            </div>
            <Boton type="submit" variante="secundario" disabled={!refaccion.descripcion.trim()}>Agregar refacción</Boton>
          </form>
        </div>
      )}

      <div>
        <h2 className="mb-2 text-sm font-semibold text-slate-800">Chat con el operador</h2>
        <ChatFolio folioId={f.id} canales={['campo']} compacto />
      </div>
    </div>
  )
}
