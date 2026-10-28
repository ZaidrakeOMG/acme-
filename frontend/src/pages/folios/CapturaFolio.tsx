import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { SelectorBusqueda } from '../../components/Buscador'
import { Renderizador } from '../../components/formularios/Renderizador'
import { Aviso, Boton, Insignia, Selector, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { api, ErrorAPI, mensajeDeError } from '../../services/api'
import { capturarFolioCampo, catalogoCampo } from '../../services/campo'
import { baseLocal } from '../../services/db'
import { esSinConexion, syncEngine } from '../../services/syncEngine'
import { capturarFolio, verificarDuplicado } from '../../services/folios'
import { crearRespuesta, enviarRespuesta, guardarRespuesta } from '../../services/formularios/respuestas'
import { validar } from '../../services/formularios/validacion'
import type { Equipo, TipoFalla, UnidadNegocio } from '../../types/api'
import type { Evidencia, Formulario, Respuesta } from '../../types/formularios'
import type { TarjetaDuplicado, TipoFolio } from '../../types/folios'
import { NOMBRE_ESTADO } from '../../types/folios'

type Geo = { lat: number; lng: number } | null

function posicion(): Promise<Geo> {
  return new Promise((resolve) => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) return resolve(null)
    navigator.geolocation.getCurrentPosition((p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude }), () => resolve(null), { timeout: 4000 })
  })
}

/**
 * Captura de folio desde escritorio/PWA (§6.8.6): UN → equipos con contrato activo → tipo de falla por familia → descripción →
 * formulario dinámico (P03) → verificación de duplicado con confirmación fuerte → confirmación obligatoria de UN.
 * P05 reutiliza esta pantalla en la app del operador con la cola offline.
 */
export function CapturaFolio({ modoCampo = false }: { modoCampo?: boolean } = {}) {
  const { usuario } = useAuth()
  const navegar = useNavigate()
  const [unidades, setUnidades] = useState<UnidadNegocio[]>([])
  const [un, setUn] = useState<UnidadNegocio | null>(null)
  const [equipos, setEquipos] = useState<Equipo[] | null>(null)
  const [equipoId, setEquipoId] = useState('')
  const [fallas, setFallas] = useState<TipoFalla[]>([])
  const [tipoFallaId, setTipoFallaId] = useState('')
  const [tipoFolio, setTipoFolio] = useState<TipoFolio>('correctivo')
  const [descripcion, setDescripcion] = useState('')
  const [formulario, setFormulario] = useState<Formulario | null>(null)
  const [respuesta, setRespuesta] = useState<Respuesta | null>(null)
  const [valores, setValores] = useState<Record<string, unknown>>({})
  const [evidencias, setEvidencias] = useState<Record<string, Evidencia[]>>({})
  const [mostrarErrores, setMostrarErrores] = useState(false)
  const [duplicado, setDuplicado] = useState<TarjetaDuplicado | null>(null)
  const [continuarDistinta, setContinuarDistinta] = useState(false)
  const [justificacion, setJustificacion] = useState('')
  const [paso, setPaso] = useState<'captura' | 'confirmacion'>('captura')
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)
  const geo = useRef<Geo>(null)
  const temporizador = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    catalogoCampo<UnidadNegocio>('unidades', () => api<UnidadNegocio[]>('/unidades-negocio')).then(setUnidades).catch((e) => setError(mensajeDeError(e)))
    void posicion().then((g) => { geo.current = g })
  }, [])

  // Equipos con contrato activo de la UN elegida (mecanismo preventivo 1 de §6.8.6).
  useEffect(() => {
    setEquipoId(''); setTipoFallaId(''); setDuplicado(null); setFormulario(null); setRespuesta(null)
    if (!un) { setEquipos(null); return }
    catalogoCampo<Equipo>('equipos', () => api<Equipo[]>('/catalogos/equipos', { params: { un_id: un.id, con_contrato: true } }))
      .then((lista) => setEquipos(lista.filter((e) => e.un_id === un.id && e.con_contrato_activo !== false))).catch((e) => setError(mensajeDeError(e)))
  }, [un])

  const equipo = useMemo(() => equipos?.find((e) => e.id === equipoId) ?? null, [equipos, equipoId])

  // Tipos de falla de la familia del equipo + duplicado abierto + formulario de captura resuelto (P03).
  useEffect(() => {
    setTipoFallaId(''); setDuplicado(null); setContinuarDistinta(false); setJustificacion(''); setFormulario(null); setRespuesta(null)
    if (!equipo || !un) return
    catalogoCampo<TipoFalla>('tipos_falla', () => api<TipoFalla[]>('/catalogos/tipos-falla', { params: { familia_id: equipo.familia_id ?? undefined } }))
      .then((lista) => setFallas(lista.filter((t) => !equipo.familia_id || t.familia_equipo_id === equipo.familia_id))).catch(() => setFallas([]))
    verificarDuplicado(equipo.id).then(setDuplicado).catch(() => setDuplicado(null))
    const resolverFormulario = async (): Promise<Formulario> => {
      if (syncEngine.enLinea()) {
        try {
          return await api<Formulario>('/formularios/resolver', { params: { tipo: 'captura_operador', tipo_folio: tipoFolio, tenant_id: un.tenant_id, tipo_equipo_id: equipo.tipo_equipo_id, familia_equipo_id: equipo.familia_id ?? undefined } })
        } catch (e) {
          if (!esSinConexion(e)) throw e
        }
      }
      const cache = await baseLocal.formularios_cache.where('tipo').equals('captura_operador').first()
      if (!cache) throw new ErrorAPI(404, { codigo: 'NO_ENCONTRADO', mensaje: 'Sin formulario de captura en caché' })
      return cache.datos as unknown as Formulario
    }
    resolverFormulario()
      .then(async (f) => {
        setFormulario(f)
        const r = await crearRespuesta(f.id, 'folio_captura', { tenant_id: un.tenant_id, un_id: un.id, equipo_id: equipo.id })
        setRespuesta(r)
        setValores(r.respuestas_json)
        setEvidencias({})
      })
      .catch((e) => { if (!(e instanceof ErrorAPI && e.estado === 404)) setError(mensajeDeError(e)) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [equipo?.id, tipoFolio])

  function cambiarValores(nuevos: Record<string, unknown>) {
    setValores(nuevos)
    if (!respuesta) return
    if (temporizador.current) clearTimeout(temporizador.current)
    temporizador.current = setTimeout(() => { guardarRespuesta(respuesta.id, nuevos).catch(() => undefined) }, 600)
  }

  const listoParaConfirmar = !!un && !!equipo && !!tipoFallaId && descripcion.trim().length >= 5 && (!duplicado?.existe || (continuarDistinta && justificacion.trim().length > 0)) && !duplicado?.bloqueo_total

  async function irAConfirmacion() {
    setError(null)
    setMostrarErrores(true)
    if (formulario && respuesta) {
      const ev = Object.fromEntries(Object.entries(evidencias).map(([k, v]) => [k, v.map((e) => ({ tipo: e.tipo }))]))
      const { errores } = validar(formulario.esquema_json, valores, { evidencias: ev, iniciadoAt: new Date(respuesta.iniciado_at) }, true)
      if (errores.length) { setError(`Revisa ${errores.length} campo(s) del formulario antes de continuar`); return }
    }
    setPaso('confirmacion')
  }

  async function enviar() {
    if (!un || !equipo) return
    setEnviando(true)
    setError(null)
    try {
      let respuestaId: string | null = null
      if (formulario && respuesta) {
        if (temporizador.current) clearTimeout(temporizador.current)
        await guardarRespuesta(respuesta.id, valores)
        const r = await enviarRespuesta(respuesta.id)
        respuestaId = r.id
      }
      const ahora = new Date().toISOString()
      const g = geo.current ?? (await posicion())
      const capturar = modoCampo ? capturarFolioCampo : capturarFolio
      const folio = await capturar({
        un_id: un.id, equipo_id: equipo.id, tipo_falla_id: tipoFallaId, descripcion: descripcion.trim(), tipo_folio: tipoFolio,
        confirmacion_un: true, confirmacion_un_timestamp: ahora, confirmacion_un_geolat: g?.lat ?? null, confirmacion_un_geolng: g?.lng ?? null,
        geolat_captura: g?.lat ?? null, geolng_captura: g?.lng ?? null, respuesta_id: respuestaId,
        folio_duplicado_justificacion: duplicado?.existe ? justificacion.trim() : null,
      })
      navegar(modoCampo ? `/campo/folio/${folio.id}` : `/folios/${folio.id}`)
    } catch (e) {
      setError(mensajeDeError(e))
      setPaso('captura')
    } finally {
      setEnviando(false)
    }
  }

  if (!usuario) return null

  if (paso === 'confirmacion' && un) {
    return (
      <div className="mx-auto max-w-lg">
        <Tarjeta titulo="Confirma la unidad de negocio">
          <p className="text-sm text-slate-600">Último paso antes de enviar. Verifica que el folio corresponde a esta unidad:</p>
          <div className="my-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
            <p className="text-lg font-semibold text-slate-900">{un.nombre}</p>
            <p className="text-sm text-slate-600">{un.codigo}</p>
            <p className="mt-1 text-sm text-slate-700">{un.direccion || 'Sin dirección registrada'}</p>
            <p className="mt-2 text-xs text-slate-500">Equipo {equipo?.codigo} · {equipo?.nombre}</p>
          </div>
          {error && <div className="mb-3"><Aviso>{error}</Aviso></div>}
          <div className="flex flex-col gap-2 sm:flex-row">
            <Boton onClick={() => void enviar()} disabled={enviando} className="flex-1">Sí, es esta unidad</Boton>
            <Boton variante="secundario" onClick={() => { setPaso('captura'); setUn(null) }} disabled={enviando} className="flex-1">No, quiero cambiarla</Boton>
          </div>
          <p className="mt-3 text-xs text-slate-500">La confirmación queda registrada con fecha, hora y geolocalización como evidencia de presencia en sitio.</p>
        </Tarjeta>
      </div>
    )
  }

  const buscarUn = async (q: string) => unidades.filter((u) => `${u.codigo} ${u.nombre} ${u.direccion}`.toLowerCase().includes(q.toLowerCase()))
  const guia = modoCampo ? {
    un: '¿Dónde está el equipo? Escribe el código o el nombre de tu sucursal.',
    equipo: 'Solo aparecen equipos con contrato activo. Si no ves el tuyo, avisa a tu administrador.',
    falla: '¿Qué le pasa al equipo? Elige el síntoma y describe desde cuándo ocurre; la severidad la calcula ACMA.',
  } : null

  return (
    <div className={`mx-auto space-y-5 ${modoCampo ? 'max-w-lg text-base [&_button]:min-h-11 [&_select]:min-h-11 [&_input]:min-h-11' : 'max-w-3xl'}`}>
      {modoCampo && !syncEngine.enLinea() && <Aviso tipo="info">Sin conexión: capturas con los catálogos guardados y el folio se enviará al recuperar la señal.</Aviso>}
      <div className="flex items-center justify-between">
        <div>
          <Link to={modoCampo ? '/campo' : '/folios'} className="text-xs text-primario underline">← {modoCampo ? 'Mis folios' : 'Folios'}</Link>
          <h1 className="text-2xl font-semibold text-slate-900">Nuevo folio</h1>
        </div>
        <Selector etiqueta="Tipo" value={tipoFolio} onChange={(e) => setTipoFolio(e.target.value as TipoFolio)}
                  opciones={[{ valor: 'correctivo', texto: 'Correctivo' }, { valor: 'preventivo', texto: 'Preventivo' }, { valor: 'especial', texto: 'Especial' }]} />
      </div>
      {error && <Aviso>{error}</Aviso>}

      <Tarjeta titulo="1. Unidad de negocio">
        {guia && <p className="mb-2 text-sm text-slate-600">{guia.un}</p>}
        <SelectorBusqueda etiqueta="Unidad de negocio" minimo={2} valor={un} buscar={buscarUn} alSeleccionar={setUn}
                          mostrar={(u) => <span>{u.codigo} · {u.nombre} <span className="text-xs text-slate-500">{u.direccion}</span></span>} placeholder="Escribe 2 letras del código o nombre…" />
      </Tarjeta>

      {un && (
        <Tarjeta titulo="2. Equipo con contrato activo">
          {guia && <p className="mb-2 text-sm text-slate-600">{guia.equipo}</p>}
          {equipos === null ? <p className="text-sm text-slate-500">Cargando equipos…</p> : equipos.length === 0 ? (
            <Aviso>Ningún equipo de esta unidad tiene contrato activo. No es posible capturar un folio; contacta a tu administrador.</Aviso>
          ) : (
            <Selector etiqueta="Equipo" value={equipoId} onChange={(e) => setEquipoId(e.target.value)}
                      opciones={[{ valor: '', texto: 'Elegir equipo…' }, ...equipos.map((e) => ({ valor: e.id, texto: `${e.codigo} · ${e.nombre}` }))]} />
          )}
          {duplicado?.existe && (
            <div data-testid="tarjeta-duplicado" className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm">
              <p className="font-medium text-amber-900">Ya existe un folio abierto para este equipo: {duplicado.numero_folio}</p>
              <p className="text-amber-900">Estado: {duplicado.estado ? NOMBRE_ESTADO[duplicado.estado] : ''}{duplicado.tecnico_nombre && <> · Técnico: {duplicado.tecnico_nombre}</>}{duplicado.eta && <> · Llegada estimada: {new Date(duplicado.eta).toLocaleString('es-MX')}</>}</p>
              <p className="mt-1 text-slate-700">{duplicado.descripcion}</p>
              {duplicado.bloqueo_total ? (
                <p className="mt-2 font-medium text-red-800">Tu empresa bloquea los folios duplicados: espera a que el folio existente se cierre o cancele.</p>
              ) : (
                <div className="mt-2 flex flex-wrap gap-2">
                  <Link to={`/folios/${duplicado.folio_id}`}><Boton variante="secundario">Ver folio existente</Boton></Link>
                  {!continuarDistinta && <Boton variante="fantasma" onClick={() => setContinuarDistinta(true)}>Es una falla diferente — continuar</Boton>}
                </div>
              )}
              {continuarDistinta && !duplicado.bloqueo_total && (
                <label className="mt-2 block text-sm">
                  <span className="font-medium">¿En qué es diferente esta falla? (obligatorio)</span>
                  <textarea aria-label="Justificación del duplicado" value={justificacion} onChange={(e) => setJustificacion(e.target.value)} rows={2}
                            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
                </label>
              )}
            </div>
          )}
        </Tarjeta>
      )}

      {equipo && (
        <Tarjeta titulo="3. Falla">
          {guia && <p className="mb-2 text-sm text-slate-600">{guia.falla}</p>}
          <Selector etiqueta="Tipo de falla" value={tipoFallaId} onChange={(e) => setTipoFallaId(e.target.value)}
                    opciones={[{ valor: '', texto: 'Elegir tipo de falla…' }, ...fallas.map((f) => ({ valor: f.id, texto: f.descripcion }))]} />
          <p className="mb-3 text-xs text-slate-500">La severidad la determina el sistema con la matriz tipo de falla × tipo de equipo.</p>
          <label className="block text-sm">
            <span className="font-medium text-slate-700">Descripción</span>
            <textarea aria-label="Descripción" value={descripcion} onChange={(e) => setDescripcion(e.target.value)} rows={4}
                      className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" placeholder="Qué pasa, desde cuándo, qué se intentó…" />
          </label>
        </Tarjeta>
      )}

      {equipo && formulario && respuesta && (
        <Tarjeta titulo={`4. ${formulario.nombre}`} acciones={<Insignia tono="acento">v{respuesta.numero_version}</Insignia>}>
          <Renderizador esquema={formulario.esquema_json} respuestas={valores} onChange={cambiarValores} respuestaId={respuesta.id}
                        contexto={{ tenant_id: un?.tenant_id, un_id: un?.id, equipo_id: equipo.id }} evidencias={evidencias}
                        onEvidencias={(k, l) => setEvidencias((e) => ({ ...e, [k]: l }))} mostrarErrores={mostrarErrores} iniciadoAt={new Date(respuesta.iniciado_at)} />
        </Tarjeta>
      )}

      {equipo && (
        <div className="flex justify-end">
          <Boton onClick={() => void irAConfirmacion()} disabled={!listoParaConfirmar}>Continuar</Boton>
        </div>
      )}
    </div>
  )
}
