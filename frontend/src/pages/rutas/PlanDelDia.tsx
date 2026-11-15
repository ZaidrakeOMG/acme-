/** Plan de rutas del día (§6.8.2, §4.1). F2-06.
 *
 * Tres vistas: el **plan** (una ruta por técnico, con la hora de cada parada, su holgura de SLA y su criticidad),
 * las **propuestas** de reasignación automática por decidir, y la **configuración** del optimizador, que solo ve
 * el Admin prestador porque sus pesos cambian las rutas de todos sus técnicos.
 *
 * El plan nace en borrador y **no toca la operación hasta que se publica**: eso se dice en la pantalla, porque un
 * despachador que cree que ya asignó y no publicó deja a sus técnicos sin folios.
 */
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'
import { Aviso, Boton, Campo, Encabezado, Insignia, Modal, Selector, Tabla, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { mensajeDeError } from '../../services/api'
import {
  aceptarPropuesta, calcular, cerrar, configuracion, crearMercado, guardarConfiguracion, guardarTiempoServicio,
  mercados as pedirMercados, moverParada, planDelDia, propuestasPendientes, publicar, recalcular,
  rechazarPropuesta, simular, sugerirTiempos, tiemposServicio, trazos as pedirTrazos,
} from '../../services/rutas'
import type {
  ConfiguracionRutas, Mercado, PesosRutas, PlanDetalle, Propuesta, TiempoServicio, TrazoRuta,
} from '../../types/rutas'
import {
  EXPLICACION_PESOS, NOMBRE_DISPARADOR, NOMBRE_ESTADO_PLAN, NOMBRE_MODO, NOMBRE_PESO, NOMBRE_PROVEEDOR,
  ROLES_CALCULAN, ROLES_CONFIGURAN, hora, textoHolgura,
} from '../../types/rutas'
import { MapaRutas } from './MapaRutas'

type Vista = 'plan' | 'propuestas' | 'configuracion'

const TONO_CRITICIDAD: Record<string, 'alerta' | 'acento' | 'neutro' | 'ok'> = {
  A: 'alerta', B: 'acento', C: 'neutro', D: 'ok',
}

function hoyISO() {
  return new Date().toISOString().slice(0, 10)
}

export function PlanDelDia() {
  const { usuario } = useAuth()
  const [vista, setVista] = useState<Vista>('plan')
  const [mercados, setMercados] = useState<Mercado[]>([])
  const [mercadoId, setMercadoId] = useState('')
  const [fecha, setFecha] = useState(hoyISO())
  const [detalle, setDetalle] = useState<PlanDetalle | null>(null)
  const [trazos, setTrazos] = useState<TrazoRuta[]>([])
  const [propuestas, setPropuestas] = useState<Propuesta[]>([])
  const [cfg, setCfg] = useState<ConfiguracionRutas | null>(null)
  const [pesos, setPesos] = useState<PesosRutas | null>(null)
  const [tiempos, setTiempos] = useState<TiempoServicio[]>([])
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [cargando, setCargando] = useState(false)
  const [modal, setModal] = useState<'mover' | 'mercado' | 'recalcular' | null>(null)
  const [moviendo, setMoviendo] = useState<{ paradaId: string; folio: string; tecnicoActual: string } | null>(null)
  const [destino, setDestino] = useState('')
  const [nuevoMercado, setNuevoMercado] = useState({ codigo: '', nombre: '' })
  const [simulacion, setSimulacion] = useState<string | null>(null)

  const cargarMercados = useCallback(async () => {
    try {
      const lista = await pedirMercados()
      setMercados(lista)
      setMercadoId((actual) => actual || (lista[0]?.id ?? ''))
    } catch (e) { setError(mensajeDeError(e)) }
  }, [])
  useEffect(() => { void cargarMercados() }, [cargarMercados])

  const cargar = useCallback(async () => {
    if (!mercadoId) return
    setError(null)
    try {
      const d = await planDelDia(mercadoId, fecha)
      setDetalle(d)
      setTrazos(d ? await pedirTrazos(d.plan.id) : [])
      setPropuestas(await propuestasPendientes())
      const c = await configuracion()
      setCfg(c)
      setPesos(c.pesos_json)
      setTiempos(await tiemposServicio())
    } catch (e) { setError(mensajeDeError(e)) }
  }, [mercadoId, fecha])
  useEffect(() => { void cargar() }, [cargar])

  if (!usuario) return null
  const calcula = ROLES_CALCULAN.includes(usuario.rol)
  const configura = ROLES_CONFIGURAN.includes(usuario.rol)
  const pestanas: Vista[] = ['plan', 'propuestas', ...(configura ? (['configuracion'] as Vista[]) : [])]
  const plan = detalle?.plan
  const esBorrador = plan?.estado === 'borrador'

  async function ejecutar(fn: () => Promise<unknown>, texto: string) {
    setError(null)
    setCargando(true)
    try {
      const r = await fn()
      setModal(null)
      setAviso(typeof r === 'string' ? r : texto)
      await cargar()
    } catch (e) { setError(mensajeDeError(e)) } finally { setCargando(false) }
  }

  return (
    <div className="space-y-4">
      <Encabezado
        titulo="Rutas del día"
        descripcion="El optimizador propone el orden de visitas de cada técnico respetando habilidades certificadas, ventanas de horario, SLA, criticidad del activo y la jornada. El plan nace en borrador: no asigna nada hasta que se publica."
        acciones={
          <div className="flex flex-wrap items-end gap-2">
            <div className="flex flex-wrap gap-1">
              {pestanas.map((v) => (
                <button key={v} className={`rounded-lg px-3 py-1.5 text-sm ${vista === v ? 'bg-primario text-white' : 'border border-slate-300'}`}
                  onClick={() => setVista(v)}>
                  {v === 'plan' ? 'Plan del día' : v === 'propuestas' ? `Propuestas${propuestas.length ? ` (${propuestas.length})` : ''}` : 'Configuración'}
                </button>
              ))}
            </div>
            <Selector name="mercado" etiqueta="Mercado" value={mercadoId} onChange={(e) => setMercadoId(e.target.value)}
              opciones={[{ valor: '', texto: mercados.length ? 'Elige un mercado' : 'Sin mercados' },
                         ...mercados.map((m) => ({ valor: m.id, texto: `${m.codigo} · ${m.nombre} (${m.unidades} UN)` }))]} />
            <Campo name="fecha" etiqueta="Fecha" type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} />
            {configura && <Boton variante="secundario" onClick={() => setModal('mercado')}>Nuevo mercado</Boton>}
          </div>
        } />
      {error && <Aviso>{error}</Aviso>}
      {aviso && <Aviso tipo="exito">{aviso}</Aviso>}
      {cargando && <p className="text-sm text-slate-500">Calculando…</p>}

      {vista === 'plan' && (
        <>
          <Tarjeta titulo="Plan del día"
            acciones={calcula && mercadoId && (
              <div className="flex flex-wrap gap-2">
                <Boton onClick={() => void ejecutar(() => calcular(mercadoId, fecha), 'Rutas calculadas en borrador')}>
                  Calcular rutas del día
                </Boton>
                {plan && esBorrador && (
                  <Boton onClick={() => void ejecutar(async () => {
                    const r = await publicar(plan.id)
                    return `Plan publicado: ${r.asignados} folio(s) asignados y ${r.respetados} respetados en ${r.tecnicos} técnico(s)`
                  }, 'Plan publicado')}>Publicar y asignar</Boton>
                )}
                {plan && !esBorrador && plan.estado !== 'cerrado' && (
                  <>
                    <Boton variante="secundario" onClick={() => setModal('recalcular')}>Recalcular</Boton>
                    <Boton variante="secundario" onClick={() => void ejecutar(() => cerrar(plan.id), 'Plan cerrado')}>
                      Cerrar el día
                    </Boton>
                  </>
                )}
              </div>
            )}>
            {!plan ? (
              <p className="text-sm text-slate-600">
                {mercadoId ? 'No hay plan para ese mercado y esa fecha. Calcula las rutas del día.'
                  : 'Elige un mercado para ver su plan.'}
              </p>
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-3">
                  <Insignia tono={esBorrador ? 'acento' : plan.estado === 'cerrado' ? 'neutro' : 'ok'}>
                    {NOMBRE_ESTADO_PLAN[plan.estado]}
                  </Insignia>
                  <span className="text-sm text-slate-700">{`${plan.folios_asignados} folio(s) en ruta`}</span>
                  <span className="text-sm text-slate-700">{`${plan.distancia_total_km.toFixed(1)} km en total`}</span>
                  <span className="text-xs text-slate-500">
                    {`versión ${plan.version} · ${plan.motor} · ${(plan.tiempo_calculo_ms / 1000).toFixed(1)} s de cálculo`}
                  </span>
                </div>
                {esBorrador && (
                  <p className="mt-2 text-sm text-amber-700">
                    Es un borrador: los técnicos todavía no tienen estos folios. Publícalo cuando esté como lo quieres.
                  </p>
                )}
              </>
            )}
          </Tarjeta>

          {detalle && detalle.rutas.length > 0 && (
            <MapaRutas rutas={detalle.rutas} trazos={trazos} />
          )}

          {detalle?.rutas.map((ruta) => (
            <Tarjeta key={ruta.tecnico_id}
              titulo={`${ruta.tecnico} · ${ruta.paradas.length} parada(s)`}
              acciones={<span className="text-xs text-slate-500">{`${ruta.km.toFixed(1)} km · ${Math.round(ruta.minutos / 60)} h de ruta`}</span>}>
              <Tabla
                columnas={[
                  { titulo: '#', celda: (p) => p.orden + 1 },
                  { titulo: 'Folio', celda: (p) => (
                    <Link to={`/folios/${p.folio_id}`} className="text-primario underline">{p.numero_folio}</Link>
                  ) },
                  { titulo: 'Unidad', celda: (p) => `${p.un_codigo} ${p.un_nombre}` },
                  { titulo: 'Llegada', celda: (p) => (
                    <span>{hora(p.llegada_estimada)}
                      {!p.ventana_ok && <Insignia tono="alerta">Fuera de ventana</Insignia>}
                    </span>
                  ) },
                  { titulo: 'Traslado', celda: (p) => `${p.minutos_desde_anterior} min · ${p.km_desde_anterior.toFixed(1)} km` },
                  { titulo: 'SLA', celda: (p) => (
                    <span className={p.sla_ok ? '' : 'text-red-700'}>{textoHolgura(p.holgura_sla_min)}</span>
                  ) },
                  { titulo: 'Criticidad', celda: (p) => p.criticidad
                    ? <Insignia tono={TONO_CRITICIDAD[p.criticidad] ?? 'neutro'}>{p.criticidad}</Insignia>
                    : <span className="text-xs text-slate-400">sin evaluar</span> },
                  { titulo: '', celda: (p) => p.fijo
                    ? <Insignia>En ejecución</Insignia>
                    : (calcula && esBorrador && (
                      <button className="text-xs text-primario underline"
                        onClick={() => { setMoviendo({ paradaId: p.parada_id, folio: p.numero_folio, tecnicoActual: ruta.tecnico_id }); setDestino(''); setSimulacion(null); setModal('mover') }}>
                        Mover
                      </button>
                    )) },
                ]}
                filas={ruta.paradas.map((p) => ({ ...p, id: p.parada_id }))} />
            </Tarjeta>
          ))}

          {plan && plan.sin_asignar.length > 0 && (
            <Tarjeta titulo={`Folios sin asignar (${plan.folios_sin_asignar})`}>
              <p className="mb-2 text-sm text-slate-600">
                Cada uno con su motivo: es lo que hay que resolver a mano (abrir otra jornada, certificar una
                habilidad o mover la ventana de horario).
              </p>
              <Tabla
                columnas={[
                  { titulo: 'Folio', celda: (f) => f.numero_folio || f.folio_id.slice(0, 8) },
                  { titulo: 'Motivo', celda: (f) => f.motivo },
                ]}
                filas={plan.sin_asignar.map((f) => ({ ...f, id: f.folio_id }))} />
            </Tarjeta>
          )}
        </>
      )}

      {vista === 'propuestas' && (
        <Tarjeta titulo="Propuestas de reasignación automática">
          <p className="mb-2 text-sm text-slate-600">
            {cfg?.modo_reasignacion_automatica === 'aplicar_y_avisar'
              ? 'Tu configuración aplica las reasignaciones solas y te avisa. Aquí quedan las que todavía no se aplicaron.'
              : 'Nada cambia hasta que aceptas. Una propuesta vence sola porque describe la operación de ese momento.'}
          </p>
          <Tabla
            columnas={[
              { titulo: 'Motivo', celda: (p) => (
                <span><Insignia>{NOMBRE_DISPARADOR[p.disparador]}</Insignia> {p.motivo}</span>
              ) },
              { titulo: 'Movimientos', celda: (p) => (
                <ul className="space-y-1 text-xs">
                  {p.movimientos.map((m) => (
                    <li key={m.folio_id}>{`${m.numero_folio}: ${m.de_tecnico_id ? 'cambia de técnico' : 'sin asignar'} → llega ${hora(m.llegada_estimada)}`}</li>
                  ))}
                </ul>
              ) },
              { titulo: 'Vence', celda: (p) => hora(p.vence_at) },
              { titulo: 'Cálculo', celda: (p) => `${(p.tiempo_calculo_ms / 1000).toFixed(1)} s` },
              { titulo: '', celda: (p) => calcula && (
                <div className="flex gap-2">
                  <Boton onClick={() => void ejecutar(async () => {
                    const r = await aceptarPropuesta(p.id)
                    return `Propuesta aplicada: ${r.aplicados} folio(s) movidos`
                  }, 'Propuesta aplicada')}>Aceptar</Boton>
                  <Boton variante="secundario" onClick={() => void ejecutar(
                    () => rechazarPropuesta(p.id, 'El despachador prefiere la ruta actual'), 'Propuesta rechazada')}>
                    Rechazar
                  </Boton>
                </div>
              ) },
            ]}
            filas={propuestas}
            vacio="No hay propuestas por decidir" />
        </Tarjeta>
      )}

      {vista === 'configuracion' && cfg && pesos && (
        <div className="space-y-4">
          <Tarjeta titulo="Pesos de la función objetivo">
            <p className="mb-3 text-sm text-slate-600">
              Cada peso dice «cuántos minutos de ruta vale la pena gastar para evitar esto». Súbelo para que importe
              más. El de folio sin asignar es el más alto a propósito.
            </p>
            <div className="space-y-3">
              {(Object.keys(pesos) as (keyof PesosRutas)[]).map((k) => (
                <div key={k} className="grid gap-1 sm:grid-cols-[14rem_1fr] sm:items-center">
                  <Campo name={`peso-${k}`} etiqueta={NOMBRE_PESO[k] ?? k} type="number" min={0} max={1000000}
                    value={String(pesos[k])} onChange={(e) => setPesos({ ...pesos, [k]: Number(e.target.value) })} />
                  <p className="text-xs text-slate-600">{EXPLICACION_PESOS[k]}</p>
                </div>
              ))}
            </div>
            <div className="mt-3 flex gap-2">
              <Boton onClick={() => void ejecutar(() => guardarConfiguracion({ pesos_json: pesos }), 'Pesos guardados')}>
                Guardar los pesos
              </Boton>
              <Boton variante="secundario" onClick={() => setPesos(cfg.pesos_json)}>Deshacer</Boton>
            </div>
          </Tarjeta>

          <Tarjeta titulo="Jornada, velocidades y desvío">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <Campo name="duracion" etiqueta="Jornada (minutos)" type="number" min={60} max={1440}
                defaultValue={String(cfg.duracion_jornada_min)}
                onBlur={(e) => void ejecutar(() => guardarConfiguracion({ duracion_jornada_min: Number(e.target.value) }), 'Jornada guardada')} />
              <Campo name="servicio" etiqueta="Tiempo de servicio por defecto (min)" type="number" min={1} max={1440}
                defaultValue={String(cfg.tiempo_servicio_default_min)}
                onBlur={(e) => void ejecutar(() => guardarConfiguracion({ tiempo_servicio_default_min: Number(e.target.value) }), 'Tiempo de servicio guardado')} />
              <Campo name="sinuosidad" etiqueta="Factor de sinuosidad" type="number" step="0.1" min={1} max={3}
                defaultValue={String(cfg.factor_sinuosidad)}
                onBlur={(e) => void ejecutar(() => guardarConfiguracion({ factor_sinuosidad: e.target.value }), 'Factor guardado')} />
              <Campo name="limite" etiqueta="Límite de cálculo (segundos)" type="number" min={1} max={600}
                defaultValue={String(cfg.segundos_limite_calculo)}
                onBlur={(e) => void ejecutar(() => guardarConfiguracion({ segundos_limite_calculo: Number(e.target.value) }), 'Límite guardado')} />
              <Campo name="desvio_m" etiqueta="Desvío: metros" type="number" min={100} max={10000}
                defaultValue={String(cfg.umbral_desvio_m)}
                onBlur={(e) => void ejecutar(() => guardarConfiguracion({ umbral_desvio_m: Number(e.target.value) }), 'Umbral guardado')} />
              <Campo name="desvio_min" etiqueta="Desvío: minutos" type="number" min={1} max={120}
                defaultValue={String(cfg.umbral_desvio_min)}
                onBlur={(e) => void ejecutar(() => guardarConfiguracion({ umbral_desvio_min: Number(e.target.value) }), 'Umbral guardado')} />
              <Selector name="modo" etiqueta="Reasignación automática" value={cfg.modo_reasignacion_automatica}
                onChange={(e) => void ejecutar(() => guardarConfiguracion({ modo_reasignacion_automatica: e.target.value }), 'Modo guardado')}
                opciones={Object.entries(NOMBRE_MODO).map(([valor, texto]) => ({ valor, texto }))} />
              <Selector name="proveedor" etiqueta="Distancias y tiempos" value={cfg.proveedor_distancias}
                onChange={(e) => void ejecutar(() => guardarConfiguracion({ proveedor_distancias: e.target.value }), 'Proveedor guardado')}
                opciones={Object.entries(NOMBRE_PROVEEDOR).map(([valor, texto]) => ({ valor, texto }))} />
            </div>
            <p className="mt-3 text-xs text-slate-500">
              Velocidad promedio por franja horaria (km/h): {Object.entries(cfg.velocidades_json)
                .map(([f, v]) => `${f} → ${v}`).join(' · ')}. Con el proveedor estimado no hay consulta de tráfico;
              con Google Routes, la distancia y el tiempo salen de la ruta real.
            </p>
          </Tarjeta>

          <Tarjeta titulo="Cuánto dura atender un folio"
            acciones={
              <Boton variante="secundario" onClick={() => void ejecutar(() => sugerirTiempos(6), 'Tiempos sugeridos con el historial')}>
                Sugerir con el historial
              </Boton>
            }>
            <p className="mb-2 text-sm text-slate-600">
              Es el dato que más mueve la calidad de la ruta. ACMA lo puede medir con la mediana de la atención real
              de los últimos meses, descartando los folios que estuvieron esperando más de una jornada.
            </p>
            <Tabla
              columnas={[
                { titulo: 'Tipo de folio', celda: (t) => t.tipo_folio },
                { titulo: 'Tipo de equipo', celda: (t) => t.tipo_equipo ?? 'Todos' },
                { titulo: 'Minutos', celda: (t) => (
                  <Campo name={`t-${t.id}`} etiqueta="" type="number" min={1} max={1440}
                    defaultValue={String(t.minutos_estimados)}
                    onBlur={(e) => void ejecutar(() => guardarTiempoServicio({
                      tipo_folio: t.tipo_folio, tipo_equipo_id: t.tipo_equipo_id,
                      minutos_estimados: Number(e.target.value),
                    }), 'Tiempo de servicio guardado')} />
                ) },
                { titulo: 'Origen', celda: (t) => t.origen === 'historial'
                  ? `medido con ${t.muestras} folio(s)` : t.origen },
              ]}
              filas={tiempos}
              vacio="Sin tiempos de servicio configurados" />
          </Tarjeta>
        </div>
      )}

      <Modal titulo={`Mover ${moviendo?.folio ?? ''}`} abierto={modal === 'mover'} alCerrar={() => setModal(null)}>
        <div className="space-y-3">
          <p className="text-sm text-slate-600">
            Se valida la habilidad certificada igual que al asignar, y el folio entra en la mejor posición de la ruta
            del destino. Puedes ver antes cuánto cuesta el cambio.
          </p>
          <Selector name="destino" etiqueta="Técnico destino" value={destino} onChange={(e) => setDestino(e.target.value)}
            opciones={[{ valor: '', texto: 'Elige un técnico' },
                       ...(detalle?.rutas ?? []).filter((r) => r.tecnico_id !== moviendo?.tecnicoActual)
                         .map((r) => ({ valor: r.tecnico_id, texto: `${r.tecnico} (${r.paradas.length} paradas)` }))]} />
          {simulacion && <Aviso tipo="info">{simulacion}</Aviso>}
          <div className="flex gap-2">
            <Boton variante="secundario" disabled={!destino || !plan || !moviendo}
              onClick={async () => {
                setError(null)
                try {
                  const folio = detalle?.rutas.flatMap((r) => r.paradas)
                    .find((p) => p.parada_id === moviendo?.paradaId)
                  if (!folio || !plan) return
                  const s = await simular(plan.id, [{ folio_id: folio.folio_id, tecnico_destino_id: destino }])
                  setSimulacion(`${s.diferencia_km >= 0 ? '+' : ''}${s.diferencia_km.toFixed(1)} km · `
                    + `${s.despues.fuera_ventana} parada(s) fuera de ventana y ${s.despues.fuera_sla} con el SLA vencido`)
                } catch (e) { setError(mensajeDeError(e)) }
              }}>¿Qué pasa si lo muevo?</Boton>
            <Boton disabled={!destino} onClick={() => void ejecutar(
              () => moverParada(plan!.id, moviendo!.paradaId, destino), 'Parada movida')}>Mover la parada</Boton>
          </div>
        </div>
      </Modal>

      <Modal titulo="Recalcular lo afectado" abierto={modal === 'recalcular'} alCerrar={() => setModal(null)}>
        <div className="space-y-3">
          <p className="text-sm text-slate-600">
            Recalcula solo los folios pendientes y los que quedaron sin técnico, partiendo de dónde está cada uno
            ahora. No toca lo que ya empezó.
          </p>
          <Boton onClick={() => void ejecutar(async () => {
            const p = await recalcular(plan!.id, { disparador: 'manual', motivo: 'Recálculo pedido por el despachador' })
            return p.movimientos.length
              ? `Propuesta con ${p.movimientos.length} movimiento(s): revísala en Propuestas`
              : 'El recálculo no encontró ninguna mejora: la ruta de ahora ya es la buena'
          }, 'Recálculo hecho')}>Recalcular ahora</Boton>
        </div>
      </Modal>

      <Modal titulo="Nuevo mercado" abierto={modal === 'mercado'} alCerrar={() => setModal(null)}>
        <div className="space-y-3">
          <p className="text-sm text-slate-600">
            El mercado agrupa las unidades que se atienden juntas. La ruta del día se calcula por mercado.
          </p>
          <Campo name="codigo" etiqueta="Código" value={nuevoMercado.codigo}
            onChange={(e) => setNuevoMercado({ ...nuevoMercado, codigo: e.target.value.toUpperCase() })} />
          <Campo name="nombre" etiqueta="Nombre" value={nuevoMercado.nombre}
            onChange={(e) => setNuevoMercado({ ...nuevoMercado, nombre: e.target.value })} />
          <p className="text-xs text-slate-500">
            Después hay que asignarle sus unidades de negocio para poder calcular rutas.
          </p>
          <Boton disabled={!nuevoMercado.codigo || !nuevoMercado.nombre}
            onClick={() => void ejecutar(async () => {
              await crearMercado(nuevoMercado)
              await cargarMercados()
            }, 'Mercado creado')}>Crear el mercado</Boton>
        </div>
      </Modal>
    </div>
  )
}
