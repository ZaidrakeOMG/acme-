/** Pestaña «Criticidad y riesgo» de la ficha del activo (§6.9.3, F2-05): el nivel con su color y su texto, el
 * índice con el desglose de cómo se formó, el historial de evaluaciones, los modos de falla con su nivel de riesgo
 * y las acciones de mitigación. La evaluación guiada y el ajuste manual viven aquí porque es donde la persona está
 * viendo el activo. */
import { useCallback, useEffect, useState } from 'react'
import { Aviso, Boton, Campo, Insignia, Modal, Selector, Tabla, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { mensajeDeError } from '../../services/api'
import {
  aceptarSugerencias, ajustarNivel, cambiarEstadoMitigacion, crearMitigacion, crearModo, detalle as pedirDetalle,
  efectividadDe, evaluar, historial as pedirHistorial, mitigacionesDe, modosDeEquipo, recalcular,
  sugerenciasDeModos,
} from '../../services/criticidad'
import type {
  Criticidad, DetalleCriticidad, Dimension, Dimensiones, Efectividad, EvaluacionHistorial, Mitigacion, ModoFalla,
  SugerenciaModo,
} from '../../types/criticidad'
import {
  DIMENSIONES, ETIQUETA_NIVEL, NIVELES, NOMBRE_CATEGORIA_RIESGO, NOMBRE_DIMENSION, NOMBRE_ESTADO_MITIGACION,
  NOMBRE_MOTIVO, NOMBRE_ORIGEN_PROBABILIDAD, NOMBRE_TIPO_MITIGACION, ROLES_CONFIGURAN, ROLES_EVALUAN, ROLES_RIESGO,
  TONO_CATEGORIA, TONO_NIVEL, categoriaRiesgo, impactoPonderado, indiceDe,
} from '../../types/criticidad'
import { fecha as fmtFecha } from '../folios/comunes'

const DIMENSIONES_INICIALES: Dimensiones = { operacional: 3, seguridad: 3, economico: 3, imagen: 3 }

function textoEfectividad(e: Efectividad | Record<string, never>): string {
  const x = e as Efectividad
  if (!x || !x.estado) return 'Sin medir'
  if (x.estado === 'medida') {
    const signo = (x.delta_fallas ?? 0) > 0 ? '−' : '+'
    return `${x.veredicto === 'mejoro' ? 'Mejoró' : x.veredicto === 'empeoro' ? 'Empeoró' : 'Sin cambio'}: ${signo}${Math.abs(x.delta_fallas ?? 0)} falla(s)`
  }
  return x.nota ?? NOMBRE_ESTADO_MITIGACION[x.estado] ?? x.estado
}

export function PestanaCriticidad({ equipoId, equipoCodigo }: { equipoId: string; equipoCodigo: string }) {
  const { usuario } = useAuth()
  const [d, setD] = useState<DetalleCriticidad | null>(null)
  const [hist, setHist] = useState<EvaluacionHistorial[]>([])
  const [modos, setModos] = useState<ModoFalla[]>([])
  const [sugerencias, setSugerencias] = useState<SugerenciaModo[]>([])
  const [mitigaciones, setMitigaciones] = useState<Record<string, Mitigacion[]>>({})
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [modal, setModal] = useState<'evaluar' | 'ajuste' | 'modo' | 'mitigacion' | null>(null)
  const [dims, setDims] = useState<Dimensiones>(DIMENSIONES_INICIALES)
  const [razon, setRazon] = useState('')
  const [nivelManual, setNivelManual] = useState<Criticidad>('A')
  const [modoNuevo, setModoNuevo] = useState({ descripcion_falla: '', causa_probable: '', efecto_operacional: '', severidad: 3, frecuencia_historica: 2, deteccion: '' })
  const [paraMitigar, setParaMitigar] = useState<ModoFalla | null>(null)
  const [mitigacionNueva, setMitigacionNueva] = useState({ accion_mitigacion: '', tipo: 'otro', fecha_compromiso: '' })

  const cargar = useCallback(async () => {
    try {
      const det = await pedirDetalle(equipoId)
      setD(det)
      if (det.evaluado) {
        setHist(await pedirHistorial(equipoId))
        const d0 = Object.fromEntries((det.dimensiones ?? []).map((x) => [x.clave, x.valor])) as Partial<Dimensiones>
        setDims({ ...DIMENSIONES_INICIALES, ...d0 })
      } else if (det.economico_propuesto?.nivel) {
        setDims({ ...DIMENSIONES_INICIALES, economico: det.economico_propuesto.nivel })
      }
      const lista = await modosDeEquipo(equipoId)
      setModos(lista)
      const pares = await Promise.all(lista.map(async (m) => [m.id, await mitigacionesDe(m.id)] as const))
      setMitigaciones(Object.fromEntries(pares))
    } catch (e) { setError(mensajeDeError(e)) }
  }, [equipoId])
  useEffect(() => { void cargar() }, [cargar])

  if (!usuario) return null
  const evalua = ROLES_EVALUAN.includes(usuario.rol)
  const configura = ROLES_CONFIGURAN.includes(usuario.rol)
  const registraRiesgo = ROLES_RIESGO.includes(usuario.rol)
  if (!d) return <p className="text-sm text-slate-500">{error ? <Aviso>{error}</Aviso> : 'Cargando la criticidad del activo…'}</p>

  const pesos = d.pesos
  const impacto = impactoPonderado(dims, pesos)
  const probabilidad = Number(d.probabilidad ?? d.probabilidad_si_se_evalua ?? 0)

  /** Corre la acción, cierra el modal y recarga. Si la acción devuelve un texto, ese es el aviso: así el
   * recálculo cuenta su resultado en lugar de un «listo» genérico. */
  async function ejecutar(fn: () => Promise<unknown>, texto: string) {
    setError(null)
    try {
      const r = await fn()
      setModal(null)
      setAviso(typeof r === 'string' ? r : texto)
      await cargar()
    } catch (e) { setError(mensajeDeError(e)) }
  }

  async function verSugerencias() {
    setError(null)
    try { setSugerencias(await sugerenciasDeModos(equipoId)) } catch (e) { setError(mensajeDeError(e)) }
  }

  async function medir(m: Mitigacion) {
    setError(null)
    try {
      const e = await efectividadDe(m.id)
      setAviso(`${m.accion_mitigacion}: ${e.nota ?? textoEfectividad(e)}`)
    } catch (e) { setError(mensajeDeError(e)) }
  }

  return (
    <div className="space-y-4">
      {error && <Aviso>{error}</Aviso>}
      {aviso && <Aviso tipo="exito">{aviso}</Aviso>}

      <Tarjeta
        titulo="Criticidad del activo"
        acciones={
          <div className="flex flex-wrap gap-2">
            {evalua && <Boton onClick={() => setModal('evaluar')}>{d.evaluado ? 'Reevaluar' : 'Evaluar criticidad'}</Boton>}
            {evalua && d.evaluado && (
              <Boton variante="secundario" onClick={() => void ejecutar(async () => {
                const r = await recalcular(equipoId)
                return r.estado === 'cambio' ? `Cambió de ${r.nivel_anterior} a ${r.nivel}`
                  : r.estado === 'manual_vigente' ? 'El nivel está fijado a mano: el recálculo lo respeta'
                  : `Sin cambio de nivel (${r.nivel ?? '—'})`
              }, 'Recálculo hecho')}>Recalcular</Boton>
            )}
            {configura && d.evaluado && <Boton variante="secundario" onClick={() => setModal('ajuste')}>Ajustar a mano</Boton>}
          </div>
        }>
        {!d.evaluado ? (
          <div className="space-y-2 text-sm text-slate-700">
            <p>Este activo todavía no tiene criticidad evaluada.
              {d.nivel_manual ? ` Su ficha trae ${d.nivel_manual} capturado a mano.` : ''}</p>
            <p className="text-slate-600">
              {`La probabilidad de falla la pone ACMA con el historial (${
                NOMBRE_ORIGEN_PROBABILIDAD[d.probabilidad_origen] ?? d.probabilidad_origen}); las cuatro dimensiones de impacto las evalúa el cliente.`}
            </p>
            {d.economico_propuesto?.texto && (
              <p className="text-slate-600">{`Impacto económico propuesto: nivel ${d.economico_propuesto.nivel} · ${d.economico_propuesto.texto}`}</p>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-3">
              <Insignia tono={TONO_NIVEL[d.nivel as Criticidad]}>{`${d.nivel} · ${d.etiqueta ?? ETIQUETA_NIVEL[d.nivel as Criticidad]}`}</Insignia>
              <span className="text-2xl font-semibold text-slate-800">{Number(d.indice_criticidad).toFixed(2)}</span>
              <span className="text-xs text-slate-500">índice de criticidad (0–100)</span>
              {d.origen === 'manual' && <Insignia tono="acento">Nivel fijado a mano</Insignia>}
              {d.revision_vencida && <Insignia tono="alerta">Revisión vencida</Insignia>}
              {d.probabilidad_estimada && <Insignia>Probabilidad estimada</Insignia>}
            </div>
            <p className="text-sm text-slate-700">{d.implicaciones}</p>
            {d.origen === 'manual' && d.razon_manual && (
              <p className="text-sm text-slate-600">{`Razón del ajuste: ${d.razon_manual}`}</p>
            )}
            <p className="text-sm text-slate-600">
              {`Probabilidad ${Number(d.probabilidad).toFixed(2)} (de ${
                NOMBRE_ORIGEN_PROBABILIDAD[d.probabilidad_origen ?? ''] ?? d.probabilidad_origen}) × impacto ${
                Number(d.impacto_ponderado).toFixed(2)} ÷ 25 × 100 = ${Number(d.indice_criticidad).toFixed(2)}`}
            </p>
            <dl className="grid gap-2 text-sm sm:grid-cols-2">
              <div><dt className="text-slate-500">Evaluado</dt><dd>{fmtFecha(d.fecha_evaluacion)}</dd></div>
              <div><dt className="text-slate-500">Próxima revisión</dt><dd>{d.proxima_revision ? fmtFecha(d.proxima_revision) : '—'}</dd></div>
            </dl>
            <Tabla
              columnas={[
                { titulo: 'Dimensión', celda: (x) => NOMBRE_DIMENSION[x.clave] },
                { titulo: 'Nivel', celda: (x) => `${x.valor} · ${x.texto}` },
                { titulo: 'Peso', celda: (x) => `${x.peso} %` },
                { titulo: 'Aporte al impacto', celda: (x) => Number(x.aporte).toFixed(2) },
              ]}
              filas={(d.dimensiones ?? []).map((x) => ({ ...x, id: x.clave }))} />
          </div>
        )}
      </Tarjeta>

      {d.evaluado && (
        <Tarjeta titulo="Historial de evaluaciones">
          <p className="mb-2 text-xs text-slate-500">Append-only: es la trazabilidad que pide una auditoría ISO 55000.</p>
          <Tabla
            columnas={[
              { titulo: 'Fecha', celda: (h) => fmtFecha(h.timestamp) },
              { titulo: 'Motivo', celda: (h) => NOMBRE_MOTIVO[h.motivo] ?? h.motivo },
              { titulo: 'Nivel', celda: (h) => `${h.nivel_anterior ?? 'sin evaluar'} → ${h.nivel_nuevo}` },
              { titulo: 'Índice', celda: (h) => `${h.indice_anterior ? Number(h.indice_anterior).toFixed(2) : '—'} → ${Number(h.indice_nuevo).toFixed(2)}` },
              { titulo: 'Razón', celda: (h) => h.razon || '—' },
            ]}
            filas={hist}
            vacio="Sin evaluaciones registradas" />
        </Tarjeta>
      )}

      <Tarjeta
        titulo="Modos de falla (FMEA)"
        acciones={registraRiesgo && (
          <div className="flex flex-wrap gap-2">
            <Boton variante="secundario" onClick={() => void verSugerencias()}>Proponer desde el historial</Boton>
            <Boton onClick={() => setModal('modo')}>Registrar modo de falla</Boton>
          </div>
        )}>
        <Tabla
          columnas={[
            { titulo: 'Modo de falla', celda: (m) => (
              <span>{m.descripcion_falla}
                {m.tipo_equipo_id && <span className="ml-1 text-xs text-slate-500">(genérico del tipo de equipo)</span>}
                {m.origen === 'sugerido' && <span className="ml-1 text-xs text-slate-500">· propuesto por el historial</span>}
              </span>
            ) },
            { titulo: 'Causa probable', celda: (m) => m.causa_probable || '—' },
            { titulo: 'Sev × Frec', celda: (m) => `${m.severidad} × ${m.frecuencia_historica}${m.deteccion ? ` × ${m.deteccion}` : ''}` },
            { titulo: 'Riesgo', celda: (m) => (
              <Insignia tono={TONO_CATEGORIA[categoriaRiesgo(m.severidad, m.frecuencia_historica)]}>
                {`${m.nivel_riesgo} · ${NOMBRE_CATEGORIA_RIESGO[categoriaRiesgo(m.severidad, m.frecuencia_historica)]}`}
              </Insignia>
            ) },
            { titulo: 'Fallas 12 m', celda: (m) => m.fallas_12m },
            { titulo: 'Mitigación', celda: (m) => (
              <div className="space-y-1">
                {(mitigaciones[m.id] ?? []).map((x) => (
                  <div key={x.id} className="text-xs">
                    <span className="font-medium">{NOMBRE_TIPO_MITIGACION[x.tipo] ?? x.tipo}</span>{`: ${x.accion_mitigacion} `}
                    <Insignia tono={x.estado === 'implementada' ? 'ok' : x.estado === 'descartada' ? 'neutro' : 'acento'}>
                      {NOMBRE_ESTADO_MITIGACION[x.estado] ?? x.estado}
                    </Insignia>
                    {x.estado === 'implementada' && (
                      <button className="ml-1 underline" onClick={() => void medir(x)}>ver efectividad</button>
                    )}
                    {registraRiesgo && (x.estado === 'propuesta' || x.estado === 'en_proceso') && (
                      <button className="ml-1 underline" onClick={() => void ejecutar(
                        () => cambiarEstadoMitigacion(x.id, { estado: 'implementada' }), 'Acción marcada como implementada')}>
                        marcar implementada
                      </button>
                    )}
                  </div>
                ))}
                {registraRiesgo && (
                  <button className="text-xs text-primario underline" onClick={() => { setParaMitigar(m); setModal('mitigacion') }}>
                    + acción de mitigación
                  </button>
                )}
              </div>
            ) },
          ]}
          filas={modos}
          vacio="Sin modos de falla registrados" />
      </Tarjeta>

      {sugerencias.length > 0 && (
        <Tarjeta titulo="Modos de falla propuestos desde el historial"
          acciones={registraRiesgo && (
            <Boton onClick={() => void ejecutar(async () => {
              await aceptarSugerencias(equipoId, sugerencias.filter((s) => !s.ya_registrado).map((s) => ({
                descripcion_falla: s.descripcion_falla, tipo_falla_id: s.tipo_falla_id, causa_probable: s.causa_probable,
                severidad: s.severidad, frecuencia_historica: s.frecuencia_historica, fallas_12m: s.fallas_12m,
              })))
              setSugerencias([])
            }, 'Modos de falla propuestos aceptados')}>Aceptar los que faltan</Boton>
          )}>
          <Tabla
            columnas={[
              { titulo: 'Modo de falla', celda: (s) => s.descripcion_falla },
              { titulo: 'Causa más frecuente', celda: (s) => s.causa_probable || '—' },
              { titulo: 'Riesgo', celda: (s) => `${s.nivel_riesgo} · ${NOMBRE_CATEGORIA_RIESGO[s.categoria]}` },
              { titulo: 'Nota', celda: (s) => s.nota },
              { titulo: '', celda: (s) => s.ya_registrado ? <Insignia tono="ok">Ya registrado</Insignia> : null },
            ]}
            filas={sugerencias.map((s, i) => ({ ...s, id: `${s.descripcion_falla}-${i}` }))} />
        </Tarjeta>
      )}

      <Modal titulo={`Evaluar la criticidad de ${equipoCodigo}`} abierto={modal === 'evaluar'} alCerrar={() => setModal(null)}>
        <div className="space-y-3">
          <p className="text-sm text-slate-600">
            Cada dimensión va de 1 a 5 (§6.9.3). La probabilidad de falla la pone ACMA con el historial del activo.
          </p>
          {DIMENSIONES.map((k: Dimension) => (
            <Selector key={k} name={`dim-${k}`} etiqueta={`${NOMBRE_DIMENSION[k]} (${pesos[k]} %) · ${d.guia[k].pregunta}`}
              value={String(dims[k])} onChange={(e) => setDims({ ...dims, [k]: Number(e.target.value) })}
              opciones={[1, 2, 3, 4, 5].map((n) => ({ valor: String(n), texto: `${n} · ${d.guia[k].niveles[String(n)]}` }))} />
          ))}
          <p className="text-sm text-slate-700">
            {`Impacto ponderado ${impacto.toFixed(2)}`}
            {probabilidad > 0 && ` · índice estimado ${indiceDe(probabilidad, impacto).toFixed(2)}`}
          </p>
          <Campo name="razon" etiqueta="Razón o nota de la evaluación" value={razon} onChange={(e) => setRazon(e.target.value)} />
          <Boton onClick={() => void ejecutar(() => evaluar(equipoId, dims, razon, d.evaluado ? 'revision_periodica' : 'evaluacion_inicial'),
            'Criticidad evaluada')}>Guardar la evaluación</Boton>
        </div>
      </Modal>

      <Modal titulo="Ajustar el nivel a mano" abierto={modal === 'ajuste'} alCerrar={() => setModal(null)}>
        <div className="space-y-3">
          <p className="text-sm text-slate-600">
            El nivel fijado a mano se conserva hasta la próxima revisión: el recálculo semanal lo respeta. La razón
            es obligatoria porque es lo que lee la auditoría.
          </p>
          <Selector name="nivel" etiqueta="Nivel" value={nivelManual} onChange={(e) => setNivelManual(e.target.value as Criticidad)}
            opciones={NIVELES.map((n) => ({ valor: n, texto: `${n} · ${ETIQUETA_NIVEL[n]}` }))} />
          <Campo name="razon-ajuste" etiqueta="Razón del ajuste" value={razon} onChange={(e) => setRazon(e.target.value)} />
          <Boton onClick={() => void ejecutar(() => ajustarNivel(equipoId, nivelManual, razon), 'Nivel ajustado a mano')}>
            Fijar el nivel
          </Boton>
        </div>
      </Modal>

      <Modal titulo="Registrar un modo de falla" abierto={modal === 'modo'} alCerrar={() => setModal(null)}>
        <div className="space-y-3">
          <Campo name="descripcion_falla" etiqueta="¿Cómo falla?" value={modoNuevo.descripcion_falla}
            onChange={(e) => setModoNuevo({ ...modoNuevo, descripcion_falla: e.target.value })} />
          <Campo name="causa_probable" etiqueta="Causa probable" value={modoNuevo.causa_probable}
            onChange={(e) => setModoNuevo({ ...modoNuevo, causa_probable: e.target.value })} />
          <Campo name="efecto_operacional" etiqueta="Efecto en la operación" value={modoNuevo.efecto_operacional}
            onChange={(e) => setModoNuevo({ ...modoNuevo, efecto_operacional: e.target.value })} />
          <Selector name="severidad" etiqueta="Severidad (1–5)" value={String(modoNuevo.severidad)}
            onChange={(e) => setModoNuevo({ ...modoNuevo, severidad: Number(e.target.value) })}
            opciones={[1, 2, 3, 4, 5].map((n) => ({ valor: String(n), texto: String(n) }))} />
          <Selector name="frecuencia_historica" etiqueta="Frecuencia (1–5)" value={String(modoNuevo.frecuencia_historica)}
            onChange={(e) => setModoNuevo({ ...modoNuevo, frecuencia_historica: Number(e.target.value) })}
            opciones={[1, 2, 3, 4, 5].map((n) => ({ valor: String(n), texto: String(n) }))} />
          <Selector name="deteccion" etiqueta="Detección (opcional, FMEA clásico)" value={modoNuevo.deteccion}
            onChange={(e) => setModoNuevo({ ...modoNuevo, deteccion: e.target.value })}
            opciones={[{ valor: '', texto: 'Sin detección' }, ...[1, 2, 3, 4, 5].map((n) => ({ valor: String(n), texto: String(n) }))]} />
          <p className="text-sm text-slate-700">
            {`Nivel de riesgo ${modoNuevo.severidad * modoNuevo.frecuencia_historica * (Number(modoNuevo.deteccion) || 1)} · ${
              NOMBRE_CATEGORIA_RIESGO[categoriaRiesgo(modoNuevo.severidad, modoNuevo.frecuencia_historica)]}`}
          </p>
          <Boton onClick={() => void ejecutar(() => crearModo({
            equipo_id: equipoId, ...modoNuevo, deteccion: modoNuevo.deteccion ? Number(modoNuevo.deteccion) : null,
          }), 'Modo de falla registrado')}>Guardar el modo de falla</Boton>
        </div>
      </Modal>

      <Modal titulo={`Acción de mitigación para «${paraMitigar?.descripcion_falla ?? ''}»`} abierto={modal === 'mitigacion'}
        alCerrar={() => setModal(null)}>
        <div className="space-y-3">
          <Campo name="accion_mitigacion" etiqueta="¿Qué se va a hacer?" value={mitigacionNueva.accion_mitigacion}
            onChange={(e) => setMitigacionNueva({ ...mitigacionNueva, accion_mitigacion: e.target.value })} />
          <Selector name="tipo" etiqueta="Tipo de acción" value={mitigacionNueva.tipo}
            onChange={(e) => setMitigacionNueva({ ...mitigacionNueva, tipo: e.target.value })}
            opciones={Object.entries(NOMBRE_TIPO_MITIGACION).map(([valor, texto]) => ({ valor, texto }))} />
          <p className="text-xs text-slate-500">
            Las de plan preventivo, capacitación y refacción se vinculan a su plan, curso o artículo desde el módulo
            ISO 55000, donde se pueden elegir de la lista.
          </p>
          <Campo name="fecha_compromiso" etiqueta="Fecha compromiso" type="date" value={mitigacionNueva.fecha_compromiso}
            onChange={(e) => setMitigacionNueva({ ...mitigacionNueva, fecha_compromiso: e.target.value })} />
          <Boton onClick={() => void ejecutar(() => crearMitigacion({
            modo_falla_id: paraMitigar?.id, accion_mitigacion: mitigacionNueva.accion_mitigacion,
            tipo: mitigacionNueva.tipo, fecha_compromiso: mitigacionNueva.fecha_compromiso || null,
          }), 'Acción de mitigación registrada')}>Guardar la acción</Boton>
        </div>
      </Modal>
    </div>
  )
}
