import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router'
import { Aviso, Boton, Campo, Encabezado, Insignia, Modal, Selector, Tabla } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { useRecurso } from '../../hooks/useRecurso'
import { api, mensajeDeError } from '../../services/api'
import { cargarCalendario, editarCalendario, generarAhora, listarCalendario, mesDe, publicaciones, publicarMes } from '../../services/preventivos'
import type { Equipo, Tecnico, Tenant, UnidadNegocio } from '../../types/api'
import type { EstadoPreventivo, FilaCalendario, FilaCalendarioEntrada, Plan, Publicacion } from '../../types/preventivos'
import { NOMBRE_ESTADO_PREVENTIVO, NOMBRE_ORIGEN, ROLES_CARGAN_CALENDARIO, ROLES_PLANES } from '../../types/preventivos'
import { EstadoInsignia } from '../folios/comunes'

const TONO: Record<EstadoPreventivo, 'neutro' | 'ok' | 'alerta' | 'acento'> = { programado: 'neutro', generado: 'acento', ejecutado: 'ok', reprogramado: 'alerta', cancelado: 'alerta' }

/** Calendario mensual de preventivos (§7.6): carga manual, edición, publicación del mes y desvío fecha programada vs. real. */
export function Calendario() {
  const { usuario } = useAuth()
  const esPrestador = usuario?.dominio === 'prestador' || usuario?.rol === 'superadmin'
  const puedeCargar = !!usuario && ROLES_CARGAN_CALENDARIO.includes(usuario.rol)
  const [mes, setMes] = useState(mesDe())
  const [tenantId, setTenantId] = useState('')
  const [estado, setEstado] = useState('')
  const [filas, setFilas] = useState<FilaCalendario[]>([])
  const [pubs, setPubs] = useState<Publicacion[]>([])
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [cargando, setCargando] = useState(false)
  const [abrirCarga, setAbrirCarga] = useState(false)
  const [editando, setEditando] = useState<FilaCalendario | null>(null)
  const tenants = useRecurso<Tenant[]>(esPrestador ? '/tenants' : null)

  useEffect(() => {
    const primero = tenants.datos?.[0]
    if (esPrestador && !tenantId && primero) setTenantId(primero.id)
  }, [esPrestador, tenantId, tenants.datos])

  async function cargar() {
    setCargando(true)
    setError(null)
    try {
      const [lista, p] = await Promise.all([
        listarCalendario({ mes, tenant_id: tenantId || undefined, estado: estado || undefined }),
        publicaciones(tenantId || undefined).catch(() => [] as Publicacion[]),
      ])
      setFilas(lista)
      setPubs(p)
    } catch (e) {
      setError(mensajeDeError(e))
    } finally {
      setCargando(false)
    }
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void cargar() }, [mes, tenantId, estado])

  const publicacion = pubs.find((p) => p.mes.startsWith(mes) && (!tenantId || p.tenant_id === tenantId))
  const resumen = useMemo(() => {
    const r: Record<EstadoPreventivo, number> = { programado: 0, generado: 0, ejecutado: 0, reprogramado: 0, cancelado: 0 }
    for (const f of filas) r[f.estado] += 1
    return r
  }, [filas])

  async function publicar() {
    try {
      const p = await publicarMes(mes, tenantId || undefined)
      setAviso(`Calendario de ${mes} publicado: ${p.total_preventivos} preventivo(s). Se notificó al Admin empresa y a los Admin UN.`)
      await cargar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  async function generar() {
    try {
      const r = await generarAhora(7)
      setAviso(`Generación ejecutada: ${r.planes} por plan, ${r.manuales} manuales, ${r.omitidos} omitidos, ${r.errores} errores.`)
      await cargar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  return (
    <div>
      <Encabezado
        titulo="Calendario de preventivos"
        descripcion="Programación mensual (manual o por planes con triggers). Al publicar el mes, ACMA avisa al cliente; cada preventivo muestra el desvío entre la fecha programada y la real."
        acciones={
          <div className="flex flex-wrap gap-2">
            {usuario && ROLES_PLANES.includes(usuario.rol) && <Link to="/preventivos/planes"><Boton variante="secundario">Planes</Boton></Link>}
            <Link to="/preventivos/autorizaciones"><Boton variante="secundario">Autorizaciones</Boton></Link>
            {puedeCargar && <Boton variante="secundario" onClick={() => setAbrirCarga(true)}>Cargar preventivos</Boton>}
            {puedeCargar && <Boton onClick={() => void publicar()} disabled={filas.length === 0}>{publicacion ? 'Volver a publicar el mes' : 'Publicar el mes'}</Boton>}
          </div>
        }
      />
      <div className="mb-4 flex flex-wrap items-end gap-2">
        <Campo etiqueta="Mes" type="month" value={mes} onChange={(e) => setMes(e.target.value)} />
        {esPrestador && (
          <Selector etiqueta="Cliente" value={tenantId} onChange={(e) => setTenantId(e.target.value)}
                    opciones={[{ valor: '', texto: 'Todos los clientes' }, ...(tenants.datos ?? []).map((t) => ({ valor: t.id, texto: t.razon_social }))]} />
        )}
        <Selector etiqueta="Estado" value={estado} onChange={(e) => setEstado(e.target.value)}
                  opciones={[{ valor: '', texto: 'Todos' }, ...(Object.keys(NOMBRE_ESTADO_PREVENTIVO) as EstadoPreventivo[]).map((e) => ({ valor: e, texto: NOMBRE_ESTADO_PREVENTIVO[e] }))]} />
        {puedeCargar && <Boton variante="fantasma" onClick={() => void generar()} title="Misma lógica que la tarea nocturna">Generar folios ahora</Boton>}
      </div>
      <div className="mb-4 flex flex-wrap items-center gap-2 text-xs text-slate-600" data-testid="resumen-mes">
        {publicacion ? <Insignia tono="ok">Publicado el {new Date(publicacion.publicado_at).toLocaleDateString('es-MX')} · {publicacion.total_preventivos} preventivos</Insignia> : <Insignia tono="alerta">Mes sin publicar</Insignia>}
        {(Object.keys(resumen) as EstadoPreventivo[]).map((e) => <span key={e}>{NOMBRE_ESTADO_PREVENTIVO[e]}: <strong>{resumen[e]}</strong></span>)}
      </div>
      {error && <div className="mb-3"><Aviso>{error}</Aviso></div>}
      {aviso && <div className="mb-3"><Aviso tipo="exito">{aviso}</Aviso></div>}
      {cargando && filas.length === 0 && <p className="text-sm text-slate-500">Cargando calendario…</p>}
      <div className="rounded-xl border border-slate-200 bg-white p-2">
        <Tabla
          filas={filas}
          vacio="Sin preventivos en este mes"
          columnas={[
            { titulo: 'Fecha', celda: (f) => <span className="font-mono text-xs">{f.fecha_programada}{f.fecha_programada_original && f.fecha_programada_original !== f.fecha_programada && <span className="block text-slate-400 line-through">{f.fecha_programada_original}</span>}</span> },
            { titulo: 'UN / Equipo', celda: (f) => <span>{f.un_codigo} <span className="text-xs text-slate-500">{f.un_nombre}</span>{f.equipo_codigo ? <span className="block">{f.equipo_codigo} <span className="text-xs text-slate-500">{f.equipo_nombre}</span></span> : <span className="block text-xs text-slate-500">UN completa</span>}</span> },
            { titulo: 'Plan / descripción', celda: (f) => <span>{f.plan_nombre ?? <span className="text-xs text-slate-500">—</span>}{f.descripcion && <span className="block text-xs text-slate-600">{f.descripcion}</span>}</span> },
            // F2-04 (§6.9.1): el calendario dice de dónde salió cada preventivo, y con qué lectura si fue por uso.
            { titulo: 'Origen', celda: (f) => (
              <span data-testid={`origen-${f.id}`}>
                <Insignia tono={f.origen === 'medidor' ? 'acento' : f.origen === 'evento' ? 'alerta' : 'neutro'}>{NOMBRE_ORIGEN[f.origen]}</Insignia>
                {f.valor_medidor != null && <span className="block text-xs text-slate-500">con el medidor en {Number(f.valor_medidor)}</span>}
              </span>
            ) },
            { titulo: 'Técnico', celda: (f) => f.tecnico_nombre ?? <span className="text-xs text-slate-400">—</span> },
            { titulo: 'Estado', celda: (f) => <div className="flex flex-wrap gap-1"><Insignia tono={TONO[f.estado]}>{NOMBRE_ESTADO_PREVENTIVO[f.estado]}</Insignia>{f.estado_folio && <EstadoInsignia estado={f.estado_folio} />}</div> },
            { titulo: 'Folio', celda: (f) => f.folio_id ? <Link to={`/folios/${f.folio_id}`} className="font-mono text-xs text-primario underline">{f.numero_folio}</Link> : <span className="text-xs text-slate-400">—</span> },
            { titulo: 'Ejecución', celda: (f) => <span className="text-xs">{f.fecha_real ? <span className="font-mono">{f.fecha_real}</span> : null}<span className={`block ${f.desvio_dias != null && f.desvio_dias > 0 ? 'text-amber-800' : f.desvio_dias != null && f.desvio_dias < 0 ? 'text-sky-800' : 'text-slate-500'}`} data-testid={`desvio-${f.id}`}>{f.texto_desvio}</span></span> },
            { titulo: '', celda: (f) => puedeCargar && !['ejecutado', 'cancelado', 'reprogramado'].includes(f.estado) ? <Boton variante="fantasma" onClick={() => setEditando(f)}>Editar</Boton> : null },
          ]}
        />
      </div>

      {abrirCarga && <CargaPreventivos tenantId={tenantId || null} alCerrar={() => setAbrirCarga(false)} alCargar={async (n) => { setAbrirCarga(false); setAviso(`${n} preventivo(s) cargados`); await cargar() }} />}
      {editando && <EditarPreventivo fila={editando} alCerrar={() => setEditando(null)} alGuardar={async () => { setEditando(null); await cargar() }} />}
    </div>
  )
}

function CargaPreventivos({ tenantId, alCerrar, alCargar }: { tenantId: string | null; alCerrar: () => void; alCargar: (n: number) => Promise<void> }) {
  const [filas, setFilas] = useState<FilaCalendarioEntrada[]>([{ un_id: '', equipo_id: null, plan_id: null, tecnico_id: null, fecha_programada: '', descripcion: '' }])
  const [error, setError] = useState<string | null>(null)
  const [guardando, setGuardando] = useState(false)
  const unidades = useRecurso<UnidadNegocio[]>('/unidades-negocio', { tenant_id: tenantId ?? undefined })
  const equipos = useRecurso<Equipo[]>('/catalogos/equipos', { tenant_id: tenantId ?? undefined })
  const planes = useRecurso<Plan[]>('/planes', { solo_activos: 'true' })
  const tecnicos = useRecurso<Tecnico[]>('/catalogos/tecnicos', { solo_activos: 'true' })

  function cambiar(i: number, cambios: Partial<FilaCalendarioEntrada>) {
    setFilas((fs) => fs.map((f, j) => (j === i ? { ...f, ...cambios } : f)))
  }
  async function guardar() {
    setGuardando(true)
    setError(null)
    try {
      const listas = filas.filter((f) => f.un_id && f.fecha_programada).map((f) => ({ ...f, equipo_id: f.equipo_id || null, plan_id: f.plan_id || null, tecnico_id: f.tecnico_id || null }))
      if (listas.length === 0) { setError('Indica al menos una UN con fecha'); return }
      const r = await cargarCalendario(listas, tenantId)
      await alCargar(r.length)
    } catch (e) {
      setError(mensajeDeError(e))
    } finally {
      setGuardando(false)
    }
  }
  return (
    <Modal titulo="Cargar preventivos" abierto alCerrar={alCerrar}>
      <p className="mb-3 text-sm text-slate-600">Una fila por preventivo. Sin equipo = preventivo de la UN completa (no genera folio hasta asignarle un equipo). También puedes importar el catálogo <strong>calendario_preventivos</strong> desde Catálogos → Importar.</p>
      {error && <div className="mb-3"><Aviso>{error}</Aviso></div>}
      <div className="max-h-96 space-y-3 overflow-y-auto pr-1">
        {filas.map((f, i) => (
          <div key={i} className="grid gap-2 rounded-lg border border-slate-200 p-2 sm:grid-cols-2" data-testid={`fila-carga-${i}`}>
            <Selector etiqueta="Unidad de negocio" value={f.un_id} onChange={(e) => cambiar(i, { un_id: e.target.value, equipo_id: null })}
                      opciones={[{ valor: '', texto: 'Elegir UN…' }, ...(unidades.datos ?? []).map((u) => ({ valor: u.id, texto: `${u.codigo} · ${u.nombre}` }))]} />
            <Selector etiqueta="Equipo (opcional)" value={f.equipo_id ?? ''} onChange={(e) => cambiar(i, { equipo_id: e.target.value || null })}
                      opciones={[{ valor: '', texto: 'UN completa' }, ...(equipos.datos ?? []).filter((e) => !f.un_id || e.un_id === f.un_id).map((e) => ({ valor: e.id, texto: `${e.codigo} · ${e.nombre}` }))]} />
            <Campo etiqueta="Fecha programada" type="date" value={f.fecha_programada} onChange={(e) => cambiar(i, { fecha_programada: e.target.value })} />
            <Selector etiqueta="Plan (opcional)" value={f.plan_id ?? ''} onChange={(e) => cambiar(i, { plan_id: e.target.value || null })}
                      opciones={[{ valor: '', texto: 'Sin plan (manual)' }, ...(planes.datos ?? []).map((p) => ({ valor: p.id, texto: p.nombre }))]} />
            <Selector etiqueta="Técnico (opcional)" value={f.tecnico_id ?? ''} onChange={(e) => cambiar(i, { tecnico_id: e.target.value || null })}
                      opciones={[{ valor: '', texto: 'Por asignar' }, ...(tecnicos.datos ?? []).map((t) => ({ valor: t.usuario_id, texto: t.nombre }))]} />
            <Campo etiqueta="Descripción" value={f.descripcion ?? ''} onChange={(e) => cambiar(i, { descripcion: e.target.value })} />
          </div>
        ))}
      </div>
      <div className="mt-3 flex justify-between gap-2">
        <Boton variante="fantasma" onClick={() => setFilas((fs) => [...fs, { un_id: '', equipo_id: null, plan_id: null, tecnico_id: null, fecha_programada: '', descripcion: '' }])}>+ Otra fila</Boton>
        <div className="flex gap-2">
          <Boton variante="fantasma" onClick={alCerrar}>Cancelar</Boton>
          <Boton onClick={() => void guardar()} disabled={guardando}>Cargar</Boton>
        </div>
      </div>
    </Modal>
  )
}

function EditarPreventivo({ fila, alCerrar, alGuardar }: { fila: FilaCalendario; alCerrar: () => void; alGuardar: () => Promise<void> }) {
  const [tecnicoId, setTecnicoId] = useState(fila.tecnico_id ?? '')
  const [fecha, setFecha] = useState(fila.fecha_programada)
  const [descripcion, setDescripcion] = useState(fila.descripcion)
  const [error, setError] = useState<string | null>(null)
  const [tecnicos, setTecnicos] = useState<Tecnico[]>([])
  useEffect(() => { api<Tecnico[]>('/catalogos/tecnicos', { params: { solo_activos: true } }).then(setTecnicos).catch(() => setTecnicos([])) }, [])
  async function guardar() {
    try {
      const cambios: Partial<FilaCalendarioEntrada> = { tecnico_id: tecnicoId || null, descripcion }
      if (fecha !== fila.fecha_programada) cambios.fecha_programada = fecha
      await editarCalendario(fila.id, cambios)
      await alGuardar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }
  return (
    <Modal titulo={`Editar preventivo · ${fila.un_codigo} ${fila.equipo_codigo ?? ''}`} abierto alCerrar={alCerrar}>
      {error && <div className="mb-3"><Aviso>{error}</Aviso></div>}
      <div className="space-y-3">
        <Selector etiqueta="Técnico" value={tecnicoId} onChange={(e) => setTecnicoId(e.target.value)} opciones={[{ valor: '', texto: 'Por asignar' }, ...tecnicos.map((t) => ({ valor: t.usuario_id, texto: t.nombre }))]} />
        <Campo etiqueta={fila.folio_id ? 'Fecha (con folio generado solo cambia con reprogramación autorizada)' : 'Fecha programada'} type="date" value={fecha} disabled={!!fila.folio_id} onChange={(e) => setFecha(e.target.value)} />
        <Campo etiqueta="Descripción" value={descripcion} onChange={(e) => setDescripcion(e.target.value)} />
        <div className="flex justify-end gap-2">
          <Boton variante="fantasma" onClick={alCerrar}>Cancelar</Boton>
          <Boton onClick={() => void guardar()}>Guardar</Boton>
        </div>
      </div>
    </Modal>
  )
}
