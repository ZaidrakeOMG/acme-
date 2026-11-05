import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { Aviso, Boton, Campo, Encabezado, Insignia, Tabla, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { mensajeDeError } from '../../services/api'
import { calcularCalificaciones, calificaciones, clasificarFolio, configuracionClasificacion, guardarConfiguracionClasificacion, pendientesClasificacion } from '../../services/minutas'
import type { Calificacion, ClasificacionConfig, OpcionClasificacion, PendienteClasificacion } from '../../types/minutas'
import { OPCIONES_CLASIFICACION } from '../../types/minutas'
import { SeveridadInsignia, fecha as fmtFecha } from '../folios/comunes'

/** Pantalla dedicada de §6.10.5: folios no críticos pendientes de clasificar (cinco opciones, plazo restante) y calificación del período. */
export function Clasificacion() {
  const { usuario } = useAuth()
  const [params] = useSearchParams()
  const [vista, setVista] = useState<'pendientes' | 'calificacion' | 'configuracion'>((params.get('vista') as 'calificacion') ?? 'pendientes')
  const [pendientes, setPendientes] = useState<PendienteClasificacion[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [abierto, setAbierto] = useState<string | null>(null)
  const [opcion, setOpcion] = useState<OpcionClasificacion | null>(null)
  const [fechaTentativa, setFechaTentativa] = useState('')
  const [notas, setNotas] = useState('')

  const cargar = useCallback(async () => { try { setPendientes(await pendientesClasificacion()) } catch (e) { setError(mensajeDeError(e)) } }, [])
  useEffect(() => { void cargar() }, [cargar])

  async function clasificar(p: PendienteClasificacion) {
    if (!opcion) return
    try {
      await clasificarFolio(p.folio.id, opcion, opcion === 'reprogramacion' ? fechaTentativa || null : null, notas)
      setAviso(`Folio ${p.folio.numero_folio} clasificado: ${OPCIONES_CLASIFICACION.find((o) => o.valor === opcion)?.texto}`)
      setAbierto(null)
      setOpcion(null)
      setNotas('')
      await cargar()
    } catch (e) { setError(mensajeDeError(e)) }
  }
  if (!usuario) return null
  const vistas: ('pendientes' | 'calificacion' | 'configuracion')[] = ['pendientes', 'calificacion', ...(usuario.rol === 'admin_empresa' || usuario.rol === 'superadmin' ? ['configuracion' as const] : [])]
  return (
    <div>
      <Encabezado titulo="Folios no críticos" descripcion="Clasifica dentro del plazo los folios no críticos de tus unidades. Si no los clasificas a tiempo no cuenta contra el prestador en el SLA, pero descuenta puntos de tu calificación."
                  acciones={<div className="flex gap-1">{vistas.map((v) => <button key={v} className={`rounded-lg px-3 py-1.5 text-sm ${vista === v ? 'bg-primario text-white' : 'border border-slate-300'}`} onClick={() => setVista(v)}>{{ pendientes: 'Pendientes', calificacion: 'Calificación', configuracion: 'Configuración' }[v]}</button>)}</div>} />
      {error && <div className="mb-3"><Aviso>{error}</Aviso></div>}
      {aviso && <div className="mb-3"><Aviso tipo="exito">{aviso}</Aviso></div>}
      {vista === 'pendientes' && (
        <div className="space-y-3">
          {pendientes && pendientes.length === 0 && <p className="text-sm text-slate-500">No tienes folios pendientes de clasificar.</p>}
          {(pendientes ?? []).map((p) => (
            <article key={p.folio.id} data-testid={`pendiente-${p.folio.numero_folio}`} className={`rounded-xl border bg-white p-4 ${p.vencido ? 'border-red-300' : 'border-slate-200'}`}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <Link to={`/folios/${p.folio.id}`} className="font-mono text-sm font-semibold text-primario underline">{p.folio.numero_folio}</Link>
                  <p className="text-sm text-slate-800">{p.folio.descripcion}</p>
                  <p className="text-xs text-slate-500">{p.folio.un_codigo} · {p.folio.equipo_codigo} {p.folio.equipo_nombre} · {p.folio.tipo_falla} · capturado {fmtFecha(p.folio.capturado_at)}</p>
                  <div className="mt-1 flex gap-1"><SeveridadInsignia severidad={p.folio.severidad} />{p.vencido ? <Insignia tono="alerta">Plazo vencido hace {Math.abs(Math.round(p.horas_restantes))} h</Insignia> : <Insignia tono="acento">Quedan {Math.round(p.horas_restantes)} h</Insignia>}</div>
                </div>
                <Boton variante="secundario" onClick={() => { setAbierto(abierto === p.folio.id ? null : p.folio.id); setOpcion(null) }}>Clasificar</Boton>
              </div>
              {abierto === p.folio.id && (
                <div className="mt-3 rounded-lg border border-primario/30 bg-primario/5 p-3" data-testid="opciones-clasificacion">
                  <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Opciones de clasificación">
                    {OPCIONES_CLASIFICACION.map((o) => (
                      <label key={o.valor} className={`cursor-pointer rounded-lg border bg-white p-2 text-sm ${opcion === o.valor ? 'border-primario' : 'border-slate-200'}`}>
                        <input type="radio" name={`clasif-${p.folio.id}`} className="mr-2" checked={opcion === o.valor} onChange={() => setOpcion(o.valor)} aria-label={o.texto} />
                        <span className="font-medium">{o.texto}</span><span className="block text-xs text-slate-500">{o.efecto}</span>
                      </label>
                    ))}
                  </div>
                  <div className="mt-2 flex flex-wrap items-end gap-2">
                    {opcion === 'reprogramacion' && <Campo etiqueta="Fecha tentativa" type="date" value={fechaTentativa} onChange={(e) => setFechaTentativa(e.target.value)} />}
                    <Campo etiqueta="Notas" value={notas} onChange={(e) => setNotas(e.target.value)} />
                    <Boton disabled={!opcion || (opcion === 'reprogramacion' && !fechaTentativa)} onClick={() => void clasificar(p)}>Confirmar</Boton>
                  </div>
                </div>
              )}
            </article>
          ))}
        </div>
      )}
      {vista === 'calificacion' && <Calificaciones esAdminEmpresa={usuario.rol === 'admin_empresa' || usuario.rol === 'superadmin'} />}
      {vista === 'configuracion' && <Configuracion />}
    </div>
  )
}

function Calificaciones({ esAdminEmpresa }: { esAdminEmpresa: boolean }) {
  const [lista, setLista] = useState<Calificacion[]>([])
  const [error, setError] = useState<string | null>(null)
  const [detalle, setDetalle] = useState<Calificacion | null>(null)
  const cargar = useCallback(() => calificaciones().then(setLista).catch((e) => setError(mensajeDeError(e))), [])
  useEffect(() => { void cargar() }, [cargar])
  return (
    <div>
      {error && <Aviso>{error}</Aviso>}
      {esAdminEmpresa && <div className="mb-3"><Boton variante="secundario" onClick={() => void calcularCalificaciones().then(setLista).catch((e) => setError(mensajeDeError(e)))}>Recalcular el período actual</Boton></div>}
      <div className="rounded-xl border border-slate-200 bg-white p-2">
        <Tabla filas={lista} vacio="Sin calificaciones todavía" columnas={[
          { titulo: 'Período', celda: (c) => c.periodo },
          { titulo: 'Admin UN', celda: (c) => <span>{c.usuario_nombre} <span className="text-xs text-slate-500">{c.un_codigo ?? ''}</span></span> },
          { titulo: 'Calificación', celda: (c) => <Insignia tono={Number(c.calificacion_final) < 70 ? 'alerta' : 'ok'}>{c.calificacion_final} / {c.puntos_total}</Insignia> },
          { titulo: 'Folios', celda: (c) => <span className="text-xs">{c.folios_clasificados_tiempo} a tiempo · {c.folios_tardios} tardíos · {c.folios_sin_clasificar} sin clasificar</span> },
          { titulo: 'Minutas', celda: (c) => <span className="text-xs">{c.minutas_respondidas} respondidas · {c.minutas_tardias} tardías o sin respuesta</span> },
          { titulo: '', celda: (c) => <Boton variante="fantasma" onClick={() => setDetalle(c)}>Eventos</Boton> },
        ]} />
      </div>
      {detalle && (
        <div className="mt-3"><Tarjeta titulo={`Eventos de ${detalle.usuario_nombre} · ${detalle.periodo}`}>
          {detalle.eventos_json.length === 0 ? <p className="text-sm text-slate-500">Sin descuentos en el período.</p> : <ul className="text-sm">{detalle.eventos_json.map((e, i) => <li key={i}>{e.tipo.replace(/_/g, ' ')} · −{e.descuento} puntos{e.horas_retraso !== undefined && ` · ${e.horas_retraso} h de retraso`}</li>)}</ul>}
        </Tarjeta></div>
      )}
    </div>
  )
}

function Configuracion() {
  const [c, setC] = useState<ClasificacionConfig | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  useEffect(() => { configuracionClasificacion().then(setC).catch((e) => setError(mensajeDeError(e))) }, [])
  if (!c) return error ? <Aviso>{error}</Aviso> : null
  const niveles = ['muy_baja', 'baja', 'media', 'alta', 'critica']
  return (
    <Tarjeta titulo="Configuración de la clasificación (Admin empresa)">
      {error && <Aviso>{error}</Aviso>}
      {aviso && <Aviso tipo="exito">{aviso}</Aviso>}
      <p className="mb-2 text-sm text-slate-600">Severidades no críticas (requieren clasificación del Admin UN):</p>
      <div className="mb-3 flex flex-wrap gap-3">{niveles.map((n) => <label key={n} className="flex items-center gap-1 text-sm"><input type="checkbox" checked={c.severidades_no_criticas_json.includes(n)} onChange={(e) => setC({ ...c, severidades_no_criticas_json: e.target.checked ? [...c.severidades_no_criticas_json, n] : c.severidades_no_criticas_json.filter((x) => x !== n) })} /> {n}</label>)}</div>
      <div className="grid gap-3 sm:grid-cols-3">
        <Campo etiqueta="Plazo para clasificar (horas)" type="number" min={1} value={c.plazo_horas} onChange={(e) => setC({ ...c, plazo_horas: Number(e.target.value) })} />
        <Campo etiqueta="Umbral de bajo desempeño (puntos)" type="number" min={0} max={100} value={c.umbral_calificacion} onChange={(e) => setC({ ...c, umbral_calificacion: Number(e.target.value) })} />
        <label className="flex items-end gap-2 pb-2 text-sm"><input type="checkbox" checked={c.admin_empresa_puede_clasificar} onChange={(e) => setC({ ...c, admin_empresa_puede_clasificar: e.target.checked })} /> El Admin empresa también puede clasificar</label>
        <label className="flex items-end gap-2 pb-2 text-sm"><input type="checkbox" checked={c.activa} onChange={(e) => setC({ ...c, activa: e.target.checked })} /> Clasificación activa</label>
      </div>
      <div className="mt-3"><Boton onClick={() => void guardarConfiguracionClasificacion(c).then((x) => { setC(x); setAviso('Configuración guardada') }).catch((e) => setError(mensajeDeError(e)))}>Guardar</Boton></div>
    </Tarjeta>
  )
}
