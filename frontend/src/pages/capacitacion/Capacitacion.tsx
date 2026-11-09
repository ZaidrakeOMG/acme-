import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { Aviso, Boton, Campo, Encabezado, Insignia, Modal, Selector, Tabla, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { useRecurso } from '../../hooks/useRecurso'
import { mensajeDeError } from '../../services/api'
import {
  alertasCapacitacion, constancia, crearCurso, editarCurso, expedienteArchivo, expedienteDe,
  guardarAlertasCapacitacion, listarCursos, registrarCurso, tecnicosDeMisUnidades, vencimientos,
} from '../../services/capacitacion'
import { abrirBlob } from '../../services/minutas'
import type { Habilidad, Tecnico } from '../../types/api'
import type { AlertasCapacitacion, Curso, EstadoCurso, Expediente, TecnicoDelCliente, Vencimiento } from '../../types/capacitacion'
import { COLOR_ESTADO, NOMBRE_ESTADO, ROLES_GESTIONAN_CAPACITACION, ROLES_VISTA_CLIENTE } from '../../types/capacitacion'

type Vista = 'expedientes' | 'catalogo' | 'vencimientos' | 'alertas'

/** Semáforo de vigencia: color **y** texto, para que no dependa de ver el color (§6.10.3). */
export function Semaforo({ estado, dias }: { estado: EstadoCurso; dias?: number | null }) {
  const detalle = estado === 'por_vencer' && dias != null ? ` · ${dias} día(s)`
    : estado === 'vencido' && dias != null ? ` · hace ${Math.abs(dias)} día(s)` : ''
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${COLOR_ESTADO[estado]}`}>
      {NOMBRE_ESTADO[estado]}{detalle}
    </span>
  )
}

/**
 * Capacitación y certificaciones del personal técnico (§6.10.3): catálogo de cursos, expediente por técnico con su
 * constancia, certificación automática de habilidades, próximos vencimientos y la vista del cliente.
 */
export function Capacitacion() {
  const { usuario } = useAuth()
  const [params, setParams] = useSearchParams()
  const vista = (params.get('vista') as Vista) || 'expedientes'
  const tecnicoId = params.get('tecnico')
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)

  function ir(cambios: Record<string, string | null>) {
    const p = new URLSearchParams(params)
    for (const [k, v] of Object.entries(cambios)) { if (v) p.set(k, v); else p.delete(k) }
    setParams(p)
  }

  if (!usuario) return null
  const esCliente = ROLES_VISTA_CLIENTE.includes(usuario.rol) && usuario.rol !== 'superadmin'
  const gestiona = ROLES_GESTIONAN_CAPACITACION.includes(usuario.rol)
  if (esCliente) return <VistaCliente />

  return (
    <div>
      <Encabezado titulo="Capacitación y certificaciones"
        descripcion="Cursos y certificaciones del personal técnico: la constancia queda en el expediente, un curso aprobado certifica la habilidad y al vencer la certificación la habilidad se retira, lo que impide nuevas asignaciones de ese tipo de trabajo." />
      <div className="mb-3 flex flex-wrap gap-1" role="tablist" aria-label="Vistas de capacitación">
        {([['expedientes', 'Expedientes'], ['catalogo', 'Catálogo de cursos'], ['vencimientos', 'Vencimientos'],
          ['alertas', 'Alertas']] as [Vista, string][]).map(([v, texto]) => (
          <button key={v} role="tab" aria-selected={vista === v}
            className={`rounded-lg px-3 py-1.5 text-sm ${vista === v ? 'bg-primario text-white' : 'border border-slate-300'}`}
            onClick={() => ir({ vista: v })}>{texto}</button>
        ))}
      </div>
      {error && <div className="mb-3"><Aviso>{error}</Aviso></div>}
      {aviso && <div className="mb-3"><Aviso tipo="exito">{aviso}</Aviso></div>}

      {vista === 'expedientes' && (
        <Expedientes tecnicoId={tecnicoId} alElegir={(id) => ir({ tecnico: id })} gestiona={gestiona}
          alError={setError} alAviso={setAviso} />
      )}
      {vista === 'catalogo' && <Catalogo gestiona={gestiona} alError={setError} alAviso={setAviso} />}
      {vista === 'vencimientos' && <Vencimientos alVerExpediente={(id) => ir({ vista: 'expedientes', tecnico: id })} />}
      {vista === 'alertas' && <ConfigAlertas gestiona={gestiona} alError={setError} alAviso={setAviso} />}
    </div>
  )
}

// ------------------------------------------------------------------ expedientes
function Expedientes({ tecnicoId, alElegir, gestiona, alError, alAviso }: {
  tecnicoId: string | null; alElegir: (id: string) => void; gestiona: boolean
  alError: (m: string | null) => void; alAviso: (m: string | null) => void
}) {
  const tecnicos = useRecurso<Tecnico[]>('/catalogos/tecnicos')
  const [expediente, setExpediente] = useState<Expediente | null>(null)
  const [registrando, setRegistrando] = useState(false)
  const [busqueda, setBusqueda] = useState('')

  const cargar = useCallback(async () => {
    if (!tecnicoId) { setExpediente(null); return }
    try { setExpediente(await expedienteDe(tecnicoId)) } catch (e) { alError(mensajeDeError(e)) }
  }, [tecnicoId, alError])
  useEffect(() => { void cargar() }, [cargar])

  const texto = busqueda.trim().toLowerCase()
  const filtrados = (tecnicos.datos ?? []).filter(
    (t) => !texto || t.nombre.toLowerCase().includes(texto) || (t.numero_empleado ?? '').toLowerCase().includes(texto))

  return (
    <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
      <Tarjeta titulo="Técnicos">
        {tecnicos.error && <Aviso>{tecnicos.error}</Aviso>}
        {/* Un prestador con decenas de técnicos deja el expediente fuera de la pantalla: se filtra y la lista rueda. */}
        <div className="mb-2">
          <Campo etiqueta="Buscar" placeholder="Nombre o número de empleado" value={busqueda}
            onChange={(e) => setBusqueda(e.target.value)} />
        </div>
        <ul className="max-h-[60vh] divide-y divide-slate-100 overflow-y-auto" data-testid="lista-tecnicos">
          {filtrados.map((t) => (
            <li key={t.id}>
              <button className={`w-full px-2 py-2 text-left text-sm hover:bg-slate-50 ${t.id === tecnicoId ? 'bg-primario/5 font-medium' : ''}`}
                onClick={() => alElegir(t.id)}>
                {t.nombre}
                <span className="block text-xs text-slate-500">{t.numero_empleado ?? 'sin número'}</span>
              </button>
            </li>
          ))}
          {filtrados.length === 0 && (
            <li className="px-2 py-2 text-sm text-slate-500">
              {(tecnicos.datos ?? []).length === 0 ? 'Sin técnicos.' : 'Ningún técnico con ese nombre.'}
            </li>
          )}
        </ul>
      </Tarjeta>

      {!expediente && <p className="text-sm text-slate-500">Elige un técnico para ver su expediente.</p>}
      {expediente && (
        <div className="grid gap-4">
          <Tarjeta titulo={`Cursos y certificaciones de ${expediente.tecnico_nombre}`}
            acciones={
              <div className="flex flex-wrap gap-2">
                {gestiona && <Boton onClick={() => setRegistrando(true)}>Registrar curso</Boton>}
                <Boton variante="secundario" onClick={() => void descargarExpediente(expediente, 'xlsx', alError)}>Excel</Boton>
                <Boton variante="secundario" onClick={() => void descargarExpediente(expediente, 'pdf', alError)}>PDF</Boton>
              </div>}>
            <Tabla filas={expediente.cursos} vacio="Sin cursos registrados" columnas={[
              { titulo: 'Curso', celda: (c) => <span className="text-sm font-medium">{c.curso}</span> },
              { titulo: 'Tipo', celda: (c) => c.tipo === 'certificacion' ? 'Certificación' : 'Curso' },
              { titulo: 'Norma', celda: (c) => c.norma_referencia ?? '—' },
              { titulo: 'Terminó', celda: (c) => c.fecha_fin },
              { titulo: 'Vigencia', celda: (c) => <Semaforo estado={c.estado} dias={c.dias_para_vencer} /> },
              { titulo: 'Vence', celda: (c) => c.vigente_hasta ?? '—' },
              { titulo: 'Habilidad', celda: (c) => c.habilidad ?? '—' },
              {
                titulo: 'Constancia',
                celda: (c) => c.tiene_certificado
                  ? <button className="text-sm text-primario underline"
                      onClick={() => void verConstancia(expediente.tecnico_id, c.id, alError)}>Ver</button>
                  : <span className="text-xs text-slate-400">Sin archivo</span>,
              },
            ]} />
          </Tarjeta>

          <Tarjeta titulo="Habilidades certificadas">
            <p className="mb-2 text-xs text-slate-500">
              Una habilidad certificada por curso se retira sola cuando la certificación vence; las declaradas a mano
              se conservan tal como las dejó el Admin prestador.
            </p>
            <div className="flex flex-wrap gap-2" data-testid="habilidades-derivadas">
              {expediente.habilidades.map((h) => (
                <span key={h.habilidad_id} className="flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1 text-xs">
                  <strong>{h.habilidad}</strong>
                  <span className="text-slate-500">{h.origen === 'curso' ? 'por curso' : 'declarada'}</span>
                  <Semaforo estado={h.estado} />
                  {!h.certificada && <Insignia tono="alerta">No certificada</Insignia>}
                </span>
              ))}
              {expediente.habilidades.length === 0 && <p className="text-sm text-slate-500">Sin habilidades.</p>}
            </div>
          </Tarjeta>
        </div>
      )}

      {registrando && expediente && (
        <RegistrarCurso tecnicoId={expediente.tecnico_id} alCerrar={() => setRegistrando(false)}
          alGuardar={(exp) => { setExpediente(exp); setRegistrando(false); alAviso('Curso registrado') }}
          alError={alError} />
      )}
    </div>
  )
}

async function verConstancia(tecnicoId: string, cursoId: string, alError: (m: string) => void) {
  try { abrirBlob(await constancia(tecnicoId, cursoId), 'constancia.pdf') } catch (e) { alError(mensajeDeError(e)) }
}

async function descargarExpediente(exp: Expediente, formato: 'xlsx' | 'pdf', alError: (m: string) => void) {
  try {
    abrirBlob(await expedienteArchivo(exp.tecnico_id, formato), `expediente_${exp.tecnico_nombre}.${formato}`)
  } catch (e) { alError(mensajeDeError(e)) }
}

function RegistrarCurso({ tecnicoId, alCerrar, alGuardar, alError }: {
  tecnicoId: string; alCerrar: () => void; alGuardar: (e: Expediente) => void; alError: (m: string | null) => void
}) {
  const [cursos, setCursos] = useState<Curso[]>([])
  const [cursoId, setCursoId] = useState('')
  const [fechaFin, setFechaFin] = useState(new Date().toISOString().slice(0, 10))
  const [fechaInicio, setFechaInicio] = useState('')
  const [calificacion, setCalificacion] = useState('')
  const [folio, setFolio] = useState('')
  const [vigenteHasta, setVigenteHasta] = useState('')
  const [razon, setRazon] = useState('')
  const [notas, setNotas] = useState('')
  const [aprobado, setAprobado] = useState(true)
  const [certificado, setCertificado] = useState<File | null>(null)
  const [guardando, setGuardando] = useState(false)

  useEffect(() => { void listarCursos({ solo_activos: true }).then(setCursos).catch(() => setCursos([])) }, [])
  const curso = cursos.find((c) => c.id === cursoId)

  async function guardar() {
    alError(null)
    setGuardando(true)
    try {
      const exp = await registrarCurso(tecnicoId, {
        curso_id: cursoId, fecha_fin: fechaFin, fecha_inicio: fechaInicio, calificacion,
        folio_constancia: folio, vigente_hasta: vigenteHasta, razon_vigencia: razon, notas,
        // El backend toma «ausente» como aprobado: solo se manda cuando NO lo está.
        ...(aprobado ? {} : { aprobado: 'no' }),
      }, certificado)
      alGuardar(exp)
    } catch (e) { alError(mensajeDeError(e)) } finally { setGuardando(false) }
  }

  return (
    <Modal titulo="Registrar curso o certificación" abierto alCerrar={alCerrar}>
      <div className="grid gap-3">
        <Selector etiqueta="Curso" value={cursoId} onChange={(e) => setCursoId(e.target.value)}
          opciones={[{ valor: '', texto: 'Elige…' }, ...cursos.map((c) => ({ valor: c.id, texto: c.nombre }))]} />
        {curso?.vigencia_meses != null && (
          <p className="text-xs text-slate-500">Vigencia del curso: {curso.vigencia_meses} meses desde la fecha de término.</p>
        )}
        <div className="grid gap-3 sm:grid-cols-2">
          <Campo etiqueta="Fecha de término" type="date" value={fechaFin} onChange={(e) => setFechaFin(e.target.value)} />
          <Campo etiqueta="Fecha de inicio (opcional)" type="date" value={fechaInicio} onChange={(e) => setFechaInicio(e.target.value)} />
          <Campo etiqueta="Calificación (opcional)" type="number" step="0.01" value={calificacion} onChange={(e) => setCalificacion(e.target.value)} />
          <Campo etiqueta="Folio de la constancia" value={folio} onChange={(e) => setFolio(e.target.value)} />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={aprobado} onChange={(e) => setAprobado(e.target.checked)} />
          Aprobado (un curso no aprobado no certifica la habilidad)
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          <Campo etiqueta="Vigencia manual (opcional)" type="date" value={vigenteHasta} onChange={(e) => setVigenteHasta(e.target.value)} />
          <Campo etiqueta="Razón de la vigencia manual" value={razon} onChange={(e) => setRazon(e.target.value)} />
        </div>
        <Campo etiqueta="Notas" value={notas} onChange={(e) => setNotas(e.target.value)} />
        <label className="text-sm">
          <span className="mb-1 block font-medium text-slate-700">Constancia (PDF o imagen, hasta 10 MB)</span>
          <input type="file" aria-label="Constancia" accept="application/pdf,image/jpeg,image/png,image/webp"
            onChange={(e) => setCertificado(e.target.files?.[0] ?? null)} />
        </label>
        <div className="flex justify-end gap-2">
          <Boton variante="secundario" onClick={alCerrar}>Cancelar</Boton>
          <Boton disabled={!cursoId || !fechaFin || guardando} onClick={() => void guardar()}>Guardar</Boton>
        </div>
      </div>
    </Modal>
  )
}

// ------------------------------------------------------------------ catálogo
function Catalogo({ gestiona, alError, alAviso }: {
  gestiona: boolean; alError: (m: string | null) => void; alAviso: (m: string | null) => void
}) {
  const [cursos, setCursos] = useState<Curso[]>([])
  const habilidades = useRecurso<Habilidad[]>('/catalogos/habilidades')
  const [nuevo, setNuevo] = useState(false)
  const vacio = {
    nombre: '', proveedor: '', vigencia_meses: '', habilidad_id: '', tipo: 'curso',
    norma_referencia: '', duracion_horas: '', descripcion: '', global: false,
  }
  const [form, setForm] = useState(vacio)

  const cargar = useCallback(async () => {
    try { setCursos(await listarCursos()) } catch (e) { alError(mensajeDeError(e)) }
  }, [alError])
  useEffect(() => { void cargar() }, [cargar])

  async function crear() {
    alError(null)
    try {
      await crearCurso({
        nombre: form.nombre, proveedor: form.proveedor || null, tipo: form.tipo as Curso['tipo'],
        vigencia_meses: form.vigencia_meses ? Number(form.vigencia_meses) : null,
        habilidad_id: form.habilidad_id || null, norma_referencia: form.norma_referencia || null,
        duracion_horas: form.duracion_horas || null, descripcion: form.descripcion, global: form.global,
      })
      setNuevo(false)
      setForm(vacio)
      alAviso('Curso agregado al catálogo')
      await cargar()
    } catch (e) { alError(mensajeDeError(e)) }
  }

  async function alternar(c: Curso) {
    try { await editarCurso(c.id, { activo: !c.activo }); await cargar() } catch (e) { alError(mensajeDeError(e)) }
  }

  return (
    <Tarjeta titulo="Catálogo de cursos y certificaciones"
      acciones={gestiona ? <Boton onClick={() => setNuevo(true)}>Nuevo curso</Boton> : undefined}>
      <p className="mb-2 text-xs text-slate-500">
        Los cursos globales los mantiene la plataforma y los ve cualquier prestador; los propios, solo el tuyo.
      </p>
      <Tabla filas={cursos} vacio="Sin cursos en el catálogo" columnas={[
        { titulo: 'Nombre', celda: (c) => <span className="text-sm font-medium">{c.nombre}</span> },
        { titulo: 'Tipo', celda: (c) => c.tipo === 'certificacion' ? 'Certificación' : 'Curso' },
        { titulo: 'Norma', celda: (c) => c.norma_referencia ?? '—' },
        { titulo: 'Proveedor', celda: (c) => c.proveedor ?? '—' },
        { titulo: 'Vigencia', celda: (c) => c.vigencia_meses ? `${c.vigencia_meses} meses` : 'No caduca' },
        { titulo: 'Alcance', celda: (c) => <Insignia tono={c.prestador_id ? 'neutro' : 'acento'}>{c.prestador_id ? 'Propio' : 'Global'}</Insignia> },
        {
          titulo: 'Estado',
          celda: (c) => gestiona && c.prestador_id
            ? <button className="text-sm text-primario underline" onClick={() => void alternar(c)}>{c.activo ? 'Desactivar' : 'Reactivar'}</button>
            : <Insignia tono={c.activo ? 'ok' : 'neutro'}>{c.activo ? 'Activo' : 'Inactivo'}</Insignia>,
        },
      ]} />
      {nuevo && (
        <Modal titulo="Nuevo curso" abierto alCerrar={() => setNuevo(false)}>
          <div className="grid gap-3">
            <Campo etiqueta="Nombre" value={form.nombre} onChange={(e) => setForm({ ...form, nombre: e.target.value })} />
            <div className="grid gap-3 sm:grid-cols-2">
              <Selector etiqueta="Tipo" value={form.tipo} onChange={(e) => setForm({ ...form, tipo: e.target.value })}
                opciones={[{ valor: 'curso', texto: 'Curso' }, { valor: 'certificacion', texto: 'Certificación' }]} />
              <Campo etiqueta="Norma de referencia" value={form.norma_referencia} onChange={(e) => setForm({ ...form, norma_referencia: e.target.value })} />
              <Campo etiqueta="Proveedor" value={form.proveedor} onChange={(e) => setForm({ ...form, proveedor: e.target.value })} />
              <Campo etiqueta="Duración (horas)" type="number" step="0.5" value={form.duracion_horas} onChange={(e) => setForm({ ...form, duracion_horas: e.target.value })} />
              <Campo etiqueta="Vigencia en meses (vacío = no caduca)" type="number" value={form.vigencia_meses} onChange={(e) => setForm({ ...form, vigencia_meses: e.target.value })} />
              <Selector etiqueta="Habilidad que certifica" value={form.habilidad_id} onChange={(e) => setForm({ ...form, habilidad_id: e.target.value })}
                opciones={[{ valor: '', texto: 'Ninguna' }, ...(habilidades.datos ?? []).map((h) => ({ valor: h.id, texto: h.nombre }))]} />
            </div>
            <Campo etiqueta="Descripción" value={form.descripcion} onChange={(e) => setForm({ ...form, descripcion: e.target.value })} />
            <div className="flex justify-end gap-2">
              <Boton variante="secundario" onClick={() => setNuevo(false)}>Cancelar</Boton>
              <Boton disabled={!form.nombre} onClick={() => void crear()}>Guardar</Boton>
            </div>
          </div>
        </Modal>
      )}
    </Tarjeta>
  )
}

// ------------------------------------------------------------------ vencimientos
function Vencimientos({ alVerExpediente }: { alVerExpediente: (tecnicoId: string) => void }) {
  const [dias, setDias] = useState('')
  const [filas, setFilas] = useState<Vencimiento[]>([])
  const [error, setError] = useState<string | null>(null)

  const cargar = useCallback(async () => {
    try { setFilas(await vencimientos(dias ? Number(dias) : undefined)) } catch (e) { setError(mensajeDeError(e)) }
  }, [dias])
  useEffect(() => { void cargar() }, [cargar])

  return (
    <Tarjeta titulo="Certificaciones por vencer y vencidas">
      {error && <Aviso>{error}</Aviso>}
      <div className="mb-3 max-w-xs">
        <Campo etiqueta="Ventana en días (vacío = la configurada)" type="number" value={dias}
          onChange={(e) => setDias(e.target.value)} />
      </div>
      <Tabla filas={filas.map((v) => ({ ...v, id: v.tecnico_curso_id }))}
        vacio="Ninguna certificación por vencer en la ventana" columnas={[
          {
            titulo: 'Técnico',
            celda: (v) => <button className="text-left text-sm text-primario underline"
              onClick={() => alVerExpediente(v.tecnico_id)}>{v.tecnico_nombre}</button>,
          },
          { titulo: 'Curso', celda: (v) => v.curso },
          { titulo: 'Norma', celda: (v) => v.norma_referencia ?? '—' },
          { titulo: 'Vence', celda: (v) => v.vigente_hasta },
          { titulo: 'Estado', celda: (v) => <Semaforo estado={v.estado} dias={v.dias} /> },
        ]} />
    </Tarjeta>
  )
}

// ------------------------------------------------------------------ alertas
function ConfigAlertas({ gestiona, alError, alAviso }: {
  gestiona: boolean; alError: (m: string | null) => void; alAviso: (m: string | null) => void
}) {
  const [config, setConfig] = useState<AlertasCapacitacion | null>(null)
  useEffect(() => { void alertasCapacitacion().then(setConfig).catch((e) => alError(mensajeDeError(e))) }, [alError])

  async function guardar(cambios: Partial<AlertasCapacitacion>) {
    alError(null)
    try {
      setConfig(await guardarAlertasCapacitacion(cambios))
      alAviso('Configuración guardada')
    } catch (e) { alError(mensajeDeError(e)) }
  }
  if (!config) return <p className="text-sm text-slate-500">Cargando…</p>

  return (
    <Tarjeta titulo="Alerta de certificación vencida">
      <p className="mb-3 text-sm text-slate-600">
        La alerta avisa con la anticipación que elijas y, al vencer, retira la habilidad certificada por el curso:
        desde ese momento el técnico ya no puede recibir folios que la exijan.
      </p>
      <div className="grid gap-3 sm:max-w-md">
        <Campo etiqueta="Días de anticipación" type="number" min={1} max={365} value={config.dias_anticipacion}
          disabled={!gestiona}
          onChange={(e) => setConfig({ ...config, dias_anticipacion: Number(e.target.value) })} />
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={config.notificar_cliente} disabled={!gestiona}
            onChange={(e) => void guardar({ notificar_cliente: e.target.checked })} />
          Avisar también al cliente cuando venza una certificación de quien atiende sus unidades
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={config.activa} disabled={!gestiona}
            onChange={(e) => void guardar({ activa: e.target.checked })} />
          Alerta activa
        </label>
        {gestiona && <div><Boton onClick={() => void guardar({ dias_anticipacion: config.dias_anticipacion })}>Guardar</Boton></div>}
      </div>
    </Tarjeta>
  )
}

// ------------------------------------------------------------------ vista del cliente
/** §6.10.3: el cliente ve la certificación **vigente** de quien atiende sus unidades, sin datos personales ni costos. */
function VistaCliente() {
  const [filas, setFilas] = useState<TecnicoDelCliente[]>([])
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { void tecnicosDeMisUnidades().then(setFilas).catch((e) => setError(mensajeDeError(e))) }, [])

  return (
    <div>
      <Encabezado titulo="Certificaciones del personal que me atiende"
        descripcion="Solo las certificaciones vigentes del personal habilitado en tus unidades o que atendió folios tuyos en los últimos 90 días." />
      {error && <div className="mb-3"><Aviso>{error}</Aviso></div>}
      <div className="grid gap-4 md:grid-cols-2" data-testid="tecnicos-del-cliente">
        {filas.map((t) => (
          <Tarjeta key={t.tecnico_id} titulo={t.nombre}>
            {t.certificaciones.length === 0 && <p className="text-sm text-slate-500">Sin certificaciones vigentes registradas.</p>}
            <ul className="divide-y divide-slate-100">
              {t.certificaciones.map((c, i) => (
                <li key={i} className="py-2 text-sm">
                  <strong>{c.nombre}</strong>
                  {c.norma_referencia && <span className="ml-1 text-slate-500">({c.norma_referencia})</span>}
                  <span className="block text-xs text-slate-500">
                    {c.tipo === 'certificacion' ? 'Certificación' : 'Curso'}
                    {c.proveedor ? ` · ${c.proveedor}` : ''} · {c.vigencia}
                  </span>
                </li>
              ))}
            </ul>
          </Tarjeta>
        ))}
        {filas.length === 0 && !error && (
          <p className="text-sm text-slate-500">Todavía no hay personal con certificaciones vigentes asociado a tus unidades.</p>
        )}
      </div>
    </div>
  )
}
