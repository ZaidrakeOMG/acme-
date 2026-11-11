import { useCallback, useEffect, useState } from 'react'
import { Aviso, Boton, Campo, Insignia, Modal, Selector, Tabla, Tarjeta } from '../../components/ui'
import { mensajeDeError } from '../../services/api'
import {
  altaMedidor, cambiosDeMedidor, configurarEstimacion, lecturas, medidoresDeEquipo, registrarCambio, registrarLectura,
  tiposMedidor,
} from '../../services/medidores'
import type { CambioMedidor, Lectura, MedidorEntrada, MedidorEquipo, MetodoMedidor, TipoMedidor } from '../../types/medidores'
import { METODOS, NOMBRE_ESTADO_LECTURA, NOMBRE_METODO, formatoValor } from '../../types/medidores'
import { fecha as fmtFecha } from '../folios/comunes'

const DIAS = ['lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo']

/**
 * Pestaña «Medidores» de la ficha del equipo (§6.9.2): cada medidor con su valor actual, la gráfica de lecturas
 * (las reales y las estimadas diferenciadas, con los valores también en texto para quien no distingue los colores),
 * el próximo mantenimiento por uso con su fecha estimada, y el alta, el reinicio y el reemplazo del medidor.
 */
export function PestanaMedidores({ equipoId, puedeAdministrar }: { equipoId: string; puedeAdministrar: boolean }) {
  const [medidores, setMedidores] = useState<MedidorEquipo[] | null>(null)
  const [tipos, setTipos] = useState<TipoMedidor[]>([])
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [modal, setModal] = useState<'alta' | 'lectura' | 'cambio' | 'estimacion' | null>(null)
  const [activo, setActivo] = useState<MedidorEquipo | null>(null)

  const cargar = useCallback(async () => {
    try {
      setMedidores(await medidoresDeEquipo(equipoId))
      setTipos(await tiposMedidor({ solo_activos: true }))
    } catch (e) { setError(mensajeDeError(e)) }
  }, [equipoId])
  useEffect(() => { void cargar() }, [cargar])

  async function ejecutar(fn: () => Promise<unknown>, texto: string) {
    setError(null)
    try { await fn(); setModal(null); setAviso(texto); await cargar() } catch (e) { setError(mensajeDeError(e)) }
  }

  if (!medidores) return <Tarjeta titulo="Medidores"><p className="text-sm text-slate-500">Cargando los medidores del equipo…</p></Tarjeta>
  const sinMedidor = tipos.filter((t) => !medidores.some((m) => m.tipo_medidor_id === t.id && m.activo))

  return (
    <div className="space-y-4" data-testid="pestana-medidores">
      {error && <Aviso>{error}</Aviso>}
      {aviso && <Aviso tipo="exito">{aviso}</Aviso>}
      {medidores.length === 0 && (
        <Tarjeta titulo="Medidores">
          <p className="text-sm text-slate-600">
            Este equipo no tiene medidores. Con uno, sus planes de mantenimiento pueden dispararse por uso real
            (horas, ciclos, kilómetros, energía o unidades producidas) y no solo por calendario.
          </p>
          {puedeAdministrar && <div className="mt-2"><Boton onClick={() => setModal('alta')}>Agregar medidor</Boton></div>}
        </Tarjeta>
      )}
      {medidores.map((m) => (
        <FichaMedidor key={m.id} medidor={m} puedeAdministrar={puedeAdministrar}
          alRegistrarLectura={() => { setActivo(m); setModal('lectura') }}
          alCambiar={() => { setActivo(m); setModal('cambio') }}
          alEstimar={() => { setActivo(m); setModal('estimacion') }} />
      ))}
      {medidores.length > 0 && puedeAdministrar && sinMedidor.length > 0 && (
        <Boton variante="secundario" onClick={() => setModal('alta')}>Agregar otro medidor</Boton>
      )}

      {modal === 'alta' && (
        <FormAlta tipos={sinMedidor} alCerrar={() => setModal(null)}
          alGuardar={(d) => ejecutar(() => altaMedidor(equipoId, d), 'Medidor dado de alta')} />
      )}
      {modal === 'lectura' && activo && (
        <FormLectura medidor={activo} alCerrar={() => setModal(null)} alGuardar={async (valor) => {
          setError(null)
          try {
            const r = await registrarLectura({ equipo_medidor_id: activo.id, valor })
            setModal(null)
            setAviso(r.anomalia
              ? `La lectura quedó en revisión: ${r.anomalia}`
              : `Lectura registrada: ${formatoValor(r.lectura.valor, activo.decimales, activo.unidad)}`
                + (r.folios_generados.length ? ` · generó ${r.folios_generados.length} folio(s) preventivo(s)` : ''))
            await cargar()
          } catch (e) { setError(mensajeDeError(e)) }
        }} />
      )}
      {modal === 'cambio' && activo && (
        <FormCambio medidor={activo} alCerrar={() => setModal(null)}
          alGuardar={(d) => ejecutar(() => registrarCambio(activo.id, d),
            d.tipo === 'reinicio' ? 'Reinicio registrado: el acumulado del equipo no retrocede' : 'Reemplazo de medidor registrado')} />
      )}
      {modal === 'estimacion' && activo && (
        <FormEstimacion medidor={activo} alCerrar={() => setModal(null)}
          alGuardar={(d) => ejecutar(() => configurarEstimacion(activo.id, d), 'Estimación configurada')} />
      )}
    </div>
  )
}

function FichaMedidor({ medidor, puedeAdministrar, alRegistrarLectura, alCambiar, alEstimar }: {
  medidor: MedidorEquipo
  puedeAdministrar: boolean
  alRegistrarLectura: () => void
  alCambiar: () => void
  alEstimar: () => void
}) {
  const [historial, setHistorial] = useState<Lectura[] | null>(null)
  const [cambios, setCambios] = useState<CambioMedidor[] | null>(null)
  const [verTodo, setVerTodo] = useState(false)
  useEffect(() => {
    void lecturas({ equipo_medidor_id: medidor.id, limite: 60 }).then((l) => setHistorial(l.slice().reverse())).catch(() => setHistorial([]))
    void cambiosDeMedidor(medidor.id).then(setCambios).catch(() => setCambios([]))
  }, [medidor.id])
  const proximos = medidor.proximos_mantenimientos

  return (
    <Tarjeta
      titulo={`${medidor.tipo}${medidor.activo ? '' : ' (dado de baja)'}`}
      acciones={puedeAdministrar && medidor.activo ? (
        <div className="flex flex-wrap gap-2">
          <Boton variante="secundario" onClick={alRegistrarLectura}>Registrar lectura</Boton>
          <Boton variante="secundario" onClick={alCambiar}>Reinicio o reemplazo</Boton>
          <Boton variante="fantasma" onClick={alEstimar}>Estimación</Boton>
        </div>
      ) : undefined}
    >
      <div className="grid gap-4 md:grid-cols-[auto_1fr]">
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm" data-testid={`medidor-${medidor.tipo_medidor_id}`}>
          <dt className="text-slate-500">Marcador</dt><dd className="font-semibold">{formatoValor(medidor.valor_actual, medidor.decimales, medidor.unidad)}</dd>
          <dt className="text-slate-500">Acumulado real</dt><dd>{formatoValor(medidor.valor_acumulado, medidor.decimales, medidor.unidad)}</dd>
          <dt className="text-slate-500">Último mantenimiento</dt><dd>{formatoValor(medidor.valor_ultimo_pm, medidor.decimales, medidor.unidad)}</dd>
          <dt className="text-slate-500">Última lectura</dt><dd>{medidor.fecha_ultima_lectura ? fmtFecha(medidor.fecha_ultima_lectura) : 'sin lecturas'}</dd>
          <dt className="text-slate-500">Se actualiza por</dt><dd>{NOMBRE_METODO[medidor.metodo_actualizacion]}</dd>
          <dt className="text-slate-500">Uso diario</dt><dd>{formatoValor(medidor.incremento_por_dia, 2, medidor.unidad)} <span className="text-xs text-slate-500">({medidor.origen_incremento === 'promedio_real' ? 'promedio real medido' : medidor.origen_incremento === 'configurado' ? 'configurado' : medidor.origen_incremento === 'historial' ? 'promedio del historial' : 'sin datos suficientes'})</span></dd>
          {medidor.numero_serie_medidor && <><dt className="text-slate-500">Serie del medidor</dt><dd>{medidor.numero_serie_medidor}</dd></>}
          {medidor.valor_maximo && <><dt className="text-slate-500">Tope del marcador</dt><dd>{formatoValor(medidor.valor_maximo, medidor.decimales, medidor.unidad)}</dd></>}
        </dl>
        <div>
          <p className="text-xs font-semibold uppercase text-slate-500">Lecturas</p>
          {historial && historial.length > 0 ? (
            <>
              <div className="mt-1 flex items-end gap-0.5" role="img" aria-label={`Lecturas de ${medidor.tipo}`} data-testid={`grafica-${medidor.id}`}>
                {historial.slice(-30).map((l) => {
                  const max = Math.max(...historial.map((x) => Number(x.valor_acumulado)), 1)
                  const estimada = l.metodo === 'estimado'
                  return (
                    <div key={l.id}
                      title={`${fmtFecha(l.timestamp)}: ${formatoValor(l.valor, medidor.decimales, medidor.unidad)} (${NOMBRE_METODO[l.metodo]}${l.estado === 'valida' ? '' : `, ${NOMBRE_ESTADO_LECTURA[l.estado]}`})`}
                      className={`w-3 rounded-t ${l.estado !== 'valida' ? 'bg-red-400' : estimada ? 'border border-dashed border-primario bg-primario/20' : 'bg-primario/70'}`}
                      style={{ height: `${Math.max(4, (Number(l.valor_acumulado) / max) * 72)}px` }} />
                  )
                })}
              </div>
              <p className="mt-1 text-xs text-slate-500">
                <span className="mr-2 inline-block h-2 w-2 rounded bg-primario/70 align-middle" />real ·
                <span className="mx-2 inline-block h-2 w-2 rounded border border-dashed border-primario bg-primario/20 align-middle" />estimada ·
                <span className="mx-2 inline-block h-2 w-2 rounded bg-red-400 align-middle" />en revisión o rechazada
              </p>
              <ul className="mt-1 text-xs text-slate-600" data-testid={`lecturas-${medidor.id}`}>
                {historial.slice(verTodo ? 0 : -5).reverse().map((l) => (
                  <li key={l.id}>
                    {fmtFecha(l.timestamp)} — {formatoValor(l.valor, medidor.decimales, medidor.unidad)} · {NOMBRE_METODO[l.metodo]}
                    {l.estado !== 'valida' && <> · <Insignia tono="alerta">{NOMBRE_ESTADO_LECTURA[l.estado]}</Insignia> {l.motivo}</>}
                  </li>
                ))}
              </ul>
              {historial.length > 5 && <button className="mt-1 text-xs text-primario underline" onClick={() => setVerTodo(!verTodo)}>{verTodo ? 'Ver solo las últimas' : `Ver las ${historial.length} lecturas`}</button>}
            </>
          ) : <p className="mt-1 text-sm text-slate-500">Todavía no hay lecturas de este medidor.</p>}
        </div>
      </div>

      {proximos.length > 0 && (
        <div className="mt-3 rounded-lg border border-primario/30 bg-primario/5 p-3" data-testid={`proximos-${medidor.id}`}>
          <p className="text-xs font-semibold uppercase text-slate-500">Próximo mantenimiento por uso</p>
          <ul className="mt-1 space-y-1 text-sm">
            {proximos.map((p) => (
              <li key={`${p.plan_id}-${p.clave}`}>
                <strong>{p.plan}</strong>: toca a {formatoValor(p.valor_objetivo, medidor.decimales, p.unidad ?? medidor.unidad)}
                {p.faltante !== null && <> · faltan {formatoValor(p.faltante, medidor.decimales, p.unidad ?? medidor.unidad)}</>}
                {p.fecha_estimada
                  ? <> · estimado para el <strong>{p.fecha_estimada}</strong> (± {p.ventana_dias} días)</>
                  : <> · <span className="text-slate-500">{p.motivo}</span></>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {medidor.estimacion && (
        <p className="mt-2 text-xs text-slate-600" data-testid={`estimacion-${medidor.id}`}>
          Estimación {medidor.estimacion.activa ? 'activa' : 'inactiva'}: {formatoValor(medidor.estimacion.incremento_por_dia, 2, medidor.unidad)} por día de operación
          {medidor.estimacion.incremento_real_promedio && <> · el uso real medido es {formatoValor(medidor.estimacion.incremento_real_promedio, 2, medidor.unidad)} por día</>}
          {medidor.estimacion.ultima_estimacion_at && <> · última estimación {fmtFecha(medidor.estimacion.ultima_estimacion_at)}</>}
        </p>
      )}

      {cambios && cambios.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-semibold uppercase text-slate-500">Reinicios y reemplazos</p>
          <Tabla filas={cambios} columnas={[
            { titulo: 'Qué pasó', celda: (c) => (c.tipo === 'reinicio' ? 'El marcador volvió a cero' : 'Se reemplazó el medidor') },
            { titulo: 'Antes', celda: (c) => formatoValor(c.valor_anterior, medidor.decimales, medidor.unidad) },
            { titulo: 'Después', celda: (c) => formatoValor(c.valor_nuevo, medidor.decimales, medidor.unidad) },
            { titulo: 'Acumulado', celda: (c) => formatoValor(c.acumulado_al_cambio, medidor.decimales, medidor.unidad) },
            { titulo: 'Motivo', celda: (c) => <span className="text-xs">{c.motivo}</span> },
            { titulo: 'Cuándo', celda: (c) => fmtFecha(c.timestamp) },
          ]} />
        </div>
      )}
    </Tarjeta>
  )
}

function FormAlta({ tipos, alCerrar, alGuardar }: { tipos: TipoMedidor[]; alCerrar: () => void; alGuardar: (d: MedidorEntrada) => Promise<void> }) {
  const [d, setD] = useState({ tipo_medidor_id: tipos[0]?.id ?? '', valor_inicial: '0', metodo_actualizacion: 'operador' as MetodoMedidor,
                               valor_maximo: '', numero_serie_medidor: '', instalado_en: '' })
  const tipo = tipos.find((t) => t.id === d.tipo_medidor_id)
  return (
    <Modal titulo="Agregar medidor al equipo" abierto alCerrar={alCerrar}>
      <div className="space-y-3" data-testid="form-alta-medidor">
        <Selector etiqueta="Tipo de medidor" value={d.tipo_medidor_id} onChange={(e) => setD({ ...d, tipo_medidor_id: e.target.value })}
          opciones={tipos.map((t) => ({ valor: t.id, texto: `${t.nombre} (${t.unidad})` }))} />
        <Selector etiqueta="Cómo se va a actualizar" value={d.metodo_actualizacion} onChange={(e) => setD({ ...d, metodo_actualizacion: e.target.value as MetodoMedidor })}
          opciones={METODOS.filter((m) => m.valor !== 'estimado' || tipo?.permite_estimacion !== false).map((m) => ({ valor: m.valor, texto: m.texto }))} />
        <p className="text-xs text-slate-600">{METODOS.find((m) => m.valor === d.metodo_actualizacion)?.detalle}</p>
        <div className="grid gap-2 sm:grid-cols-2">
          <Campo etiqueta={`Lectura actual del marcador (${tipo?.unidad ?? ''})`} type="number" value={d.valor_inicial} onChange={(e) => setD({ ...d, valor_inicial: e.target.value })} />
          <Campo etiqueta="Tope del marcador (vacío = no se reinicia)" type="number" value={d.valor_maximo} onChange={(e) => setD({ ...d, valor_maximo: e.target.value })} />
          <Campo etiqueta="Número de serie del medidor" value={d.numero_serie_medidor} onChange={(e) => setD({ ...d, numero_serie_medidor: e.target.value })} />
          <Campo etiqueta="Instalado el" type="date" value={d.instalado_en} onChange={(e) => setD({ ...d, instalado_en: e.target.value })} />
        </div>
        <div className="flex gap-2">
          <Boton disabled={!d.tipo_medidor_id} onClick={() => void alGuardar({
            tipo_medidor_id: d.tipo_medidor_id, valor_inicial: d.valor_inicial || '0', metodo_actualizacion: d.metodo_actualizacion,
            valor_maximo: d.valor_maximo || null, numero_serie_medidor: d.numero_serie_medidor || null, instalado_en: d.instalado_en || null,
          })}>Guardar</Boton>
          <Boton variante="secundario" onClick={alCerrar}>Cancelar</Boton>
        </div>
      </div>
    </Modal>
  )
}

function FormLectura({ medidor, alCerrar, alGuardar }: { medidor: MedidorEquipo; alCerrar: () => void; alGuardar: (valor: string) => Promise<void> }) {
  const [valor, setValor] = useState('')
  return (
    <Modal titulo={`Registrar lectura de ${medidor.tipo}`} abierto alCerrar={alCerrar}>
      <div className="space-y-3" data-testid="form-lectura">
        <p className="text-sm text-slate-600">
          El marcador va en {formatoValor(medidor.valor_actual, medidor.decimales, medidor.unidad)}. Si la lectura
          retrocede o salta más de lo esperado quedará en revisión y no disparará planes hasta que alguien la apruebe.
        </p>
        <Campo etiqueta={`Lectura (${medidor.unidad})`} type="number" value={valor} onChange={(e) => setValor(e.target.value)} />
        <div className="flex gap-2">
          <Boton disabled={valor === ''} onClick={() => void alGuardar(valor)}>Registrar</Boton>
          <Boton variante="secundario" onClick={alCerrar}>Cancelar</Boton>
        </div>
      </div>
    </Modal>
  )
}

function FormCambio({ medidor, alCerrar, alGuardar }: {
  medidor: MedidorEquipo
  alCerrar: () => void
  alGuardar: (d: { tipo: 'reinicio' | 'reemplazo_medidor'; valor_nuevo: string; motivo: string; numero_serie_nuevo?: string | null }) => Promise<void>
}) {
  const [d, setD] = useState({ tipo: 'reinicio' as 'reinicio' | 'reemplazo_medidor', valor_nuevo: '0', motivo: '', numero_serie_nuevo: '' })
  return (
    <Modal titulo="Reinicio del marcador o reemplazo del medidor" abierto alCerrar={alCerrar}>
      <div className="space-y-3" data-testid="form-cambio-medidor">
        <Aviso tipo="info">
          Las horas que el equipo ya trabajó no se pierden: el acumulado real sigue su cuenta y los planes por uso
          siguen midiendo bien. Registra el cambio <strong>antes</strong> de capturar la lectura nueva.
        </Aviso>
        <Selector etiqueta="Qué pasó" value={d.tipo} onChange={(e) => setD({ ...d, tipo: e.target.value as 'reinicio' })}
          opciones={[{ valor: 'reinicio', texto: 'El marcador llegó a su tope y volvió a cero' },
                     { valor: 'reemplazo_medidor', texto: 'Se reemplazó el medidor físico' }]} />
        <div className="grid gap-2 sm:grid-cols-2">
          <Campo etiqueta={`Lectura con la que arranca (${medidor.unidad})`} type="number" value={d.valor_nuevo} onChange={(e) => setD({ ...d, valor_nuevo: e.target.value })} />
          {d.tipo === 'reemplazo_medidor' && <Campo etiqueta="Serie del medidor nuevo" value={d.numero_serie_nuevo} onChange={(e) => setD({ ...d, numero_serie_nuevo: e.target.value })} />}
        </div>
        <Campo etiqueta="Motivo (obligatorio)" value={d.motivo} onChange={(e) => setD({ ...d, motivo: e.target.value })} />
        <div className="flex gap-2">
          <Boton disabled={d.motivo.trim().length < 3} onClick={() => void alGuardar({
            tipo: d.tipo, valor_nuevo: d.valor_nuevo || '0', motivo: d.motivo,
            numero_serie_nuevo: d.tipo === 'reemplazo_medidor' ? (d.numero_serie_nuevo || null) : null,
          })}>Registrar</Boton>
          <Boton variante="secundario" onClick={alCerrar}>Cancelar</Boton>
        </div>
      </div>
    </Modal>
  )
}

function FormEstimacion({ medidor, alCerrar, alGuardar }: { medidor: MedidorEquipo; alCerrar: () => void; alGuardar: (d: Record<string, unknown>) => Promise<void> }) {
  const est = medidor.estimacion
  const [incremento, setIncremento] = useState(est?.incremento_por_dia ?? '')
  const [horas, setHoras] = useState(String(est?.horario_operacion_json?.horas_por_dia ?? 8))
  const [dias, setDias] = useState<string[]>(est?.horario_operacion_json?.dias ?? DIAS.slice(0, 6))
  const [activa, setActiva] = useState(est?.activa ?? false)
  return (
    <Modal titulo={`Estimación de ${medidor.tipo}`} abierto alCerrar={alCerrar}>
      <div className="space-y-3" data-testid="form-estimacion">
        <p className="text-sm text-slate-600">
          Para equipos sin lecturas directas pero con un patrón de uso conocido (§6.9.2). Cada día de operación,
          ACMA suma el incremento configurado y escribe una lectura estimada; la siguiente lectura real la corrige y
          recalcula el uso promedio medido. También es el número con el que se detectan los saltos y se proyecta la
          fecha del próximo mantenimiento.
        </p>
        <div className="grid gap-2 sm:grid-cols-2">
          <Campo etiqueta={`Incremento por día de operación (${medidor.unidad})`} type="number" value={incremento} onChange={(e) => setIncremento(e.target.value)} />
          <Campo etiqueta="Horas de operación por día" type="number" value={horas} onChange={(e) => setHoras(e.target.value)} />
        </div>
        <fieldset>
          <legend className="mb-1 text-sm font-medium text-slate-700">Días de operación</legend>
          <div className="flex flex-wrap gap-2">
            {DIAS.map((dia) => (
              <label key={dia} className="flex items-center gap-1 text-sm capitalize">
                <input type="checkbox" checked={dias.includes(dia)} aria-label={dia}
                  onChange={(e) => setDias(e.target.checked ? [...dias, dia] : dias.filter((x) => x !== dia))} />
                {dia}
              </label>
            ))}
          </div>
        </fieldset>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={activa} onChange={(e) => setActiva(e.target.checked)} />
          Escribir lecturas estimadas todos los días
        </label>
        {activa && medidor.metodo_actualizacion !== 'estimado' && (
          <Aviso tipo="info">Este medidor se actualiza por {NOMBRE_METODO[medidor.metodo_actualizacion]}: con la estimación activa, las lecturas reales corregirán lo estimado.</Aviso>
        )}
        <div className="flex gap-2">
          <Boton onClick={() => void alGuardar({
            incremento_por_dia: incremento || '0', activa,
            horario_operacion_json: { dias, horas_por_dia: Number(horas) || 8 },
          })}>Guardar</Boton>
          <Boton variante="secundario" onClick={alCerrar}>Cancelar</Boton>
        </div>
      </div>
    </Modal>
  )
}
