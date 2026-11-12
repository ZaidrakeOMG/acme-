/** Módulo «Gestión de activos ISO 55000» (§6.9.3, F2-05): el registro de activos con su criticidad, la evaluación
 * masiva por tipo de equipo, las dos matrices de riesgo, la bandeja de revisiones vencidas y acciones atrasadas,
 * la configuración de pesos y escalas (solo Admin empresa) y los cinco reportes de certificación. */
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'
import { MatrizInteractiva } from '../../components/criticidad/MatrizInteractiva'
import { Aviso, Boton, Campo, Encabezado, Insignia, Modal, Selector, Tabla, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { api, mensajeDeError } from '../../services/api'
import {
  cambiarEstadoMitigacion, configuracion as pedirConfiguracion, descargarReporteIso, evaluarMasivo,
  guardarConfiguracion, matriz as pedirMatriz, matrizDeRiesgo, mitigacionesPendientes, plantillasIso,
  registro as pedirRegistro, resumen as pedirResumen,
} from '../../services/criticidad'
import { abrirBlob } from '../../services/minutas'
import type {
  ConfiguracionCriticidad, Dimensiones, FilaRegistro, MatrizCriticidad, MatrizRiesgo,
  MitigacionPendiente, Pesos, PlantillaIso, ResumenCriticidad,
} from '../../types/criticidad'
import {
  DIMENSIONES, ETIQUETA_NIVEL, NIVELES, NOMBRE_CATEGORIA_RIESGO, NOMBRE_DIMENSION, NOMBRE_ESTADO_MITIGACION,
  NOMBRE_IMPLICACION, NOMBRE_TIPO_MITIGACION, ROLES_CONFIGURAN, ROLES_EVALUAN, TONO_NIVEL, categoriaRiesgo,
  sumaPesos,
} from '../../types/criticidad'
import { fecha as fmtFecha } from '../folios/comunes'

type Vista = 'registro' | 'matriz' | 'bandeja' | 'reportes' | 'configuracion'
const TITULO: Record<Vista, string> = {
  registro: 'Registro de activos', matriz: 'Matriz de riesgo', bandeja: 'Pendientes',
  reportes: 'Reportes de certificación', configuracion: 'Configuración',
}

export function Iso55000() {
  const { usuario } = useAuth()
  const [vista, setVista] = useState<Vista>('registro')
  const [registro, setRegistro] = useState<FilaRegistro[]>([])
  const [resumen, setResumen] = useState<ResumenCriticidad | null>(null)
  const [matrizActivos, setMatrizActivos] = useState<MatrizCriticidad | null>(null)
  const [matrizModos, setMatrizModos] = useState<MatrizRiesgo | null>(null)
  const [pendientes, setPendientes] = useState<MitigacionPendiente[]>([])
  const [cfg, setCfg] = useState<ConfiguracionCriticidad | null>(null)
  const [plantillas, setPlantillas] = useState<PlantillaIso[]>([])
  const [tipos, setTipos] = useState<{ id: string; nombre: string }[]>([])
  const [filtroNivel, setFiltroNivel] = useState('')
  const [soloVencidas, setSoloVencidas] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [modal, setModal] = useState<'masiva' | null>(null)
  const [masiva, setMasiva] = useState<{ tipo_equipo_id: string; dimensiones: Dimensiones; solo_sin_evaluar: boolean }>({
    tipo_equipo_id: '', dimensiones: { operacional: 3, seguridad: 3, economico: 3, imagen: 3 }, solo_sin_evaluar: true,
  })
  const [pesos, setPesos] = useState<Pesos | null>(null)
  const [meses, setMeses] = useState('12')

  const cargar = useCallback(async () => {
    try {
      const [r, s, m, mm, p, c, pl] = await Promise.all([
        pedirRegistro({ nivel: filtroNivel || undefined, solo_revision_vencida: soloVencidas || undefined }),
        pedirResumen(), pedirMatriz(), matrizDeRiesgo(), mitigacionesPendientes(), pedirConfiguracion(), plantillasIso(),
      ])
      setRegistro(r); setResumen(s); setMatrizActivos(m); setMatrizModos(mm); setPendientes(p)
      setCfg(c); setPesos(c.pesos_json); setMeses(String(c.meses_revision)); setPlantillas(pl)
    } catch (e) { setError(mensajeDeError(e)) }
  }, [filtroNivel, soloVencidas])
  useEffect(() => { void cargar() }, [cargar])
  useEffect(() => {
    api<{ id: string; nombre: string }[]>('/catalogos/tipos-equipo').then(setTipos).catch(() => undefined)
  }, [])

  if (!usuario) return null
  const evalua = ROLES_EVALUAN.includes(usuario.rol)
  const configura = ROLES_CONFIGURAN.includes(usuario.rol)
  const pestanas: Vista[] = ['registro', 'matriz', 'bandeja', 'reportes', ...(configura ? (['configuracion'] as Vista[]) : [])]

  /** Corre la acción, cierra el modal y recarga. Si la acción devuelve un texto, ese es el aviso: así el
   * recálculo y la evaluación masiva pueden contar su resultado en lugar de un «listo» genérico. */
  async function ejecutar(fn: () => Promise<unknown>, texto: string) {
    setError(null)
    try {
      const r = await fn()
      setModal(null)
      setAviso(typeof r === 'string' ? r : texto)
      await cargar()
    } catch (e) { setError(mensajeDeError(e)) }
  }

  async function bajar(tipo: string, formato: 'pdf' | 'excel') {
    setError(null)
    try { abrirBlob(await descargarReporteIso(tipo, formato), `${tipo}.${formato === 'pdf' ? 'pdf' : 'xlsx'}`) }
    catch (e) { setError(mensajeDeError(e)) }
  }

  const sinPlan = new Set(resumen?.criticos_sin_plan_ids ?? [])

  return (
    <div className="space-y-4">
      <Encabezado
        titulo="Gestión de activos ISO 55000"
        descripcion="Criticidad A/B/C/D calculada como probabilidad × impacto, análisis de modos de falla y acciones de mitigación con su efectividad medida. Es la evidencia que pide una certificación ISO 55000."
        acciones={
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex flex-wrap gap-1">
              {pestanas.map((v) => (
                <button key={v} className={`rounded-lg px-3 py-1.5 text-sm ${vista === v ? 'bg-primario text-white' : 'border border-slate-300'}`}
                  onClick={() => setVista(v)}>{TITULO[v]}</button>
              ))}
            </div>
            {evalua && <Boton onClick={() => setModal('masiva')}>Evaluación masiva</Boton>}
          </div>
        } />
      {error && <Aviso>{error}</Aviso>}
      {aviso && <Aviso tipo="exito">{aviso}</Aviso>}

      {resumen && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Tarjeta titulo="Activos por nivel">
            <div className="flex flex-wrap gap-2">
              {NIVELES.map((n) => (
                <Insignia key={n} tono={TONO_NIVEL[n]}>{`${n} · ${resumen.por_nivel[n] ?? 0}`}</Insignia>
              ))}
            </div>
            <p className="mt-2 text-xs text-slate-500">{`${resumen.total} activo(s) con criticidad documentada`}</p>
          </Tarjeta>
          <Tarjeta titulo="Activos A sin plan">
            <p className="text-2xl font-semibold text-slate-800">{resumen.criticos_sin_plan}</p>
            <p className="text-xs text-slate-500">§6.9.3 pide PM obligatorio con plan definido en los activos críticos.</p>
          </Tarjeta>
          <Tarjeta titulo="Acciones vencidas">
            <p className="text-2xl font-semibold text-slate-800">{resumen.mitigaciones_vencidas}</p>
            <p className="text-xs text-slate-500">Mitigaciones con fecha compromiso pasada y sin implementar.</p>
          </Tarjeta>
          <Tarjeta titulo="Revisiones vencidas">
            <p className="text-2xl font-semibold text-slate-800">{resumen.revisiones_vencidas}</p>
            <p className="text-xs text-slate-500">La clasificación se revisa cada {cfg?.meses_revision ?? 12} meses.</p>
          </Tarjeta>
        </div>
      )}

      {vista === 'registro' && (
        <Tarjeta titulo="Registro de activos con criticidad"
          acciones={
            <div className="flex flex-wrap items-end gap-2">
              <Selector name="nivel" etiqueta="Nivel" value={filtroNivel} onChange={(e) => setFiltroNivel(e.target.value)}
                opciones={[{ valor: '', texto: 'Todos' }, ...NIVELES.map((n) => ({ valor: n, texto: `${n} · ${ETIQUETA_NIVEL[n]}` }))]} />
              <label className="flex items-center gap-2 pb-2 text-sm">
                <input type="checkbox" checked={soloVencidas} onChange={(e) => setSoloVencidas(e.target.checked)} />
                Solo revisión vencida
              </label>
            </div>
          }>
          <Tabla
            columnas={[
              { titulo: 'Activo', celda: (f) => (
                <Link to={`/activos/${f.equipo_id}?vista=criticidad`} className="text-primario underline">
                  {`${f.codigo} · ${f.nombre}`}
                </Link>
              ) },
              { titulo: 'Tipo', celda: (f) => f.tipo_equipo },
              { titulo: 'Unidad', celda: (f) => `${f.un_codigo} ${f.un_nombre}` },
              { titulo: 'Nivel', celda: (f) => <Insignia tono={TONO_NIVEL[f.nivel]}>{`${f.nivel} · ${ETIQUETA_NIVEL[f.nivel]}`}</Insignia> },
              { titulo: 'Índice', celda: (f) => Number(f.indice_criticidad).toFixed(2) },
              { titulo: 'Prob. × impacto', celda: (f) => (
                <span>{`${Number(f.probabilidad).toFixed(2)} × ${Number(f.impacto_ponderado).toFixed(2)}`}
                  {f.probabilidad_estimada && <span className="ml-1 text-xs text-slate-500">(estimada)</span>}
                </span>
              ) },
              { titulo: 'Evaluado', celda: (f) => fmtFecha(f.fecha_evaluacion) },
              { titulo: 'Próxima revisión', celda: (f) => (
                <span>{f.proxima_revision ? fmtFecha(f.proxima_revision) : '—'}
                  {f.revision_vencida && <Insignia tono="alerta">Vencida</Insignia>}
                </span>
              ) },
              { titulo: '', celda: (f) => (
                <span className="space-x-1">
                  {f.origen === 'manual' && <Insignia tono="acento">A mano</Insignia>}
                  {sinPlan.has(f.equipo_id) && <Insignia tono="alerta">Sin plan</Insignia>}
                </span>
              ) },
            ]}
            filas={registro.map((f) => ({ ...f, id: f.equipo_id }))}
            vacio="Todavía no hay activos evaluados" />
        </Tarjeta>
      )}

      {vista === 'matriz' && (
        <div className="space-y-4">
          {matrizActivos && (
            <MatrizInteractiva
              titulo="Activos: probabilidad × impacto"
              descripcion="Cada celda trae los activos que caen ahí. La esquina de arriba a la derecha es la que hay que atender primero."
              etiquetaY="Probabilidad" etiquetaX="Impacto"
              categoriaDe={(x, y) => categoriaRiesgo(y, x)}
              celdas={matrizActivos.celdas.map((c) => ({
                x: c.impacto, y: c.probabilidad, total: c.total,
                elementos: c.equipos.map((e) => ({ id: e.equipo_id, etiqueta: e.codigo, nota: `nivel ${e.nivel}` })),
              }))} />
          )}
          {matrizModos && (
            <MatrizInteractiva
              titulo="Modos de falla: severidad × frecuencia"
              descripcion="El FMEA del parque. Las celdas rojas son los modos de falla que piden acción de mitigación."
              etiquetaY="Severidad" etiquetaX="Frecuencia"
              categoriaDe={(x, y) => categoriaRiesgo(y, x)}
              acciones={
                <div className="flex flex-wrap gap-2">
                  {Object.entries(matrizModos.por_categoria).map(([c, n]) => (
                    <Insignia key={c}>{`${NOMBRE_CATEGORIA_RIESGO[c] ?? c}: ${n}`}</Insignia>
                  ))}
                </div>
              }
              celdas={matrizModos.celdas.map((c) => ({
                x: c.frecuencia, y: c.severidad, total: c.total, categoria: c.categoria,
                elementos: c.modos.map((m) => ({ id: m.id, etiqueta: m.descripcion, nota: `riesgo ${m.nivel_riesgo}` })),
              }))} />
          )}
        </div>
      )}

      {vista === 'bandeja' && (
        <Tarjeta titulo="Acciones de mitigación por implementar">
          <p className="mb-2 text-sm text-slate-600">Lo vencido primero, con los días de retraso. Un riesgo analizado y sin acción sigue siendo un riesgo abierto.</p>
          <Tabla
            columnas={[
              { titulo: 'Acción', celda: (m) => m.accion_mitigacion },
              { titulo: 'Tipo', celda: (m) => NOMBRE_TIPO_MITIGACION[m.tipo] ?? m.tipo },
              { titulo: 'Modo de falla', celda: (m) => `${m.modo_falla} (riesgo ${m.nivel_riesgo})` },
              { titulo: 'Activo', celda: (m) => m.equipo_id ? (
                <Link to={`/activos/${m.equipo_id}?vista=criticidad`} className="text-primario underline">{m.equipo_codigo}</Link>
              ) : <span className="text-xs text-slate-500">genérico del tipo</span> },
              { titulo: 'Compromiso', celda: (m) => (
                <span>{m.fecha_compromiso ? fmtFecha(m.fecha_compromiso) : '—'}
                  {m.vencida && <Insignia tono="alerta">{`${m.dias_vencida} día(s)`}</Insignia>}
                </span>
              ) },
              { titulo: 'Estado', celda: (m) => NOMBRE_ESTADO_MITIGACION[m.estado] ?? m.estado },
              { titulo: '', celda: (m) => (
                <Boton variante="secundario" onClick={() => void ejecutar(
                  () => cambiarEstadoMitigacion(m.id, { estado: 'implementada' }), 'Acción marcada como implementada')}>
                  Marcar implementada
                </Boton>
              ) },
            ]}
            filas={pendientes}
            vacio="Sin acciones pendientes" />
        </Tarjeta>
      )}

      {vista === 'reportes' && (
        <Tarjeta titulo="Reportes de certificación ISO 55000">
          <p className="mb-2 text-sm text-slate-600">Salen con el logo y los colores del prestador y quedan registrados en el historial de reportes.</p>
          <Tabla
            columnas={[
              { titulo: 'Reporte', celda: (p) => p.nombre },
              { titulo: '', celda: (p) => (
                <div className="flex gap-2">
                  <Boton variante="secundario" onClick={() => void bajar(p.tipo, 'pdf')}>PDF</Boton>
                  <Boton variante="secundario" onClick={() => void bajar(p.tipo, 'excel')}>Excel</Boton>
                </div>
              ) },
            ]}
            filas={plantillas.map((p) => ({ ...p, id: p.tipo }))} />
        </Tarjeta>
      )}

      {vista === 'configuracion' && cfg && pesos && (
        <div className="space-y-4">
          <Tarjeta titulo="Pesos de las cuatro dimensiones">
            <p className="mb-3 text-sm text-slate-600">
              Los cuatro pesos tienen que sumar 100 %: si no, el índice deja de significar lo que dice. Los valores
              con los que nace la configuración son los de §6.9.3.
            </p>
            <div className="grid gap-3 sm:grid-cols-4">
              {DIMENSIONES.map((k) => (
                <Campo key={k} name={`peso-${k}`} etiqueta={`${NOMBRE_DIMENSION[k]} (%)`} type="number" min={0} max={100}
                  value={String(pesos[k])} onChange={(e) => setPesos({ ...pesos, [k]: Number(e.target.value) })} />
              ))}
            </div>
            <p className={`mt-2 text-sm ${sumaPesos(pesos) === 100 ? 'text-slate-600' : 'text-red-600'}`}>
              {`Suman ${sumaPesos(pesos)} %`}{sumaPesos(pesos) !== 100 && ' · tienen que sumar 100 % para poder guardar'}
            </p>
            <div className="mt-3 flex gap-2">
              <Boton disabled={sumaPesos(pesos) !== 100}
                onClick={() => void ejecutar(() => guardarConfiguracion({ pesos_json: pesos }), 'Pesos guardados')}>
                Guardar los pesos
              </Boton>
              <Boton variante="secundario" onClick={() => setPesos(cfg.pesos_json)}>Deshacer</Boton>
            </div>
          </Tarjeta>

          <Tarjeta titulo="Escala de probabilidad y rangos de nivel">
            <p className="mb-2 text-sm text-slate-600">
              {`La probabilidad 1–5 sale de las fallas de los últimos ${cfg.escala_probabilidad_json.meses} meses, y se
              estima del tipo de equipo cuando el activo lleva menos de ${cfg.escala_probabilidad_json.minimo_meses_historia} meses en ACMA.`}
            </p>
            <Tabla
              columnas={[
                { titulo: 'Probabilidad', celda: (b) => b.nivel },
                { titulo: 'Fallas en la ventana', celda: (b) => b.texto },
              ]}
              filas={cfg.escala_probabilidad_json.por_fallas.map((b) => ({ ...b, id: String(b.nivel) }))} />
            <Tabla
              columnas={[
                { titulo: 'Nivel', celda: (r) => `${r.nivel} · ${r.etiqueta}` },
                { titulo: 'Índice', celda: (r) => `${r.desde} – ${r.hasta}` },
              ]}
              filas={cfg.rangos_nivel_json.map((r) => ({ ...r, id: r.nivel }))} />
            <div className="mt-3 max-w-xs">
              <Campo name="meses_revision" etiqueta="Revisar la clasificación cada (meses)" type="number" min={1} max={60}
                value={meses} onChange={(e) => setMeses(e.target.value)} />
              <div className="mt-2">
                <Boton onClick={() => void ejecutar(() => guardarConfiguracion({ meses_revision: Number(meses) }),
                  'Periodicidad de revisión guardada')}>Guardar</Boton>
              </div>
            </div>
          </Tarjeta>

          <Tarjeta titulo="Implicaciones por nivel">
            <p className="mb-2 text-sm text-slate-600">
              §6.9.3 dice qué exige cada nivel. ACMA lo aplica como aviso por defecto y como restricción solo si
              usted lo decide: un cálculo nuevo no debería bloquear la operación el primer día.
            </p>
            <Tabla
              columnas={[
                { titulo: 'Implicación', celda: (i) => NOMBRE_IMPLICACION[i.id] ?? i.id },
                { titulo: 'Avisa', celda: (i) => (
                  <input type="checkbox" aria-label={`Avisar: ${NOMBRE_IMPLICACION[i.id] ?? i.id}`} checked={i.alerta}
                    onChange={(e) => void ejecutar(() => guardarConfiguracion({
                      implicaciones_activas_json: {
                        ...cfg.implicaciones_activas_json,
                        [i.id]: { ...cfg.implicaciones_activas_json[i.id], alerta: e.target.checked },
                      },
                    }), 'Implicación actualizada')} />
                ) },
                { titulo: 'Restringe', celda: (i) => (
                  <input type="checkbox" aria-label={`Restringir: ${NOMBRE_IMPLICACION[i.id] ?? i.id}`} checked={i.restriccion}
                    onChange={(e) => void ejecutar(() => guardarConfiguracion({
                      implicaciones_activas_json: {
                        ...cfg.implicaciones_activas_json,
                        [i.id]: { ...cfg.implicaciones_activas_json[i.id], restriccion: e.target.checked },
                      },
                    }), 'Implicación actualizada')} />
                ) },
              ]}
              filas={Object.entries(cfg.implicaciones_activas_json).map(([id, v]) => ({ id, alerta: !!v.alerta, restriccion: !!v.restriccion }))} />
          </Tarjeta>
        </div>
      )}

      <Modal titulo="Evaluación masiva por tipo de equipo" abierto={modal === 'masiva'} alCerrar={() => setModal(null)}>
        <div className="space-y-3">
          <p className="text-sm text-slate-600">
            200 equipos no se evalúan de uno en uno: se asignan las mismas dimensiones a todo un tipo y después se
            ajustan los casos particulares desde la ficha de cada activo.
          </p>
          <Selector name="tipo_equipo_id" etiqueta="Tipo de equipo" value={masiva.tipo_equipo_id}
            onChange={(e) => setMasiva({ ...masiva, tipo_equipo_id: e.target.value })}
            opciones={[{ valor: '', texto: 'Elige un tipo' }, ...tipos.map((t) => ({ valor: t.id, texto: t.nombre }))]} />
          {DIMENSIONES.map((k) => (
            <Selector key={k} name={`masiva-${k}`} etiqueta={`${NOMBRE_DIMENSION[k]} (1–5)`} value={String(masiva.dimensiones[k])}
              onChange={(e) => setMasiva({ ...masiva, dimensiones: { ...masiva.dimensiones, [k]: Number(e.target.value) } })}
              opciones={[1, 2, 3, 4, 5].map((n) => ({ valor: String(n), texto: String(n) }))} />
          ))}
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={masiva.solo_sin_evaluar}
              onChange={(e) => setMasiva({ ...masiva, solo_sin_evaluar: e.target.checked })} />
            Omitir los que ya tienen criticidad
          </label>
          <Boton disabled={!masiva.tipo_equipo_id} onClick={() => void ejecutar(async () => {
            const r = await evaluarMasivo(masiva)
            return `${r.evaluados} evaluado(s), ${r.omitidos} omitido(s): ${NIVELES.map((n) => `${n} ${r.por_nivel[n] ?? 0}`).join(', ')}`
          }, 'Evaluación masiva hecha')}>Evaluar el tipo de equipo</Boton>
        </div>
      </Modal>
    </div>
  )
}
