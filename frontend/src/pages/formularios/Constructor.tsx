import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { Renderizador } from '../../components/formularios/Renderizador'
import { Aviso, Boton, Campo as CampoUI, Encabezado, Insignia, Modal, Selector, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { useRecurso } from '../../hooks/useRecurso'
import { api, mensajeDeError } from '../../services/api'
import { prepararEsquemaDemo } from '../../services/testbot/formularioDemo'
import type { Rol, Tenant } from '../../types/api'
import {
  CATALOGOS_SISTEMA, CONFIG_DEFECTO, NOMBRE_TIPO, TIPOS_CALCULADOS, TIPOS_CAMPO, TIPOS_CON_DEFECTO, TIPOS_CON_OPCIONES, camposDe,
  type Campo, type CatalogoPersonalizado, type CatalogoSistema, type Condicion, type ConfigCampo, type EsquemaFormulario, type Formulario, type FuenteOpciones, type Seccion, type TipoCampo, type VersionFormulario,
} from '../../types/formularios'

const ROLES: Rol[] = ['superadmin', 'admin_prestador', 'direccion_prestador', 'mesa_control', 'despachador', 'supervisor_prestador', 'tecnico', 'admin_empresa', 'admin_un', 'supervisor_operadores', 'operador']
const TIPOS_FORMULARIO = ['captura_operador', 'atencion_tecnico', 'preventivo', 'trabajo_especial', 'encuesta', 'libre'] as const
const NOMBRE_CATALOGO: Record<CatalogoSistema, string> = { equipos_tenant: 'Equipos del tenant', unidades_negocio: 'Unidades de negocio', tecnicos_prestador: 'Técnicos del prestador', tipos_falla: 'Tipos de falla', tipos_equipo: 'Tipos de equipo', familias_equipo: 'Familias de equipo', materiales: 'Materiales / refacciones', proveedores_externos: 'Proveedores externos', catalogo_personalizado: 'Catálogo personalizado' }

const clave = (texto: string, existentes: Set<string>) => {
  let base = texto.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 40) || 'campo'
  if (!/^[a-z]/.test(base)) base = `c_${base}`
  let k = base
  let n = 2
  while (existentes.has(k)) k = `${base}_${n++}`
  return k
}

function campoNuevo(tipo: TipoCampo, existentes: Set<string>): Campo {
  const c: Campo = { clave: clave(NOMBRE_TIPO[tipo], existentes), tipo, etiqueta: NOMBRE_TIPO[tipo], obligatorio: tipo === 'firma', config: structuredClone(CONFIG_DEFECTO[tipo]), condiciones: [] }
  if (TIPOS_CON_OPCIONES.has(tipo)) {
    c.fuente_opciones = tipo === 'boton_grupo'
      ? { origen: 'fija', opciones: [{ valor: 'si', etiqueta: 'Sí', color: '#2E7D32' }, { valor: 'no', etiqueta: 'No', color: '#C62828' }] }
      : { origen: 'fija', opciones: [{ valor: 'opcion_1', etiqueta: 'Opción 1' }, { valor: 'opcion_2', etiqueta: 'Opción 2' }] }
  }
  if (tipo === 'etiqueta_info') c.config.contenido = 'Texto informativo'
  return c
}

const esquemaVacio = (): EsquemaFormulario => ({ version_contrato: 1, secciones: [{ clave: 'seccion_1', titulo: 'Sección 1', campos: [] }] })

export function Constructor() {
  const { formularioId } = useParams()
  const navegar = useNavigate()
  const { usuario } = useAuth()
  const esSuper = usuario?.rol === 'superadmin'
  const [f, setF] = useState<Formulario | null>(null)
  const [meta, setMeta] = useState({ nombre: 'Nuevo formulario', descripcion: '', tipo: 'libre' as (typeof TIPOS_FORMULARIO)[number], rol_destino: ['tecnico'] as Rol[], tenant_id: '', es_plantilla_base: false })
  const [esquema, setEsquema] = useState<EsquemaFormulario>(esquemaVacio)
  const [seleccion, setSeleccion] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [previa, setPrevia] = useState(false)
  const [valoresPrevia, setValoresPrevia] = useState<Record<string, unknown>>({})
  const [publicar, setPublicar] = useState(false)
  const [notas, setNotas] = useState('')
  const [versiones, setVersiones] = useState<VersionFormulario[] | null>(null)
  const [diff, setDiff] = useState<{ de: number; a: number; agregados: string[]; quitados: string[]; modificados: string[] } | null>(null)
  const tenants = useRecurso<Tenant[]>(usuario && usuario.rol !== 'mesa_control' ? '/tenants' : null)
  const personalizados = useRecurso<CatalogoPersonalizado[]>('/formularios/catalogos-personalizados')
  const campos = useMemo(() => camposDe(esquema), [esquema])
  const campoSel = campos.find((c) => c.clave === seleccion) ?? null
  const puedeEditar = f ? f.puede_editar : usuario?.rol !== 'mesa_control'

  useEffect(() => {
    if (!formularioId) return
    api<Formulario>(`/formularios/${formularioId}`).then((d) => {
      setF(d)
      setMeta({ nombre: d.nombre, descripcion: d.descripcion, tipo: d.tipo, rol_destino: d.rol_destino, tenant_id: d.tenant_id ?? '', es_plantilla_base: d.es_plantilla_base })
      setEsquema(d.esquema_json)
    }).catch((e) => setError(mensajeDeError(e)))
  }, [formularioId])

  // ------------------------------------------------------------ edición
  const actualizarCampo = (k: string, cambios: Partial<Campo>) => setEsquema((e) => ({ ...e, secciones: e.secciones.map((s) => ({ ...s, campos: s.campos.map((c) => (c.clave === k ? { ...c, ...cambios } : c)) })) }))
  const agregarCampo = (tipo: TipoCampo, seccionClave?: string, antesDe?: string) => {
    const nuevo = campoNuevo(tipo, new Set(campos.map((c) => c.clave)))
    setEsquema((e) => {
      const destino = seccionClave ?? e.secciones[0]!.clave
      return { ...e, secciones: e.secciones.map((s) => {
        if (s.clave !== destino) return s
        const i = antesDe ? s.campos.findIndex((c) => c.clave === antesDe) : -1
        const lista = [...s.campos]
        lista.splice(i >= 0 ? i : lista.length, 0, nuevo)
        return { ...s, campos: lista }
      }) }
    })
    setSeleccion(nuevo.clave)
  }
  const moverCampo = (k: string, seccionClave: string, antesDe?: string) => setEsquema((e) => {
    const campo = camposDe(e).find((c) => c.clave === k)
    if (!campo || k === antesDe) return e
    const sin = e.secciones.map((s) => ({ ...s, campos: s.campos.filter((c) => c.clave !== k) }))
    return { ...e, secciones: sin.map((s) => {
      if (s.clave !== seccionClave) return s
      const i = antesDe ? s.campos.findIndex((c) => c.clave === antesDe) : -1
      const lista = [...s.campos]
      lista.splice(i >= 0 ? i : lista.length, 0, campo)
      return { ...s, campos: lista }
    }) }
  })
  const quitarCampo = (k: string) => { setEsquema((e) => ({ ...e, secciones: e.secciones.map((s) => ({ ...s, campos: s.campos.filter((c) => c.clave !== k) })) })); setSeleccion(null) }
  const enlazarCatalogo = (k: string, catalogo: CatalogoSistema, personalizadoId?: string) => {
    const c = campos.find((x) => x.clave === k)
    if (!c || !TIPOS_CON_OPCIONES.has(c.tipo) || c.tipo === 'boton_grupo') { setAviso('Arrastra el catálogo sobre un campo de opciones (radio, lista, selección múltiple)'); return }
    actualizarCampo(k, { fuente_opciones: { origen: 'catalogo', catalogo, filtro_contexto: true, campo_padre: null, catalogo_personalizado_id: personalizadoId ?? null } })
  }
  const agregarSeccion = () => setEsquema((e) => ({ ...e, secciones: [...e.secciones, { clave: clave(`seccion ${e.secciones.length + 1}`, new Set(e.secciones.map((s) => s.clave))), titulo: `Sección ${e.secciones.length + 1}`, campos: [] }] }))
  const actualizarSeccion = (k: string, cambios: Partial<Seccion>) => setEsquema((e) => ({ ...e, secciones: e.secciones.map((s) => (s.clave === k ? { ...s, ...cambios } : s)) }))
  const quitarSeccion = (k: string) => setEsquema((e) => (e.secciones.length > 1 ? { ...e, secciones: e.secciones.filter((s) => s.clave !== k) } : e))

  // ------------------------------------------------------------ guardar
  async function guardar(): Promise<Formulario | null> {
    setError(null)
    setAviso(null)
    try {
      const cuerpo = { nombre: meta.nombre, descripcion: meta.descripcion, tipo: meta.tipo, rol_destino: meta.rol_destino, tenant_id: meta.tenant_id || null, esquema, notas_version: notas || undefined }
      let guardado: Formulario
      if (f) {
        const mesa = usuario?.rol === 'mesa_control'
        guardado = await api<Formulario>(`/formularios/${f.id}`, { metodo: 'PUT', cuerpo: mesa ? { esquema, notas_version: notas || undefined } : cuerpo })
      } else {
        guardado = await api<Formulario>('/formularios', { metodo: 'POST', cuerpo: { ...cuerpo, es_plantilla_base: esSuper && meta.es_plantilla_base, prestador_id: null } })
        navegar(`/formularios/constructor/${guardado.id}`, { replace: true })
      }
      setF(guardado)
      setEsquema(guardado.esquema_json)
      setAviso(`Guardado como v${guardado.version_actual}${guardado.version_actual !== guardado.numero_version_publicada ? ' (borrador)' : ''}`)
      return guardado
    } catch (e) {
      setError(mensajeDeError(e))
      return null
    }
  }

  // El TestBot reutiliza exactamente el borrador abierto en el constructor,
  // incluidos cambios sin guardar. Nunca reemplaza otros formularios.
  useEffect(() => {
    const prepararParaTest = (evento: Event) => {
      const solicitud = evento as CustomEvent<{
        resolver: (resultado: { formularioId: string; nombre: string; totalCampos: number }) => void
        rechazar: (error: Error) => void
      }>
      if (!solicitud.detail?.resolver || !solicitud.detail?.rechazar) return
      evento.preventDefault()
      void (async () => {
        if (!esSuper) throw new Error('Solo Superadmin puede ejecutar estas pruebas.')
        if (meta.es_plantilla_base) throw new Error('No se modifica una plantilla base para hacer pruebas.')
        const esquemaPreparado = prepararEsquemaDemo(esquema)
        const nombre = meta.nombre.trim() === 'Nuevo formulario' ? 'Inspección de mantenimiento DEMO' : meta.nombre
        const roles = Array.from(new Set<Rol>([...meta.rol_destino, 'superadmin']))
        const cuerpo = {
          nombre,
          descripcion: meta.descripcion || 'Formulario de prueba para inspección de equipos',
          tipo: meta.tipo,
          rol_destino: roles,
          tenant_id: meta.tenant_id || null,
          esquema: esquemaPreparado,
        }
        setError(null)
        let guardado: Formulario
        if (f) {
          guardado = await api<Formulario>(`/formularios/${f.id}`, { metodo: 'PUT', cuerpo })
        } else {
          guardado = await api<Formulario>('/formularios', {
            metodo: 'POST', cuerpo: { ...cuerpo, es_plantilla_base: false, prestador_id: null },
          })
          navegar(`/formularios/constructor/${guardado.id}`, { replace: true })
        }
        setF(guardado)
        setMeta(m => ({ ...m, nombre: guardado.nombre, descripcion: guardado.descripcion, rol_destino: roles }))
        setEsquema(guardado.esquema_json)
        setAviso('TestBot preparó y guardó este formulario conservando los campos existentes.')
        solicitud.detail.resolver({
          formularioId: guardado.id,
          nombre: guardado.nombre,
          totalCampos: guardado.esquema_json.secciones.reduce((n, sec) => n + sec.campos.length, 0),
        })
      })().catch((e: unknown) => {
        const error = e instanceof Error ? e : new Error(String(e))
        setError(error.message)
        solicitud.detail.rechazar(error)
      })
    }
    window.addEventListener('acma:testbot:preparar', prepararParaTest)
    return () => window.removeEventListener('acma:testbot:preparar', prepararParaTest)
  }, [esSuper, esquema, meta, f, navegar])

  async function publicarAhora() {
    const g = await guardar()
    if (!g) return
    try {
      const p = await api<Formulario>(`/formularios/${g.id}/publicar`, { metodo: 'POST', cuerpo: { notas_version: notas } })
      setF(p)
      setPublicar(false)
      setAviso(`Publicada la versión ${p.numero_version_publicada}`)
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  async function verVersiones() {
    if (!f) return
    setVersiones(await api<VersionFormulario[]>(`/formularios/${f.id}/versiones`))
    setDiff(null)
  }

  const onDropEn = (seccionClave: string, antesDe?: string) => (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    const tipo = e.dataTransfer.getData('tipo') as TipoCampo
    const campo = e.dataTransfer.getData('campo')
    const catalogo = e.dataTransfer.getData('catalogo') as CatalogoSistema
    if (tipo) agregarCampo(tipo, seccionClave, antesDe)
    else if (campo) moverCampo(campo, seccionClave, antesDe)
    else if (catalogo && antesDe) enlazarCatalogo(antesDe, catalogo, e.dataTransfer.getData('personalizado') || undefined)
  }

  return (
    <div className="space-y-4">
      <Encabezado titulo={f ? `Constructor · ${f.nombre}` : 'Nuevo formulario'} descripcion="Arrastra tipos de campo al lienzo, configúralos en el panel y enlaza catálogos del sistema arrastrándolos sobre un campo."
                  acciones={<div className="flex flex-wrap gap-2">
                    <Link to="/formularios"><Boton variante="secundario">Volver</Boton></Link>
                    <Boton variante="secundario" onClick={() => setPrevia(true)}>Vista previa</Boton>
                    {f && <Boton variante="secundario" onClick={() => void verVersiones()}>Versiones</Boton>}
                    {puedeEditar && <Boton variante="secundario" onClick={() => void guardar()}>Guardar</Boton>}
                    {puedeEditar && <Boton onClick={() => setPublicar(true)}>Publicar</Boton>}
                  </div>} />
      {f && <div className="flex flex-wrap gap-2 text-xs"><Insignia tono={f.estado === 'publicado' ? 'ok' : 'alerta'}>{f.estado}</Insignia><Insignia>v{f.version_actual}{f.numero_version_publicada ? ` · publicada v${f.numero_version_publicada}` : ''}</Insignia>{!puedeEditar && <Insignia tono="alerta">Solo lectura</Insignia>}</div>}
      {error && <Aviso>{error}</Aviso>}
      {aviso && <Aviso tipo="info">{aviso}</Aviso>}

      <Tarjeta titulo="Datos del formulario">
        <div className="grid gap-3 md:grid-cols-4">
          <div className="md:col-span-2"><CampoUI etiqueta="Nombre" name="nombre_formulario" value={meta.nombre} disabled={!puedeEditar || usuario?.rol === 'mesa_control'} onChange={(e) => setMeta({ ...meta, nombre: e.target.value })} /></div>
          <Selector etiqueta="Tipo" name="tipo_formulario" value={meta.tipo} disabled={!puedeEditar || usuario?.rol === 'mesa_control'} onChange={(e) => setMeta({ ...meta, tipo: e.target.value as typeof meta.tipo })} opciones={TIPOS_FORMULARIO.map((t) => ({ valor: t, texto: t.replace('_', ' ') }))} />
          {usuario?.rol !== 'mesa_control' && (
            <Selector etiqueta="Alcance" name="alcance" value={meta.tenant_id} disabled={!puedeEditar} onChange={(e) => setMeta({ ...meta, tenant_id: e.target.value })}
                      opciones={[{ valor: '', texto: 'Global (todos mis clientes)' }, ...(tenants.datos ?? []).map((t) => ({ valor: t.id, texto: `Solo ${t.razon_social}` }))]} />
          )}
          <div className="md:col-span-3"><CampoUI etiqueta="Descripción" name="descripcion_formulario" value={meta.descripcion} disabled={!puedeEditar} onChange={(e) => setMeta({ ...meta, descripcion: e.target.value })} /></div>
          {esSuper && !f && <label className="flex items-center gap-2 pt-6 text-sm"><input type="checkbox" checked={meta.es_plantilla_base} onChange={(e) => setMeta({ ...meta, es_plantilla_base: e.target.checked })} /> Plantilla base de plataforma</label>}
        </div>
        <fieldset className="mt-3" disabled={!puedeEditar || usuario?.rol === 'mesa_control'}>
          <legend className="text-sm font-medium text-slate-700">Rol destino</legend>
          <div className="mt-1 flex flex-wrap gap-3 text-sm">
            {ROLES.map((r) => <label key={r} className="flex items-center gap-1"><input type="checkbox" checked={meta.rol_destino.includes(r)} onChange={(e) => setMeta({ ...meta, rol_destino: e.target.checked ? [...meta.rol_destino, r] : meta.rol_destino.filter((x) => x !== r) })} /> {r}</label>)}
          </div>
        </fieldset>
      </Tarjeta>

      <div className="grid gap-4 lg:grid-cols-[220px_1fr_340px]">
        <aside className="space-y-3">
          <Tarjeta titulo="Tipos de campo">
            <ul className="space-y-1" aria-label="Paleta de tipos">
              {TIPOS_CAMPO.map((t) => (
                <li key={t}>
                  <button type="button" draggable={puedeEditar} disabled={!puedeEditar} onDragStart={(e) => e.dataTransfer.setData('tipo', t)} onClick={() => agregarCampo(t)}
                          className="w-full cursor-grab rounded-lg border border-slate-200 px-2 py-1.5 text-left text-xs hover:border-primario hover:bg-primario/5 disabled:cursor-default" data-testid={`paleta-${t}`}>
                    {NOMBRE_TIPO[t]}
                  </button>
                </li>
              ))}
            </ul>
          </Tarjeta>
          <Tarjeta titulo="Catálogos del sistema">
            <p className="mb-2 text-xs text-slate-500">Arrástralos sobre un campo de opciones.</p>
            <ul className="space-y-1">
              {CATALOGOS_SISTEMA.filter((c) => c !== 'catalogo_personalizado').map((c) => (
                <li key={c}><div draggable={puedeEditar} onDragStart={(e) => e.dataTransfer.setData('catalogo', c)} className="cursor-grab rounded-lg bg-acento/20 px-2 py-1 text-xs">{NOMBRE_CATALOGO[c]}</div></li>
              ))}
              {(personalizados.datos ?? []).map((c) => (
                <li key={c.id}><div draggable={puedeEditar} onDragStart={(e) => { e.dataTransfer.setData('catalogo', 'catalogo_personalizado'); e.dataTransfer.setData('personalizado', c.id) }} className="cursor-grab rounded-lg bg-acento/40 px-2 py-1 text-xs">★ {c.nombre}</div></li>
              ))}
            </ul>
          </Tarjeta>
        </aside>

        <main className="space-y-4" aria-label="Lienzo">
          {esquema.secciones.map((s) => (
            <section key={s.clave} className="rounded-xl border border-slate-200 bg-white p-4" onDragOver={(e) => e.preventDefault()} onDrop={onDropEn(s.clave)}>
              <div className="mb-3 flex items-center gap-2">
                <input aria-label="Título de sección" value={s.titulo} disabled={!puedeEditar} onChange={(e) => actualizarSeccion(s.clave, { titulo: e.target.value })} className="flex-1 border-b border-transparent text-base font-semibold text-slate-900 focus:border-primario focus:outline-none" />
                {puedeEditar && esquema.secciones.length > 1 && <button type="button" className="text-xs text-red-700" onClick={() => quitarSeccion(s.clave)}>Quitar sección</button>}
              </div>
              {s.campos.length === 0 && <p className="rounded-lg border border-dashed border-slate-300 p-4 text-center text-xs text-slate-500">Suelta aquí un tipo de campo</p>}
              <ul className="space-y-2">
                {s.campos.map((c) => (
                  <li key={c.clave} draggable={puedeEditar} onDragStart={(e) => e.dataTransfer.setData('campo', c.clave)} onDragOver={(e) => e.preventDefault()} onDrop={onDropEn(s.clave, c.clave)}
                      onClick={() => setSeleccion(c.clave)} data-testid={`lienzo-${c.clave}`}
                      className={`cursor-pointer rounded-lg border px-3 py-2 text-sm ${seleccion === c.clave ? 'border-primario bg-primario/5' : 'border-slate-200 hover:border-slate-300'}`}>
                    <div className="flex items-center justify-between gap-2">
                      <span><span className="font-medium">{c.etiqueta}</span>{c.obligatorio && <span className="text-red-600"> *</span>} <code className="text-[10px] text-slate-400">{c.clave}</code></span>
                      <span className="flex items-center gap-1 text-[10px] text-slate-500">
                        {NOMBRE_TIPO[c.tipo]}
                        {c.fuente_opciones?.origen === 'catalogo' && <Insignia tono="acento">{NOMBRE_CATALOGO[c.fuente_opciones.catalogo]}</Insignia>}
                        {(c.condiciones?.length ?? 0) > 0 && <Insignia tono="alerta">{c.condiciones.length} cond.</Insignia>}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          ))}
          {puedeEditar && <Boton variante="secundario" onClick={agregarSeccion}>+ Sección</Boton>}
        </main>

        <aside>
          <Tarjeta titulo={campoSel ? `Propiedades · ${NOMBRE_TIPO[campoSel.tipo]}` : 'Propiedades'}>
            {!campoSel && <p className="text-xs text-slate-500">Selecciona un campo del lienzo.</p>}
            {campoSel && (
              <PanelPropiedades campo={campoSel} campos={campos} soloLectura={!puedeEditar} personalizados={personalizados.datos ?? []}
                                onChange={(cambios) => actualizarCampo(campoSel.clave, cambios)}
                                onRenombrar={(nueva) => { if (!campos.some((c) => c.clave === nueva)) { actualizarCampo(campoSel.clave, { clave: nueva }); setSeleccion(nueva) } }}
                                onQuitar={() => quitarCampo(campoSel.clave)} />
            )}
          </Tarjeta>
        </aside>
      </div>

      <Modal titulo="Vista previa (renderizador real)" abierto={previa} alCerrar={() => setPrevia(false)}>
        <Renderizador esquema={esquema} respuestas={valoresPrevia} onChange={setValoresPrevia} mostrarErrores contexto={{ tenant_id: meta.tenant_id || null }} />
      </Modal>
      <Modal titulo="Publicar versión" abierto={publicar} alCerrar={() => setPublicar(false)}>
        <div className="space-y-3">
          <p className="text-sm text-slate-600">Se publicará la versión más reciente. Las respuestas ya enviadas conservan su versión.</p>
          <CampoUI etiqueta="Notas de versión" name="notas_version" value={notas} onChange={(e) => setNotas(e.target.value)} />
          <Boton className="w-full" onClick={() => void publicarAhora()}>Guardar y publicar</Boton>
        </div>
      </Modal>
      <Modal titulo="Versiones" abierto={versiones !== null} alCerrar={() => setVersiones(null)}>
        {versiones && (
          <div className="space-y-3 text-sm">
            <ul className="divide-y divide-slate-100">
              {versiones.map((v) => <li key={v.id} className="flex items-center justify-between py-1"><span>v{v.numero_version} {v.publicada_at ? <Insignia tono="ok">publicada {new Date(v.publicada_at).toLocaleDateString('es-MX')}</Insignia> : <Insignia tono="alerta">borrador</Insignia>}</span><span className="text-xs text-slate-500">{v.notas_version}</span></li>)}
            </ul>
            {versiones.length > 1 && f && (
              <div className="flex items-end gap-2">
                <Boton variante="secundario" onClick={async () => setDiff(await api(`/formularios/${f.id}/versiones/diff`, { params: { de: String(versiones.length - 1), a: String(versiones.length) } }))}>
                  Comparar v{versiones.length - 1} → v{versiones.length}
                </Boton>
              </div>
            )}
            {diff && (
              <div className="rounded-lg bg-slate-50 p-3 text-xs">
                <p><strong>Agregados:</strong> {diff.agregados.join(', ') || '—'}</p>
                <p><strong>Quitados:</strong> {diff.quitados.join(', ') || '—'}</p>
                <p><strong>Modificados:</strong> {diff.modificados.join(', ') || '—'}</p>
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  )
}

// ====================================================== panel de propiedades

interface PropsPanel {
  campo: Campo
  campos: Campo[]
  soloLectura: boolean
  personalizados: CatalogoPersonalizado[]
  onChange: (cambios: Partial<Campo>) => void
  onRenombrar: (clave: string) => void
  onQuitar: () => void
}

function PanelPropiedades({ campo, campos, soloLectura, personalizados, onChange, onRenombrar, onQuitar }: PropsPanel) {
  const cfg = campo.config
  const setCfg = (cambios: Partial<ConfigCampo>) => onChange({ config: { ...cfg, ...cambios } })
  const otros = campos.filter((c) => c.clave !== campo.clave)
  return (
    <fieldset disabled={soloLectura} className="space-y-3 text-sm">
      <CampoUI etiqueta="Etiqueta" name="prop_etiqueta" value={campo.etiqueta} onChange={(e) => onChange({ etiqueta: e.target.value })} />
      <CampoUI etiqueta="Clave (sin acentos)" name="prop_clave" value={campo.clave} onChange={(e) => onRenombrar(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_'))} />
      <CampoUI etiqueta="Ayuda" name="prop_ayuda" value={campo.ayuda ?? ''} onChange={(e) => onChange({ ayuda: e.target.value || null })} />
      {!TIPOS_CALCULADOS.has(campo.tipo) && campo.tipo !== 'etiqueta_info' && campo.tipo !== 'firma' && (
        <label className="flex items-center gap-2"><input type="checkbox" checked={campo.obligatorio} onChange={(e) => onChange({ obligatorio: e.target.checked })} /> Obligatorio</label>
      )}
      {TIPOS_CON_DEFECTO.has(campo.tipo) && <EditorDefecto campo={campo} onChange={onChange} />}
      <EditorConfig campo={campo} cfg={cfg} setCfg={setCfg} otros={otros} />
      {TIPOS_CON_OPCIONES.has(campo.tipo) && <EditorFuente campo={campo} otros={otros} personalizados={personalizados} onChange={(fuente_opciones) => onChange({ fuente_opciones })} />}
      <EditorCondiciones campo={campo} otros={otros} onChange={(condiciones) => onChange({ condiciones })} />
      <button type="button" className="text-xs text-red-700 underline" onClick={onQuitar}>Quitar campo</button>
    </fieldset>
  )
}

function EditorDefecto({ campo, onChange }: { campo: Campo; onChange: (c: Partial<Campo>) => void }) {
  const v = campo.valor_defecto
  if (campo.tipo === 'si_no') {
    return (
      <Selector etiqueta="Valor por defecto" name="defecto" value={v === true ? 'true' : v === false ? 'false' : ''} onChange={(e) => onChange({ valor_defecto: e.target.value === '' ? null : e.target.value === 'true', config: { ...campo.config, modo_defecto: e.target.value === '' ? 'sin_defecto' : 'con_defecto' } })}
                opciones={[{ valor: '', texto: 'Sin valor por defecto' }, { valor: 'true', texto: campo.config.etiqueta_si ?? 'Sí' }, { valor: 'false', texto: campo.config.etiqueta_no ?? 'No' }]} />
    )
  }
  if (campo.tipo === 'slider') return <CampoUI etiqueta="Valor por defecto" name="defecto" type="number" value={v == null ? '' : String(v)} onChange={(e) => onChange({ valor_defecto: e.target.value === '' ? null : Number(e.target.value) })} />
  if (campo.tipo === 'opcion_multiple' || campo.tipo === 'seleccion_multiple') return <CampoUI etiqueta="Valores por defecto (separados por coma)" name="defecto" value={Array.isArray(v) ? v.join(',') : ''} onChange={(e) => onChange({ valor_defecto: e.target.value ? e.target.value.split(',').map((x) => x.trim()) : null })} />
  if (campo.tipo === 'fecha_hora') return null  // se configura como "hoy + N" en config
  return <CampoUI etiqueta={campo.tipo === 'texto' || campo.tipo === 'texto_amplio' ? 'Texto sugerido' : 'Valor por defecto'} name="defecto" value={typeof v === 'string' ? v : ''} onChange={(e) => onChange({ valor_defecto: e.target.value || null })} />
}

function Num({ etiqueta, valor, onChange, min, max, step }: { etiqueta: string; valor: number | null | undefined; onChange: (v: number | null) => void; min?: number; max?: number; step?: number }) {
  return <CampoUI etiqueta={etiqueta} name={etiqueta} type="number" min={min} max={max} step={step} value={valor == null ? '' : String(valor)} onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))} />
}
function Bool({ etiqueta, valor, onChange }: { etiqueta: string; valor: boolean | undefined; onChange: (v: boolean) => void }) {
  return <label className="flex items-center gap-2"><input type="checkbox" checked={!!valor} onChange={(e) => onChange(e.target.checked)} /> {etiqueta}</label>
}
function Sel<T extends string>({ etiqueta, valor, onChange, opciones }: { etiqueta: string; valor: T | undefined; onChange: (v: T) => void; opciones: [T, string][] }) {
  return <Selector etiqueta={etiqueta} name={etiqueta} value={valor ?? ''} onChange={(e) => onChange(e.target.value as T)} opciones={opciones.map(([v, t]) => ({ valor: v, texto: t }))} />
}
function Lista({ etiqueta, valor, onChange }: { etiqueta: string; valor: string[] | undefined; onChange: (v: string[]) => void }) {
  return <CampoUI etiqueta={`${etiqueta} (separadas por coma)`} name={etiqueta} value={(valor ?? []).join(', ')} onChange={(e) => onChange(e.target.value.split(',').map((x) => x.trim()).filter(Boolean))} />
}
function Marcas<T extends string>({ etiqueta, valor, onChange, opciones }: { etiqueta: string; valor: T[] | undefined; onChange: (v: T[]) => void; opciones: [T, string][] }) {
  const sel = valor ?? []
  return (
    <div><p className="mb-1 font-medium text-slate-700">{etiqueta}</p><div className="flex flex-wrap gap-2 text-xs">
      {opciones.map(([v, t]) => <label key={v} className="flex items-center gap-1"><input type="checkbox" checked={sel.includes(v)} onChange={(e) => onChange(e.target.checked ? [...sel, v] : sel.filter((x) => x !== v))} /> {t}</label>)}
    </div></div>
  )
}

/** Todos los parámetros de `config` de §4.3, por tipo. */
function EditorConfig({ campo, cfg, setCfg, otros }: { campo: Campo; cfg: ConfigCampo; setCfg: (c: Partial<ConfigCampo>) => void; otros: Campo[] }) {
  const fechas = otros.filter((c) => c.tipo === 'fecha_hora' || c.tipo === 'sello_fecha_hora')
  const fotos = otros.filter((c) => c.tipo === 'fotografia')
  const t = campo.tipo
  return (
    <div className="space-y-2 rounded-lg bg-slate-50 p-3" data-testid="editor-config">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Configuración</p>
      {t === 'si_no' && <><CampoUI etiqueta="Etiqueta Sí" name="etiqueta_si" value={cfg.etiqueta_si ?? ''} onChange={(e) => setCfg({ etiqueta_si: e.target.value })} /><CampoUI etiqueta="Etiqueta No" name="etiqueta_no" value={cfg.etiqueta_no ?? ''} onChange={(e) => setCfg({ etiqueta_no: e.target.value })} /></>}
      {(t === 'opcion_multiple' || t === 'seleccion_multiple') && <><Num etiqueta="Mínimo de selecciones" valor={cfg.min_selecciones} min={0} onChange={(v) => setCfg({ min_selecciones: v ?? 0 })} /><Num etiqueta="Máximo de selecciones" valor={cfg.max_selecciones} min={1} onChange={(v) => setCfg({ max_selecciones: v })} /></>}
      {t === 'seleccion_multiple' && <>
        <Bool etiqueta="Contador de cantidad por opción" valor={cfg.contador_por_opcion} onChange={(v) => setCfg({ contador_por_opcion: v })} />
        {cfg.contador_por_opcion && <div className="grid grid-cols-2 gap-2"><Num etiqueta="Cantidad mínima" valor={cfg.contador_min} min={0} onChange={(v) => setCfg({ contador_min: v ?? 1 })} /><Num etiqueta="Cantidad máxima" valor={cfg.contador_max} min={1} onChange={(v) => setCfg({ contador_max: v })} /></div>}
        <Bool etiqueta="Grupos colapsables (por el campo 'grupo' de cada opción)" valor={cfg.grupos_colapsables} onChange={(v) => setCfg({ grupos_colapsables: v })} />
        <EditorPlantillasCombinacion valor={cfg.plantillas_combinaciones ?? []} onChange={(v) => setCfg({ plantillas_combinaciones: v })} />
      </>}
      {(t === 'texto' || t === 'texto_amplio') && <>
        {t === 'texto_amplio' && <Num etiqueta="Líneas visibles" valor={cfg.lineas_visibles} min={2} max={30} onChange={(v) => setCfg({ lineas_visibles: v ?? 4 })} />}
        <div className="grid grid-cols-2 gap-2"><Num etiqueta="Longitud mínima" valor={cfg.longitud_min} min={0} onChange={(v) => setCfg({ longitud_min: v ?? 0 })} /><Num etiqueta="Longitud máxima" valor={cfg.longitud_max} min={1} onChange={(v) => setCfg({ longitud_max: v ?? 500 })} /></div>
        <Sel etiqueta="Restricción de formato" valor={cfg.formato} onChange={(v) => setCfg({ formato: v })} opciones={[['libre', 'Libre'], ['numeros', 'Solo números'], ['letras', 'Solo letras'], ['regex', 'Expresión regular']]} />
        {cfg.formato === 'regex' && <><CampoUI etiqueta="Expresión regular" name="regex" value={cfg.regex ?? ''} onChange={(e) => setCfg({ regex: e.target.value })} /><CampoUI etiqueta="Mensaje si no cumple" name="mensaje_formato" value={cfg.mensaje_formato ?? ''} onChange={(e) => setCfg({ mensaje_formato: e.target.value || null })} /></>}
      </>}
      {t === 'fotografia' && <>
        <Sel etiqueta="Origen" valor={cfg.origen} onChange={(v) => setCfg({ origen: v })} opciones={[['camara', 'Solo cámara en vivo'], ['camara_galeria', 'Cámara + galería']]} />
        <div className="grid grid-cols-2 gap-2"><Num etiqueta="Fotos mínimas" valor={cfg.cantidad_min} min={0} max={20} onChange={(v) => setCfg({ cantidad_min: v ?? 1 })} /><Num etiqueta="Fotos máximas" valor={cfg.cantidad_max} min={1} max={20} onChange={(v) => setCfg({ cantidad_max: v ?? 5 })} /></div>
        <Lista etiqueta="Etiquetas en secuencia (Antes, Detalle, Después)" valor={cfg.etiquetas_secuencia} onChange={(v) => setCfg({ etiquetas_secuencia: v })} />
        <p className="text-xs text-slate-500">Calidad mínima (vacío = default global del superadmin)</p>
        <div className="grid grid-cols-2 gap-2">
          <Num etiqueta="Tamaño mínimo (KB)" valor={cfg.calidad?.tamano_minimo_kb} min={0} onChange={(v) => setCfg({ calidad: { ...cfg.calidad!, tamano_minimo_kb: v } })} />
          <Num etiqueta="Compresión máxima (%)" valor={cfg.calidad?.compresion_maxima_pct} min={0} max={100} onChange={(v) => setCfg({ calidad: { ...cfg.calidad!, compresion_maxima_pct: v } })} />
          <Num etiqueta="Ancho mínimo (px)" valor={cfg.calidad?.resolucion_minima_ancho} min={1} onChange={(v) => setCfg({ calidad: { ...cfg.calidad!, resolucion_minima_ancho: v } })} />
          <Num etiqueta="Alto mínimo (px)" valor={cfg.calidad?.resolucion_minima_alto} min={1} onChange={(v) => setCfg({ calidad: { ...cfg.calidad!, resolucion_minima_alto: v } })} />
        </div>
        <Bool etiqueta="Permitir anotación sobre la foto" valor={cfg.permitir_anotacion} onChange={(v) => setCfg({ permitir_anotacion: v })} />
        <Bool etiqueta="Vista previa con confirmación de calidad" valor={cfg.vista_previa_confirmacion} onChange={(v) => setCfg({ vista_previa_confirmacion: v })} />
      </>}
      {t === 'firma' && <><Bool etiqueta="Modo pantalla completa" valor={cfg.pantalla_completa} onChange={(v) => setCfg({ pantalla_completa: v })} /><CampoUI etiqueta="Texto de conformidad" name="texto_conformidad" value={cfg.texto_conformidad ?? ''} onChange={(e) => setCfg({ texto_conformidad: e.target.value || null })} /><p className="text-xs text-slate-500">La firma es obligatoria por definición y no acepta lienzo vacío.</p></>}
      {t === 'dibujo' && <>
        <Sel etiqueta="Imagen de referencia" valor={cfg.imagen_referencia?.tipo} onChange={(v) => setCfg({ imagen_referencia: { tipo: v, valor: v === 'ninguna' ? null : cfg.imagen_referencia?.valor ?? (v === 'campo_fotografia' ? fotos[0]?.clave ?? null : '') } })} opciones={[['ninguna', 'Ninguna'], ['url', 'Plano o esquema (URL)'], ['campo_fotografia', 'Foto tomada en este formulario']]} />
        {cfg.imagen_referencia?.tipo === 'url' && <CampoUI etiqueta="URL de la imagen" name="ref_url" value={cfg.imagen_referencia.valor ?? ''} onChange={(e) => setCfg({ imagen_referencia: { tipo: 'url', valor: e.target.value } })} />}
        {cfg.imagen_referencia?.tipo === 'campo_fotografia' && <Sel etiqueta="Campo de fotografía" valor={cfg.imagen_referencia.valor ?? ''} onChange={(v) => setCfg({ imagen_referencia: { tipo: 'campo_fotografia', valor: v } })} opciones={fotos.map((c) => [c.clave, c.etiqueta])} />}
        <Bool etiqueta="El usuario elige color" valor={cfg.permitir_color} onChange={(v) => setCfg({ permitir_color: v })} /><Bool etiqueta="El usuario elige grosor" valor={cfg.permitir_grosor} onChange={(v) => setCfg({ permitir_grosor: v })} />
      </>}
      {t === 'radio' && <Sel etiqueta="Disposición" valor={cfg.disposicion} onChange={(v) => setCfg({ disposicion: v })} opciones={[['vertical', 'Vertical'], ['horizontal', 'Horizontal']]} />}
      {t === 'boton_grupo' && <><Sel etiqueta="Tamaño" valor={cfg.tamano} onChange={(v) => setCfg({ tamano: v })} opciones={[['grande', 'Grande (uso en campo)'], ['normal', 'Normal']]} /><p className="text-xs text-slate-500">Entre 2 y 5 opciones, cada una con su color.</p></>}
      {t === 'lista_desplegable' && <><Bool etiqueta="Búsqueda integrada" valor={cfg.busqueda} onChange={(v) => setCfg({ busqueda: v })} /><Sel etiqueta="Selección" valor={cfg.seleccion} onChange={(v) => setCfg({ seleccion: v })} opciones={[['unica', 'Única'], ['multiple', 'Múltiple']]} /><Bool etiqueta="Disponible offline (se descarga el catálogo)" valor={cfg.disponible_offline} onChange={(v) => setCfg({ disponible_offline: v })} /></>}
      {t === 'concatenacion' && <>
        <p className="text-xs text-slate-500">Partes en orden: texto fijo o valor de otro campo.</p>
        {(cfg.partes ?? []).map((p, i) => (
          <div key={i} className="flex items-center gap-1">
            <select aria-label={`Parte ${i + 1} tipo`} value={p.tipo} onChange={(e) => setCfg({ partes: cfg.partes!.map((x, j) => (j === i ? { tipo: e.target.value as 'texto' | 'campo', valor: '' } : x)) })} className="rounded border px-1 py-1 text-xs"><option value="texto">Texto</option><option value="campo">Campo</option></select>
            {p.tipo === 'texto'
              ? <input aria-label={`Parte ${i + 1} valor`} value={p.valor} onChange={(e) => setCfg({ partes: cfg.partes!.map((x, j) => (j === i ? { ...x, valor: e.target.value } : x)) })} className="flex-1 rounded border px-2 py-1 text-xs" />
              : <select aria-label={`Parte ${i + 1} campo`} value={p.valor} onChange={(e) => setCfg({ partes: cfg.partes!.map((x, j) => (j === i ? { ...x, valor: e.target.value } : x)) })} className="flex-1 rounded border px-1 py-1 text-xs"><option value="">Elige…</option>{otros.map((c) => <option key={c.clave} value={c.clave}>{c.etiqueta}</option>)}</select>}
            <button type="button" className="text-xs text-red-700" onClick={() => setCfg({ partes: cfg.partes!.filter((_, j) => j !== i) })}>✕</button>
          </div>
        ))}
        <button type="button" className="text-xs text-primario underline" onClick={() => setCfg({ partes: [...(cfg.partes ?? []), { tipo: 'texto', valor: '' }] })}>+ parte</button>
        <CampoUI etiqueta="Separador" name="separador" value={cfg.separador ?? ''} onChange={(e) => setCfg({ separador: e.target.value })} /><Bool etiqueta="Mayúsculas" valor={cfg.mayusculas} onChange={(v) => setCfg({ mayusculas: v })} />
      </>}
      {t === 'archivo' && <><Marcas etiqueta="Tipos permitidos" valor={cfg.tipos_permitidos} onChange={(v) => setCfg({ tipos_permitidos: v })} opciones={[['pdf', 'PDF'], ['imagen', 'Imágenes'], ['hoja_calculo', 'Hojas de cálculo'], ['documento', 'Documentos'], ['cualquiera', 'Cualquiera']]} /><div className="grid grid-cols-2 gap-2"><Num etiqueta="Tamaño máximo (MB)" valor={cfg.tamano_maximo_mb} min={1} max={100} onChange={(v) => setCfg({ tamano_maximo_mb: v ?? 10 })} /><Num etiqueta="Cantidad máxima" valor={cfg.cantidad_max} min={1} max={20} onChange={(v) => setCfg({ cantidad_max: v ?? 3 })} /></div><Bool etiqueta="Permitir anotación sobre imágenes" valor={cfg.permitir_anotacion_imagen} onChange={(v) => setCfg({ permitir_anotacion_imagen: v })} /></>}
      {t === 'escaner' && <><Marcas etiqueta="Formatos" valor={cfg.formatos} onChange={(v) => setCfg({ formatos: v })} opciones={[['qr', 'QR'], ['ean', 'EAN'], ['code128', 'Code 128'], ['datamatrix', 'DataMatrix']]} /><Bool etiqueta="Precargar contexto del equipo escaneado" valor={cfg.precargar_equipo} onChange={(v) => setCfg({ precargar_equipo: v })} /><Bool etiqueta="Permitir captura manual" valor={cfg.permitir_captura_manual} onChange={(v) => setCfg({ permitir_captura_manual: v })} /></>}
      {t === 'etiqueta_info' && <>
        <label className="block"><span className="mb-1 block font-medium text-slate-700">Contenido (**negritas**, listas con -)</span><textarea aria-label="Contenido" rows={4} value={cfg.contenido ?? ''} onChange={(e) => setCfg({ contenido: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" /></label>
        <Sel etiqueta="Icono" valor={cfg.icono} onChange={(v) => setCfg({ icono: v })} opciones={[['ninguno', 'Ninguno'], ['info', 'Información'], ['advertencia', 'Advertencia'], ['peligro', 'Peligro']]} />
        <CampoUI etiqueta="Enlace (URL)" name="enlace_url" value={cfg.enlace?.url ?? ''} onChange={(e) => setCfg({ enlace: e.target.value ? { url: e.target.value, texto: cfg.enlace?.texto ?? 'Ver documento' } : null })} />
        {cfg.enlace && <CampoUI etiqueta="Texto del enlace" name="enlace_texto" value={cfg.enlace.texto} onChange={(e) => setCfg({ enlace: { ...cfg.enlace!, texto: e.target.value } })} />}
      </>}
      {t === 'audio' && <><Num etiqueta="Duración máxima (segundos)" valor={cfg.duracion_maxima_seg} min={5} max={900} onChange={(v) => setCfg({ duracion_maxima_seg: v ?? 120 })} /><Bool etiqueta="Transcripción automática (Fase 2)" valor={cfg.transcripcion} onChange={(v) => setCfg({ transcripcion: v })} /></>}
      {t === 'fecha_hora' && <>
        <Sel etiqueta="Modo" valor={cfg.modo} onChange={(v) => setCfg({ modo: v })} opciones={[['fecha', 'Solo fecha'], ['hora', 'Solo hora'], ['ambos', 'Fecha y hora']]} />
        <div className="grid grid-cols-2 gap-2"><CampoUI etiqueta="Fecha mínima (ISO o hoy±N)" name="fecha_minima" value={cfg.fecha_minima ?? ''} onChange={(e) => setCfg({ fecha_minima: e.target.value || null })} /><CampoUI etiqueta="Fecha máxima" name="fecha_maxima" value={cfg.fecha_maxima ?? ''} onChange={(e) => setCfg({ fecha_maxima: e.target.value || null })} /></div>
        <div className="grid grid-cols-2 gap-2"><Num etiqueta="Intervalo de minutos" valor={cfg.intervalo_minutos} min={1} max={60} onChange={(v) => setCfg({ intervalo_minutos: v ?? 1 })} /><Num etiqueta="Por defecto: hoy + N días" valor={cfg.defecto_hoy_mas_dias} onChange={(v) => setCfg({ defecto_hoy_mas_dias: v })} /></div>
        <Sel etiqueta="Vínculo inicio/fin" valor={cfg.vinculo?.rol ?? ''} onChange={(v) => setCfg({ vinculo: v ? { rol: v as 'inicio' | 'fin', campo_par: cfg.vinculo?.campo_par ?? '' } : null })} opciones={[['', 'Sin vínculo'], ['inicio', 'Este es el inicio'], ['fin', 'Este es el fin (no anterior al inicio)']]} />
        {cfg.vinculo && <Sel etiqueta="Campo par" valor={cfg.vinculo.campo_par} onChange={(v) => setCfg({ vinculo: { ...cfg.vinculo!, campo_par: v } })} opciones={[['', 'Elige…'], ...otros.filter((c) => c.tipo === 'fecha_hora').map((c) => [c.clave, c.etiqueta] as [string, string])]} />}
      </>}
      {t === 'sello_fecha_hora' && <Sel etiqueta="Momento de captura (trigger)" valor={cfg.trigger} onChange={(v) => setCfg({ trigger: v })} opciones={[['al_abrir', 'Al abrir el formulario'], ['al_llegar_seccion', 'Al llegar a esta sección'], ['al_enviar', 'Al enviar'], ['por_condicion', 'Al activarse por condición']]} />}
      {t === 'matematicas_tiempo' && <>
        {(['inicio', 'fin'] as const).map((extremo) => (
          <div key={extremo} className="rounded border border-slate-200 p-2">
            <p className="text-xs font-medium">{extremo === 'inicio' ? 'Inicio' : 'Fin'}</p>
            <Sel etiqueta="Fuente" valor={cfg[extremo]?.origen} onChange={(v) => setCfg({ [extremo]: { origen: v, valor: v === 'sistema' ? 'ahora' : fechas[0]?.clave ?? '' } })} opciones={[['campo', 'Campo llenado por el usuario'], ['sistema', 'Timestamp del sistema']]} />
            {cfg[extremo]?.origen === 'campo'
              ? <Sel etiqueta="Campo" valor={cfg[extremo]?.valor} onChange={(v) => setCfg({ [extremo]: { origen: 'campo', valor: v } })} opciones={[['', 'Elige…'], ...fechas.map((c) => [c.clave, c.etiqueta] as [string, string])]} />
              : <Sel etiqueta="Evento del sistema" valor={cfg[extremo]?.valor} onChange={(v) => setCfg({ [extremo]: { origen: 'sistema', valor: v } })} opciones={[['ahora', 'Ahora (al enviar)'], ['captura_folio', 'Captura del folio'], ['asignacion', 'Asignación'], ['autorizacion', 'Autorización'], ['fecha_programada', 'Fecha programada del preventivo']]} />}
          </div>
        ))}
        <Sel etiqueta="Unidad del resultado" valor={cfg.unidad} onChange={(v) => setCfg({ unidad: v })} opciones={[['minutos', 'Minutos'], ['horas', 'Horas'], ['dias', 'Días'], ['compuesto', 'Compuesto (2h 35min)']]} />
      </>}
      {t === 'slider' && <>
        <div className="grid grid-cols-3 gap-2"><Num etiqueta="Mínimo" valor={cfg.minimo} onChange={(v) => setCfg({ minimo: v ?? 0 })} /><Num etiqueta="Máximo" valor={cfg.maximo} onChange={(v) => setCfg({ maximo: v ?? 10 })} /><Num etiqueta="Incremento" valor={cfg.incremento} step={0.1} onChange={(v) => setCfg({ incremento: v ?? 1 })} /></div>
        <div className="grid grid-cols-2 gap-2"><CampoUI etiqueta="Etiqueta mínimo" name="etiqueta_min" value={cfg.etiqueta_min ?? ''} onChange={(e) => setCfg({ etiqueta_min: e.target.value || null })} /><CampoUI etiqueta="Etiqueta máximo" name="etiqueta_max" value={cfg.etiqueta_max ?? ''} onChange={(e) => setCfg({ etiqueta_max: e.target.value || null })} /></div>
        <Bool etiqueta="Modo rango (dos puntos)" valor={cfg.modo_rango} onChange={(v) => setCfg({ modo_rango: v })} />
      </>}
      {t === 'encuesta_satisfaccion' && <>
        <Sel etiqueta="Modalidad" valor={cfg.modalidad} onChange={(v) => setCfg({ modalidad: v, escala_max: v === 'numerica' ? 10 : 5 })} opciones={[['estrellas', 'Estrellas (1–5)'], ['numerica', 'Numérica (1–10)'], ['emojis', 'Emojis']]} />
        {cfg.modalidad === 'emojis' && <Sel etiqueta="Escala" valor={String(cfg.escala_max)} onChange={(v) => setCfg({ escala_max: Number(v) })} opciones={[['3', '1–3'], ['5', '1–5']]} />}
        <div className="grid grid-cols-2 gap-2"><CampoUI etiqueta="Etiqueta mínimo" name="enc_min" value={cfg.etiqueta_min ?? ''} onChange={(e) => setCfg({ etiqueta_min: e.target.value || null })} /><CampoUI etiqueta="Etiqueta máximo" name="enc_max" value={cfg.etiqueta_max ?? ''} onChange={(e) => setCfg({ etiqueta_max: e.target.value || null })} /></div>
        <Num etiqueta="Umbral de calificación baja (dispara condiciones)" valor={cfg.umbral_bajo} min={1} onChange={(v) => setCfg({ umbral_bajo: v })} />
      </>}
      {t === 'geolocalizacion' && <><Num etiqueta="Radio de ajuste manual (m)" valor={cfg.radio_ajuste_m} min={0} max={2000} onChange={(v) => setCfg({ radio_ajuste_m: v ?? 50 })} /><Num etiqueta="Geofencing: distancia máxima a la UN (m)" valor={cfg.geofencing_radio_m} min={10} max={20000} onChange={(v) => setCfg({ geofencing_radio_m: v ?? 300 })} /><Bool etiqueta="Alertar si queda fuera de la UN" valor={cfg.alertar_fuera_un} onChange={(v) => setCfg({ alertar_fuera_un: v })} /></>}
    </div>
  )
}

function EditorPlantillasCombinacion({ valor, onChange }: { valor: { nombre: string; valores: string[]; cantidades: Record<string, number> }[]; onChange: (v: typeof valor) => void }) {
  return (
    <div>
      <p className="text-xs font-medium">Plantillas de combinaciones frecuentes</p>
      {valor.map((p, i) => (
        <div key={i} className="mt-1 flex items-center gap-1">
          <input aria-label={`Plantilla ${i + 1} nombre`} value={p.nombre} onChange={(e) => onChange(valor.map((x, j) => (j === i ? { ...x, nombre: e.target.value } : x)))} className="w-1/3 rounded border px-2 py-1 text-xs" placeholder="Nombre" />
          <input aria-label={`Plantilla ${i + 1} valores`} value={p.valores.join(',')} onChange={(e) => onChange(valor.map((x, j) => (j === i ? { ...x, valores: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) } : x)))} className="flex-1 rounded border px-2 py-1 text-xs" placeholder="valor1,valor2" />
          <button type="button" className="text-xs text-red-700" onClick={() => onChange(valor.filter((_, j) => j !== i))}>✕</button>
        </div>
      ))}
      <button type="button" className="text-xs text-primario underline" onClick={() => onChange([...valor, { nombre: 'Combinación', valores: [], cantidades: {} }])}>+ plantilla</button>
    </div>
  )
}

function EditorFuente({ campo, otros, personalizados, onChange }: { campo: Campo; otros: Campo[]; personalizados: CatalogoPersonalizado[]; onChange: (f: FuenteOpciones) => void }) {
  const f = campo.fuente_opciones ?? { origen: 'fija', opciones: [] }
  const conColor = campo.tipo === 'boton_grupo'
  const conGrupo = campo.tipo === 'seleccion_multiple'
  return (
    <div className="space-y-2 rounded-lg bg-slate-50 p-3" data-testid="editor-fuente">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Fuente de opciones</p>
      {campo.tipo !== 'boton_grupo' && (
        <Sel etiqueta="Origen" valor={f.origen} onChange={(v) => onChange(v === 'fija' ? { origen: 'fija', opciones: [{ valor: 'opcion_1', etiqueta: 'Opción 1' }] } : { origen: 'catalogo', catalogo: 'equipos_tenant', filtro_contexto: true, campo_padre: null })} opciones={[['fija', 'Lista fija'], ['catalogo', 'Catálogo del sistema']]} />
      )}
      {f.origen === 'fija' && (
        <div className="space-y-1">
          {f.opciones.map((o, i) => (
            <div key={i} className="flex items-center gap-1">
              <input aria-label={`Opción ${i + 1} valor`} value={o.valor} onChange={(e) => onChange({ ...f, opciones: f.opciones.map((x, j) => (j === i ? { ...x, valor: e.target.value } : x)) })} className="w-24 rounded border px-2 py-1 text-xs" placeholder="valor" />
              <input aria-label={`Opción ${i + 1} etiqueta`} value={o.etiqueta} onChange={(e) => onChange({ ...f, opciones: f.opciones.map((x, j) => (j === i ? { ...x, etiqueta: e.target.value } : x)) })} className="flex-1 rounded border px-2 py-1 text-xs" placeholder="Etiqueta" />
              {conColor && <input type="color" aria-label={`Opción ${i + 1} color`} value={o.color ?? '#64748b'} onChange={(e) => onChange({ ...f, opciones: f.opciones.map((x, j) => (j === i ? { ...x, color: e.target.value } : x)) })} />}
              {conGrupo && <input aria-label={`Opción ${i + 1} grupo`} value={o.grupo ?? ''} onChange={(e) => onChange({ ...f, opciones: f.opciones.map((x, j) => (j === i ? { ...x, grupo: e.target.value || null } : x)) })} className="w-20 rounded border px-2 py-1 text-xs" placeholder="grupo" />}
              <button type="button" className="text-xs text-red-700" disabled={f.opciones.length <= (conColor ? 2 : 1)} onClick={() => onChange({ ...f, opciones: f.opciones.filter((_, j) => j !== i) })}>✕</button>
            </div>
          ))}
          <button type="button" className="text-xs text-primario underline" disabled={conColor && f.opciones.length >= 5} onClick={() => onChange({ ...f, opciones: [...f.opciones, { valor: `opcion_${f.opciones.length + 1}`, etiqueta: `Opción ${f.opciones.length + 1}`, ...(conColor ? { color: '#1C3D8F' } : {}) }] })}>+ opción</button>
        </div>
      )}
      {f.origen === 'catalogo' && (
        <>
          <Sel etiqueta="Catálogo" valor={f.catalogo} onChange={(v) => onChange({ ...f, catalogo: v, catalogo_personalizado_id: v === 'catalogo_personalizado' ? personalizados[0]?.id ?? null : null })} opciones={CATALOGOS_SISTEMA.map((c) => [c, NOMBRE_CATALOGO[c]])} />
          {f.catalogo === 'catalogo_personalizado' && <Sel etiqueta="Catálogo personalizado" valor={f.catalogo_personalizado_id ?? ''} onChange={(v) => onChange({ ...f, catalogo_personalizado_id: v })} opciones={personalizados.map((c) => [c.id, c.nombre])} />}
          <Bool etiqueta="Filtrar por el contexto del folio (UN, equipo)" valor={f.filtro_contexto} onChange={(v) => onChange({ ...f, filtro_contexto: v })} />
          <Sel etiqueta="Cascada: campo padre que filtra" valor={f.campo_padre ?? ''} onChange={(v) => onChange({ ...f, campo_padre: v || null })} opciones={[['', 'Sin cascada'], ...otros.map((c) => [c.clave, c.etiqueta] as [string, string])]} />
        </>
      )}
    </div>
  )
}

const OPERADORES: [Condicion['operador'], string][] = [['igual', 'es igual a'], ['distinto', 'es distinto de'], ['contiene', 'contiene'], ['vacio', 'está vacío'], ['no_vacio', 'tiene valor'], ['en_rango', 'está en el rango'], ['opcion_seleccionada', 'tiene seleccionada la opción']]

function EditorCondiciones({ campo, otros, onChange }: { campo: Campo; otros: Campo[]; onChange: (c: Condicion[]) => void }) {
  const lista = campo.condiciones ?? []
  const set = (i: number, cambios: Partial<Condicion>) => onChange(lista.map((c, j) => (j === i ? { ...c, ...cambios } : c)))
  return (
    <div className="space-y-2 rounded-lg bg-slate-50 p-3" data-testid="editor-condiciones">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Lógica condicional</p>
      {lista.map((c, i) => {
        const origen = otros.find((o) => o.clave === c.campo_origen)
        const opcionesOrigen = origen?.fuente_opciones?.origen === 'fija' ? origen.fuente_opciones.opciones : null
        return (
          <div key={i} className="space-y-1 rounded border border-slate-200 bg-white p-2 text-xs">
            <div className="flex flex-wrap items-center gap-1">
              <select aria-label={`Condición ${i + 1} acción`} value={c.accion} onChange={(e) => set(i, { accion: e.target.value as Condicion['accion'] })} className="rounded border px-1 py-1"><option value="mostrar">Mostrar</option><option value="ocultar">Ocultar</option></select>
              <span>si</span>
              <select aria-label={`Condición ${i + 1} campo`} value={c.campo_origen} onChange={(e) => set(i, { campo_origen: e.target.value })} className="rounded border px-1 py-1"><option value="">campo…</option>{otros.map((o) => <option key={o.clave} value={o.clave}>{o.etiqueta}</option>)}</select>
              <select aria-label={`Condición ${i + 1} operador`} value={c.operador} onChange={(e) => set(i, { operador: e.target.value as Condicion['operador'], valor: e.target.value === 'en_rango' ? [0, 0] : null })} className="rounded border px-1 py-1">{OPERADORES.map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select>
              {c.operador === 'en_rango' && <><input aria-label={`Condición ${i + 1} mínimo`} type="number" value={Array.isArray(c.valor) ? String(c.valor[0]) : ''} onChange={(e) => set(i, { valor: [Number(e.target.value), Array.isArray(c.valor) ? c.valor[1] : 0] })} className="w-16 rounded border px-1 py-1" /><input aria-label={`Condición ${i + 1} máximo`} type="number" value={Array.isArray(c.valor) ? String(c.valor[1]) : ''} onChange={(e) => set(i, { valor: [Array.isArray(c.valor) ? c.valor[0] : 0, Number(e.target.value)] })} className="w-16 rounded border px-1 py-1" /></>}
              {['igual', 'distinto', 'contiene', 'opcion_seleccionada'].includes(c.operador) && (origen?.tipo === 'si_no'
                ? <select aria-label={`Condición ${i + 1} valor`} value={c.valor === true ? 'true' : c.valor === false ? 'false' : ''} onChange={(e) => set(i, { valor: e.target.value === 'true' })} className="rounded border px-1 py-1"><option value="">valor…</option><option value="true">{origen.config.etiqueta_si ?? 'Sí'}</option><option value="false">{origen.config.etiqueta_no ?? 'No'}</option></select>
                : opcionesOrigen && c.operador !== 'contiene'
                  ? <select aria-label={`Condición ${i + 1} valor`} value={String(c.valor ?? '')} onChange={(e) => set(i, { valor: e.target.value })} className="rounded border px-1 py-1"><option value="">opción…</option>{opcionesOrigen.map((o) => <option key={o.valor} value={o.valor}>{o.etiqueta}</option>)}</select>
                  : <input aria-label={`Condición ${i + 1} valor`} value={typeof c.valor === 'string' || typeof c.valor === 'number' ? String(c.valor) : ''} onChange={(e) => set(i, { valor: e.target.value })} className="w-28 rounded border px-2 py-1" placeholder="valor" />)}
              <button type="button" className="text-red-700" onClick={() => onChange(lista.filter((_, j) => j !== i))}>✕</button>
            </div>
          </div>
        )
      })}
      <button type="button" className="text-xs text-primario underline" onClick={() => onChange([...lista, { campo_origen: otros[0]?.clave ?? '', operador: 'igual', valor: '', accion: 'mostrar' }])}>+ condición</button>
      {lista.length > 0 && <p className="text-[10px] text-slate-500">Se evalúan en orden; la última que se cumple decide. Un campo oculto no es obligatorio ni se valida.</p>}
    </div>
  )
}
