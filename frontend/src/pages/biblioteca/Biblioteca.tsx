import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { Aviso, Boton, Campo, Encabezado, Insignia, Modal, Selector, Tabla, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { useRecurso } from '../../hooks/useRecurso'
import { mensajeDeError } from '../../services/api'
import {
  desactivarManual, enlaceManual, guardarContenido, listarContenido, listarManuales, subirManual, subirVersion,
  versionesDeManual,
} from '../../services/capacitacion'
import { SinEspacio, guardarManual } from '../../services/bibliotecaOffline'
import { baseLocal, type BibliotecaOffline } from '../../services/db'
import type { Contrato, TipoEquipo } from '../../types/api'
import type { CategoriaManual, ContenidoServicio, Manual, PuntoRevision, VersionManual } from '../../types/capacitacion'
import {
  NOMBRE_CATEGORIA, ROLES_GESTIONAN_CONTENIDO, ROLES_GESTIONAN_MANUALES,
} from '../../types/capacitacion'
import { fecha as fmtFecha, tamanoArchivo as tamano } from '../folios/comunes'

type Vista = 'manuales' | 'contenido'

/**
 * Biblioteca técnica (§6.10.4): manuales y fichas por tipo de equipo con historial de versiones, y el contenido de
 * servicio contractual del cliente con sus puntos de revisión ordenados, que es lo que el técnico ve en el folio.
 */
export function Biblioteca() {
  const { usuario } = useAuth()
  const [params, setParams] = useSearchParams()
  const vista = (params.get('vista') as Vista) || 'manuales'
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)

  if (!usuario) return null
  const gestionaManuales = ROLES_GESTIONAN_MANUALES.includes(usuario.rol)
  const gestionaContenido = ROLES_GESTIONAN_CONTENIDO.includes(usuario.rol)
  const esCliente = ['admin_empresa', 'admin_un', 'supervisor_operadores'].includes(usuario.rol)

  function ir(v: Vista) {
    const p = new URLSearchParams(params)
    p.set('vista', v)
    setParams(p)
  }

  return (
    <div>
      <Encabezado titulo="Biblioteca técnica"
        descripcion="Manuales, fichas y diagramas por tipo de equipo, con historial de versiones, y el contenido de servicio del contrato: lo que hay que revisar en cada visita. El técnico lo consulta desde el folio, incluso sin señal." />
      <div className="mb-3 flex flex-wrap gap-1" role="tablist" aria-label="Vistas de la biblioteca">
        {([['manuales', 'Manuales y fichas'], ['contenido', 'Contenido de servicio']] as [Vista, string][]).map(([v, texto]) => (
          <button key={v} role="tab" aria-selected={vista === v}
            className={`rounded-lg px-3 py-1.5 text-sm ${vista === v ? 'bg-primario text-white' : 'border border-slate-300'}`}
            onClick={() => ir(v)}>{texto}</button>
        ))}
      </div>
      {usuario.rol === 'tecnico' && (
        <p className="mb-3 text-sm">
          <Link className="text-primario underline" to="/campo/manuales">Mis manuales sin conexión</Link>
          <span className="text-slate-500"> · guarda en el teléfono lo que vas a necesitar en sitio.</span>
        </p>
      )}
      {error && <div className="mb-3"><Aviso>{error}</Aviso></div>}
      {aviso && <div className="mb-3"><Aviso tipo="exito">{aviso}</Aviso></div>}

      {vista === 'manuales' && (
        <Manuales gestiona={gestionaManuales} guardaSinConexion={usuario.rol === 'tecnico'}
          alError={setError} alAviso={setAviso} />
      )}
      {vista === 'contenido' && (
        <Contenido gestiona={gestionaContenido} esCliente={esCliente} alError={setError} alAviso={setAviso} />
      )}
    </div>
  )
}

// ------------------------------------------------------------------ manuales
export function Manuales({ gestiona, alError, alAviso, soloMisFolios = false, guardaSinConexion = false }: {
  gestiona: boolean; alError: (m: string | null) => void; alAviso: (m: string | null) => void
  soloMisFolios?: boolean
  /** El técnico puede llevarse a su teléfono cualquier manual que consulte, no solo los de sus folios del día. */
  guardaSinConexion?: boolean
}) {
  const tipos = useRecurso<TipoEquipo[]>('/catalogos/tipos-equipo')
  const [tipoId, setTipoId] = useState('')
  const [busqueda, setBusqueda] = useState('')
  const [manuales, setManuales] = useState<Manual[]>([])
  const [viendo, setViendo] = useState<{ manual: Manual; url: string; enlace: string } | null>(null)
  const [historial, setHistorial] = useState<{ manual: Manual; versiones: VersionManual[] } | null>(null)
  const [subiendo, setSubiendo] = useState(false)
  const [nuevaVersionDe, setNuevaVersionDe] = useState<Manual | null>(null)
  const [guardados, setGuardados] = useState<BibliotecaOffline[]>([])

  useEffect(() => {
    if (guardaSinConexion) void baseLocal.biblioteca_offline.toArray().then(setGuardados)
  }, [guardaSinConexion])

  const cargar = useCallback(async () => {
    try {
      setManuales(await listarManuales({
        tipo_equipo_id: tipoId || undefined, q: busqueda || undefined,
        solo_mis_folios: soloMisFolios || undefined,
      }))
    } catch (e) { alError(mensajeDeError(e)) }
  }, [tipoId, busqueda, soloMisFolios, alError])
  useEffect(() => { void cargar() }, [cargar])

  /**
   * El visor recibe el archivo como `blob:` y no el enlace firmado: la API manda `frame-ancestors 'none'` (P11a), así
   * que un iframe apuntado a `/api/biblioteca/archivo` lo bloquea el navegador. El enlace firmado se conserva para
   * abrirlo en otra pestaña, donde no hay marco que valga.
   */
  async function ver(m: Manual) {
    alError(null)
    try {
      const enlace = await enlaceManual(m.id)
      const respuesta = await fetch(enlace.url)
      if (!respuesta.ok) throw new Error('No se pudo abrir el manual')
      const blob = await respuesta.blob()
      setViendo((previo) => {
        if (previo) URL.revokeObjectURL(previo.url)
        return { manual: m, url: URL.createObjectURL(blob), enlace: enlace.url }
      })
    } catch (e) { alError(mensajeDeError(e)) }
  }

  function cerrarVisor() {
    setViendo((previo) => {
      if (previo) URL.revokeObjectURL(previo.url)
      return null
    })
  }

  async function verHistorial(m: Manual) {
    try { setHistorial({ manual: m, versiones: await versionesDeManual(m.id) }) } catch (e) { alError(mensajeDeError(e)) }
  }

  async function guardarSinConexion(m: Manual) {
    alError(null)
    try {
      await guardarManual({
        clase: 'manual', id: m.id, tipo_equipo_id: m.tipo_equipo_id, titulo: m.titulo, categoria: m.categoria,
        version: m.version, mime: m.mime, bytes: m.bytes, activo: true, de_mis_folios: false,
      })
      setGuardados(await baseLocal.biblioteca_offline.toArray())
      alAviso(`«${m.titulo}» quedó disponible sin señal`)
    } catch (e) {
      alError(e instanceof SinEspacio
        ? `No cabe: libera ${tamano(e.faltanBytes)} en «Mis manuales sin conexión» o sube el límite`
        : mensajeDeError(e))
    }
  }

  async function desactivar(m: Manual) {
    alError(null)
    try { await desactivarManual(m.id); alAviso(`«${m.titulo}» ya no se publica`); await cargar() }
    catch (e) { alError(mensajeDeError(e)) }
  }

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-56">
          <Selector etiqueta="Tipo de equipo" value={tipoId} onChange={(e) => setTipoId(e.target.value)}
            opciones={[{ valor: '', texto: 'Todos' }, ...(tipos.datos ?? []).map((t) => ({ valor: t.id, texto: t.nombre }))]} />
        </div>
        <div className="min-w-56">
          <Campo etiqueta="Buscar por título" value={busqueda} onChange={(e) => setBusqueda(e.target.value)} />
        </div>
        {gestiona && <Boton onClick={() => setSubiendo(true)}>Subir manual</Boton>}
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-2">
        <Tabla filas={manuales} vacio="Sin manuales para este filtro" columnas={[
          { titulo: 'Título', celda: (m) => <button className="text-left text-sm font-medium text-primario underline" onClick={() => void ver(m)}>{m.titulo}</button> },
          { titulo: 'Tipo de equipo', celda: (m) => m.tipo_equipo },
          { titulo: 'Categoría', celda: (m) => NOMBRE_CATEGORIA[m.categoria] ?? m.categoria },
          { titulo: 'Versión', celda: (m) => <Insignia tono={m.version > 1 ? 'acento' : 'neutro'}>v{m.version}</Insignia> },
          { titulo: 'Tamaño', celda: (m) => tamano(m.bytes) },
          { titulo: 'Subido', celda: (m) => fmtFecha(m.fecha_subida) },
          {
            titulo: 'Acciones',
            celda: (m) => (
              <div className="flex flex-wrap gap-2 text-sm">
                <button className="text-primario underline" onClick={() => void ver(m)}>Ver</button>
                {guardaSinConexion && (guardados.some((g) => g.clave === `manual:${m.id}`)
                  ? <span className="text-xs text-slate-500">En el teléfono</span>
                  : <button className="text-primario underline" onClick={() => void guardarSinConexion(m)}>Guardar</button>)}
                {gestiona && <button className="text-primario underline" onClick={() => void verHistorial(m)}>Versiones</button>}
                {gestiona && <button className="text-primario underline" onClick={() => setNuevaVersionDe(m)}>Nueva versión</button>}
                {gestiona && <button className="text-red-700 underline" onClick={() => void desactivar(m)}>Retirar</button>}
              </div>
            ),
          },
        ]} />
      </div>

      {viendo && (
        <Modal titulo={`${viendo.manual.titulo} (v${viendo.manual.version})`} abierto alCerrar={cerrarVisor}>
          <div className="grid gap-2">
            {viendo.manual.mime.startsWith('image/') ? (
              <img src={viendo.url} alt={viendo.manual.titulo} className="max-h-[70vh] w-full object-contain" />
            ) : viendo.manual.mime.startsWith('video/') ? (
              <video src={viendo.url} controls className="max-h-[70vh] w-full" />
            ) : (
              // El enlace firmado dura unos minutos y no lleva cabecera de autorización: el visor del navegador basta.
              <iframe src={viendo.url} title={viendo.manual.titulo} className="h-[70vh] w-full rounded border border-slate-200" />
            )}
            <p className="text-xs text-slate-500">
              {viendo.manual.nombre_original} · {tamano(viendo.manual.bytes)} · el enlace caduca en unos minutos.
            </p>
            <div className="flex justify-end">
              <a className="text-sm text-primario underline" href={viendo.enlace} target="_blank" rel="noreferrer">Abrir en una pestaña</a>
            </div>
          </div>
        </Modal>
      )}

      {historial && (
        <Modal titulo={`Versiones de ${historial.manual.titulo}`} abierto alCerrar={() => setHistorial(null)}>
          <p className="mb-2 text-sm text-slate-600">
            Al subir una versión nueva la anterior no se borra: queda aquí con la fecha, quién la reemplazó y sus notas.
          </p>
          <ul className="divide-y divide-slate-100">
            <li className="py-2 text-sm"><strong>v{historial.manual.version}</strong> — vigente desde {fmtFecha(historial.manual.fecha_subida)}</li>
            {historial.versiones.map((v) => (
              <li key={v.id} className="py-2 text-sm">
                <strong>v{v.version_anterior}</strong> — reemplazada el {fmtFecha(v.reemplazado_en)}
                <span className="block text-xs text-slate-500">
                  {v.nombre_original_anterior ?? 'sin nombre'} · {tamano(v.bytes_anterior)}
                  {v.notas_version ? ` · ${v.notas_version}` : ''}
                </span>
              </li>
            ))}
            {historial.versiones.length === 0 && <li className="py-2 text-sm text-slate-500">Es la primera versión.</li>}
          </ul>
        </Modal>
      )}

      {subiendo && (
        <SubirManual tipos={tipos.datos ?? []} alCerrar={() => setSubiendo(false)} alError={alError}
          alGuardar={async () => { setSubiendo(false); alAviso('Manual publicado'); await cargar() }} />
      )}

      {nuevaVersionDe && (
        <NuevaVersion manual={nuevaVersionDe} alCerrar={() => setNuevaVersionDe(null)} alError={alError}
          alGuardar={async () => {
            setNuevaVersionDe(null)
            alAviso('Versión publicada: a quien lo tenga descargado se le avisa que hay una nueva')
            await cargar()
          }} />
      )}
    </div>
  )
}

function SubirManual({ tipos, alCerrar, alGuardar, alError }: {
  tipos: TipoEquipo[]; alCerrar: () => void; alGuardar: () => Promise<void>; alError: (m: string | null) => void
}) {
  const [tipoId, setTipoId] = useState('')
  const [titulo, setTitulo] = useState('')
  const [categoria, setCategoria] = useState<CategoriaManual>('ficha_tecnica')
  const [descripcion, setDescripcion] = useState('')
  const [archivo, setArchivo] = useState<File | null>(null)
  const [guardando, setGuardando] = useState(false)

  async function guardar() {
    if (!archivo) return
    alError(null)
    setGuardando(true)
    try {
      await subirManual({ tipo_equipo_id: tipoId, titulo, categoria, descripcion }, archivo)
      await alGuardar()
    } catch (e) { alError(mensajeDeError(e)) } finally { setGuardando(false) }
  }

  return (
    <Modal titulo="Subir manual o ficha" abierto alCerrar={alCerrar}>
      <div className="grid gap-3">
        <Selector etiqueta="Tipo de equipo" value={tipoId} onChange={(e) => setTipoId(e.target.value)}
          opciones={[{ valor: '', texto: 'Elige…' }, ...tipos.map((t) => ({ valor: t.id, texto: t.nombre }))]} />
        <Campo etiqueta="Título" value={titulo} onChange={(e) => setTitulo(e.target.value)} />
        <Selector etiqueta="Categoría" value={categoria} onChange={(e) => setCategoria(e.target.value as CategoriaManual)}
          opciones={(Object.keys(NOMBRE_CATEGORIA) as CategoriaManual[]).map((c) => ({ valor: c, texto: NOMBRE_CATEGORIA[c] }))} />
        <Campo etiqueta="Descripción" value={descripcion} onChange={(e) => setDescripcion(e.target.value)} />
        <label className="text-sm">
          <span className="mb-1 block font-medium text-slate-700">Archivo (PDF, imagen o video corto, hasta 50 MB)</span>
          <input type="file" aria-label="Archivo del manual"
            accept="application/pdf,image/jpeg,image/png,image/webp,video/mp4,video/webm"
            onChange={(e) => setArchivo(e.target.files?.[0] ?? null)} />
        </label>
        <div className="flex justify-end gap-2">
          <Boton variante="secundario" onClick={alCerrar}>Cancelar</Boton>
          <Boton disabled={!tipoId || !titulo || !archivo || guardando} onClick={() => void guardar()}>Publicar</Boton>
        </div>
      </div>
    </Modal>
  )
}

function NuevaVersion({ manual, alCerrar, alGuardar, alError }: {
  manual: Manual; alCerrar: () => void; alGuardar: () => Promise<void>; alError: (m: string | null) => void
}) {
  const [archivo, setArchivo] = useState<File | null>(null)
  const [notas, setNotas] = useState('')
  const [guardando, setGuardando] = useState(false)

  async function guardar() {
    if (!archivo) return
    alError(null)
    setGuardando(true)
    try { await subirVersion(manual.id, archivo, notas); await alGuardar() }
    catch (e) { alError(mensajeDeError(e)) } finally { setGuardando(false) }
  }

  return (
    <Modal titulo={`Nueva versión de ${manual.titulo}`} abierto alCerrar={alCerrar}>
      <div className="grid gap-3">
        <p className="text-sm text-slate-600">Quedará como v{manual.version + 1}; la v{manual.version} se conserva en el historial.</p>
        <label className="text-sm">
          <span className="mb-1 block font-medium text-slate-700">Archivo nuevo</span>
          <input type="file" aria-label="Archivo de la nueva versión"
            accept="application/pdf,image/jpeg,image/png,image/webp,video/mp4,video/webm"
            onChange={(e) => setArchivo(e.target.files?.[0] ?? null)} />
        </label>
        <Campo etiqueta="Qué cambió" value={notas} onChange={(e) => setNotas(e.target.value)} />
        <div className="flex justify-end gap-2">
          <Boton variante="secundario" onClick={alCerrar}>Cancelar</Boton>
          <Boton disabled={!archivo || guardando} onClick={() => void guardar()}>Publicar versión</Boton>
        </div>
      </div>
    </Modal>
  )
}

// ------------------------------------------------------------------ contenido de servicio
function Contenido({ gestiona, esCliente, alError, alAviso }: {
  gestiona: boolean; esCliente: boolean; alError: (m: string | null) => void; alAviso: (m: string | null) => void
}) {
  const [filas, setFilas] = useState<ContenidoServicio[]>([])
  const [editando, setEditando] = useState<ContenidoServicio | 'nuevo' | null>(null)
  const [avisos, setAvisos] = useState<string[]>([])

  const cargar = useCallback(async () => {
    try { setFilas(await listarContenido()) } catch (e) { alError(mensajeDeError(e)) }
  }, [alError])
  useEffect(() => { void cargar() }, [cargar])

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-slate-600">
          {esCliente
            ? 'Define qué incluye el servicio de cada tipo de equipo: los puntos de revisión se le muestran al técnico en el folio y se guardan en su teléfono para trabajar sin señal.'
            : 'Lo que el cliente definió como alcance del servicio por tipo de equipo. Solo baja a tu teléfono el contenido de los folios que tienes asignados.'}
        </p>
        {gestiona && <Boton onClick={() => setEditando('nuevo')}>Nuevo contenido</Boton>}
      </div>
      {avisos.length > 0 && (
        <Aviso tipo="info">
          <span className="font-medium">Diferencias con la iguala del contrato:</span>
          <ul className="mt-1 list-disc pl-5">{avisos.map((a, i) => <li key={i}>{a}</li>)}</ul>
        </Aviso>
      )}
      <div className="grid gap-4 md:grid-cols-2" data-testid="contenido-servicio">
        {filas.map((c) => (
          <Tarjeta key={c.id} titulo={c.titulo}
            acciones={gestiona ? <Boton variante="secundario" onClick={() => setEditando(c)}>Editar</Boton> : undefined}>
            <p className="text-sm text-slate-600">
              {c.tipo_equipo} · {c.periodicidad ?? 'sin periodicidad'} · v{c.version}
              {!c.activo && <Insignia tono="neutro">Inactivo</Insignia>}
            </p>
            <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm">
              {c.puntos_revision.map((p, i) => (
                <li key={i}>
                  {p.descripcion}
                  {p.obligatorio && <Insignia tono="alerta">Obligatorio</Insignia>}
                </li>
              ))}
            </ol>
            {c.puntos_revision.length === 0 && <p className="mt-2 text-sm text-slate-500">Sin puntos de revisión.</p>}
          </Tarjeta>
        ))}
        {filas.length === 0 && <p className="text-sm text-slate-500">Sin contenido de servicio registrado.</p>}
      </div>

      {editando && (
        <EditorContenido inicial={editando === 'nuevo' ? null : editando} alCerrar={() => setEditando(null)}
          alError={alError}
          alGuardar={async (avisosNuevos) => {
            setEditando(null)
            setAvisos(avisosNuevos)
            alAviso('Contenido de servicio guardado')
            await cargar()
          }} />
      )}
    </div>
  )
}

function EditorContenido({ inicial, alCerrar, alGuardar, alError }: {
  inicial: ContenidoServicio | null; alCerrar: () => void
  alGuardar: (avisos: string[]) => Promise<void>; alError: (m: string | null) => void
}) {
  const tipos = useRecurso<TipoEquipo[]>('/catalogos/tipos-equipo')
  const contratos = useRecurso<Contrato[]>('/contratos')
  const [tipoId, setTipoId] = useState(inicial?.tipo_equipo_id ?? '')
  const [contratoId, setContratoId] = useState(inicial?.contrato_id ?? '')
  const [titulo, setTitulo] = useState(inicial?.titulo ?? '')
  const [periodicidad, setPeriodicidad] = useState(inicial?.periodicidad ?? '')
  const [correctivos, setCorrectivos] = useState(inicial?.correctivos_iguala?.toString() ?? '')
  const [puntos, setPuntos] = useState<PuntoRevision[]>(inicial?.puntos_revision ?? [{ descripcion: '', obligatorio: true }])
  const [guardando, setGuardando] = useState(false)

  function cambiar(i: number, cambios: Partial<PuntoRevision>) {
    setPuntos(puntos.map((p, j) => j === i ? { ...p, ...cambios } : p))
  }
  /** El orden importa: es el que el técnico ve en el folio, así que se edita moviendo los puntos. */
  function mover(i: number, delta: number) {
    const destino = i + delta
    if (destino < 0 || destino >= puntos.length) return
    const copia = [...puntos]
    const [fila] = copia.splice(i, 1)
    copia.splice(destino, 0, fila!)
    setPuntos(copia)
  }

  async function guardar() {
    alError(null)
    setGuardando(true)
    try {
      const limpios = puntos.filter((p) => p.descripcion.trim())
        .map((p, i) => ({ ...p, descripcion: p.descripcion.trim(), orden: i + 1 }))
      const r = await guardarContenido({
        tipo_equipo_id: tipoId, contrato_id: contratoId, titulo, puntos_revision: limpios,
        periodicidad: periodicidad || null,
        correctivos_iguala: correctivos ? Number(correctivos) : null,
      })
      await alGuardar(r.avisos)
    } catch (e) { alError(mensajeDeError(e)) } finally { setGuardando(false) }
  }

  return (
    <Modal titulo={inicial ? `Editar ${inicial.titulo}` : 'Nuevo contenido de servicio'} abierto alCerrar={alCerrar}>
      <div className="grid gap-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Selector etiqueta="Tipo de equipo" value={tipoId} onChange={(e) => setTipoId(e.target.value)}
            disabled={!!inicial}
            opciones={[{ valor: '', texto: 'Elige…' }, ...(tipos.datos ?? []).map((t) => ({ valor: t.id, texto: t.nombre }))]} />
          <Selector etiqueta="Contrato" value={contratoId} onChange={(e) => setContratoId(e.target.value)}
            opciones={[{ valor: '', texto: 'Elige…' }, ...(contratos.datos ?? []).map((c) => ({ valor: c.id, texto: `${c.nombre} (${c.modalidad})` }))]} />
        </div>
        <Campo etiqueta="Título" value={titulo} onChange={(e) => setTitulo(e.target.value)} />
        <div className="grid gap-3 sm:grid-cols-2">
          <Selector etiqueta="Periodicidad del preventivo" value={periodicidad} onChange={(e) => setPeriodicidad(e.target.value)}
            opciones={[{ valor: '', texto: 'Sin definir' }, { valor: 'mensual', texto: 'Mensual' },
              { valor: 'bimestral', texto: 'Bimestral' }, { valor: 'trimestral', texto: 'Trimestral' },
              { valor: 'semestral', texto: 'Semestral' }, { valor: 'anual', texto: 'Anual' }]} />
          <Campo etiqueta="Correctivos incluidos en la iguala" type="number" value={correctivos}
            onChange={(e) => setCorrectivos(e.target.value)} />
        </div>

        <div>
          <p className="mb-1 text-sm font-medium text-slate-700">Puntos de revisión, en el orden en que se revisan</p>
          <ul className="grid gap-2" data-testid="puntos-revision">
            {puntos.map((p, i) => (
              <li key={i} className="flex flex-wrap items-center gap-2">
                <span className="w-5 text-right text-xs text-slate-500">{i + 1}.</span>
                <input className="min-w-56 flex-1 rounded-lg border border-slate-300 px-2 py-1 text-sm"
                  aria-label={`Punto ${i + 1}`} value={p.descripcion}
                  onChange={(e) => cambiar(i, { descripcion: e.target.value })} />
                <label className="flex items-center gap-1 text-xs">
                  <input type="checkbox" checked={p.obligatorio !== false}
                    onChange={(e) => cambiar(i, { obligatorio: e.target.checked })} />
                  Obligatorio
                </label>
                <button className="text-xs text-primario underline" aria-label={`Subir punto ${i + 1}`} onClick={() => mover(i, -1)}>↑</button>
                <button className="text-xs text-primario underline" aria-label={`Bajar punto ${i + 1}`} onClick={() => mover(i, 1)}>↓</button>
                <button className="text-xs text-red-700 underline" aria-label={`Quitar punto ${i + 1}`}
                  onClick={() => setPuntos(puntos.filter((_, j) => j !== i))}>Quitar</button>
              </li>
            ))}
          </ul>
          <div className="mt-2">
            <Boton variante="secundario" onClick={() => setPuntos([...puntos, { descripcion: '', obligatorio: true }])}>
              Agregar punto
            </Boton>
          </div>
        </div>

        <div className="flex justify-end gap-2">
          <Boton variante="secundario" onClick={alCerrar}>Cancelar</Boton>
          <Boton disabled={!tipoId || !contratoId || !titulo || guardando} onClick={() => void guardar()}>Guardar</Boton>
        </div>
      </div>
    </Modal>
  )
}
