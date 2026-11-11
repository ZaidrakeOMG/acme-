import { useCallback, useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { Aviso, Boton, Campo, Encabezado, Insignia, Modal, Selector, Tabla, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { mensajeDeError } from '../../services/api'
import { decidirReemplazo, fichaActivo, guardarDatosEconomicos, guardarDepreciacion, recalcularActivo } from '../../services/inventario'
import type { FichaActivo, MetodoDepreciacion } from '../../types/inventario'
import { DESCRIPCION_METODO, NOMBRE_METODO, ROLES_ESCRIBEN_PRESUPUESTO } from '../../types/inventario'
import { ROLES_MEDIDORES, formatoValor } from '../../types/medidores'
import { fecha as fmtFecha } from '../folios/comunes'
import { PestanaMedidores } from './PestanaMedidores'

function moneda(v: string | null | undefined) {
  return v == null ? '—' : `$${Number(v).toLocaleString('es-MX', { minimumFractionDigits: 2 })}`
}

/** Ficha del equipo (§6.9.4): datos, contrato y garantía, historial de folios con costos, refacciones, depreciación y TCO. */
export function FichaEquipo() {
  const { equipoId } = useParams()
  const { usuario } = useAuth()
  const [params] = useSearchParams()
  const [vista, setVista] = useState<'ficha' | 'medidores'>(params.get('vista') === 'medidores' ? 'medidores' : 'ficha')
  const [f, setF] = useState<FichaActivo | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [modal, setModal] = useState<'economicos' | 'depreciacion' | 'decision' | null>(null)
  const cargar = useCallback(async () => {
    if (!equipoId) return
    try { setF(await fichaActivo(equipoId)) } catch (e) { setError(mensajeDeError(e)) }
  }, [equipoId])
  useEffect(() => { void cargar() }, [cargar])
  if (!usuario) return null
  if (!f) return <div className="p-4">{error ? <Aviso>{error}</Aviso> : <p className="text-sm text-slate-500">Cargando la ficha del activo…</p>}</div>
  const e = f.equipo as Record<string, string | null>
  const configura = ROLES_ESCRIBEN_PRESUPUESTO.includes(usuario.rol)
  const tco = f.tco
  const componentes: [string, string][] = [
    ['Costo de adquisición', tco.costo_adquisicion], ['Preventivos acumulados', tco.costo_preventivos], ['Correctivos acumulados', tco.costo_correctivos],
    ['Refacciones consumidas', tco.costo_refacciones], ['Tiempo de inactividad', tco.costo_downtime], ['Valor residual (se resta)', tco.valor_residual],
  ]
  async function ejecutar(fn: () => Promise<unknown>, texto: string) {
    setError(null)
    try { await fn(); setModal(null); setAviso(texto); await cargar() } catch (err) { setError(mensajeDeError(err)) }
  }

  return (
    <div className="space-y-4">
      <Link to="/activos" className="text-xs text-primario underline">← Equipos y activos</Link>
      <Encabezado titulo={`${e.codigo} · ${e.nombre}`} descripcion={`${e.un_codigo ?? ''} ${e.un_nombre ?? ''} · ${e.tipo_equipo ?? ''}`}
        acciones={
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex gap-1">
              {(['ficha', 'medidores'] as const).map((v) => (
                <button key={v} className={`rounded-lg px-3 py-1.5 text-sm ${vista === v ? 'bg-primario text-white' : 'border border-slate-300'}`} onClick={() => setVista(v)}>
                  {v === 'ficha' ? 'Ficha y TCO' : `Medidores${f.medidores?.length ? ` (${f.medidores.length})` : ''}`}
                </button>
              ))}
            </div>
            {configura && vista === 'ficha' && (
              <>
                <Boton variante="secundario" onClick={() => setModal('economicos')}>Datos económicos</Boton>
                <Boton variante="secundario" onClick={() => setModal('depreciacion')}>Depreciación</Boton>
                <Boton onClick={() => void ejecutar(() => recalcularActivo(equipoId!), 'TCO y depreciación recalculados')}>Recalcular TCO</Boton>
              </>
            )}
          </div>
        } />
      {error && <Aviso>{error}</Aviso>}
      {aviso && <Aviso tipo="exito">{aviso}</Aviso>}

      {vista === 'medidores' && equipoId && (
        <PestanaMedidores equipoId={equipoId} puedeAdministrar={ROLES_MEDIDORES.includes(usuario.rol)} />
      )}
      {vista === 'medidores' ? null : (<>

      {f.alerta_reemplazo && f.alerta_reemplazo.decision === null && (
        <Tarjeta titulo="Reemplazo recomendado" acciones={<Insignia tono="alerta">{Number(f.alerta_reemplazo.porcentaje_alcanzado).toFixed(1)}% del valor de reposición</Insignia>}>
          <p className="text-sm">El costo total de propiedad acumulado ({moneda(f.alerta_reemplazo.tco_al_momento)}) superó el umbral del {Number(f.alerta_reemplazo.porcentaje_umbral).toFixed(0)}% sobre {moneda(f.alerta_reemplazo.valor_reposicion)} de reposición.</p>
          {configura && <div className="mt-2"><Boton onClick={() => setModal('decision')}>Decidir: reemplazar o reparar</Boton></div>}
        </Tarjeta>
      )}
      {f.alerta_reemplazo?.decision && (
        <Aviso tipo="info">Decisión registrada: {f.alerta_reemplazo.decision === 'aceptado' ? 'reemplazo aceptado' : 'reemplazo pospuesto'}{f.alerta_reemplazo.razon && ` · ${f.alerta_reemplazo.razon}`}
          {f.alerta_reemplazo.trabajo_especial_id && <> · <Link className="underline" to={`/trabajos-especiales?registro=${f.alerta_reemplazo.trabajo_especial_id}`}>ver el trabajo especial</Link></>}</Aviso>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <Tarjeta titulo="Datos del equipo">
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm" data-testid="datos-equipo">
            <dt className="text-slate-500">Marca y modelo</dt><dd>{e.marca ?? '—'} {e.modelo ?? ''}</dd>
            <dt className="text-slate-500">Número de serie</dt><dd>{e.numero_serie ?? '—'}</dd>
            <dt className="text-slate-500">Estado</dt><dd>{e.estado}</dd>
            <dt className="text-slate-500">Criticidad</dt><dd>{e.criticidad ?? '—'} <span className="text-xs text-slate-500">{e.criticidad_origen}</span></dd>
            <dt className="text-slate-500">Instalación</dt><dd>{e.fecha_instalacion ?? '—'}</dd>
            <dt className="text-slate-500">Adquisición</dt><dd>{moneda(e.costo_adquisicion)} {e.fecha_adquisicion ? `· ${e.fecha_adquisicion}` : ''}</dd>
            <dt className="text-slate-500">Valor de reposición</dt><dd>{moneda(e.valor_reposicion)}</dd>
            <dt className="text-slate-500">Costo por hora de inactividad</dt><dd>{moneda(e.costo_hora_inactividad)}</dd>
            <dt className="text-slate-500">Garantía</dt><dd>{e.garantia_vigente_hasta ?? 'sin garantía vigente'}</dd>
            <dt className="text-slate-500">Activo fijo en el ERP</dt><dd>{e.numero_activo_fijo_erp ?? 'pendiente'}</dd>
          </dl>
          {f.contrato && <p className="mt-2 text-xs text-slate-600">Contrato {f.contrato.nombre} ({f.contrato.modalidad}) vigente de {f.contrato.fecha_inicio} a {f.contrato.fecha_fin}</p>}
        </Tarjeta>
        <Tarjeta titulo={`Costo total de propiedad · período ${tco.periodo}`}>
          <p className="text-2xl font-semibold" data-testid="tco-total">{moneda(tco.tco_total)}</p>
          <p className="text-xs text-slate-600">{Number(tco.porcentaje_vs_reposicion).toFixed(1)}% del valor de reposición ({moneda(tco.valor_reposicion)}) · umbral {Number(f.umbral_reemplazo_pct).toFixed(0)}%</p>
          <ul className="mt-2 text-sm" data-testid="componentes-tco">
            {componentes.map(([nombre, valor]) => <li key={nombre} className="flex justify-between gap-4"><span className="text-slate-600">{nombre}</span><span>{moneda(valor)}</span></li>)}
          </ul>
          <p className="mt-2 text-xs text-slate-500">{Number(tco.horas_downtime).toFixed(1)} h de inactividad en {tco.folios} folio(s) cerrados. Las refacciones ya están incluidas en los costos de preventivos y correctivos.</p>
        </Tarjeta>
      </div>

      <Tarjeta titulo="Depreciación">
        {f.depreciacion ? (
          <>
            <p className="text-sm">{NOMBRE_METODO[f.depreciacion.metodo]} · vida útil {f.depreciacion.vida_util_anios} años · salvamento {moneda(f.depreciacion.valor_salvamento)} · desde {f.depreciacion.fecha_inicio}</p>
            <p className="text-xs text-slate-500">{DESCRIPCION_METODO[f.depreciacion.metodo]}</p>
            {f.depreciacion.metodo === 'unidades_produccion' && f.depreciacion.equipo_medidor_id && (
              <p className="text-sm" data-testid="depreciacion-unidades">
                {formatoValor(f.depreciacion.unidades_acumuladas, 0)} de {formatoValor(f.depreciacion.unidades_vida_util, 0)} unidades de vida útil
                {f.depreciacion.unidades_periodo && <> · {formatoValor(f.depreciacion.unidades_periodo, 0)} en el período</>}
              </p>
            )}
            {f.depreciacion.aviso === 'MEDIDOR_NO_CONFIGURADO' && (
              <div className="mt-2"><Aviso tipo="info">
                El método reparte el costo según el uso medido, pero este activo todavía no tiene medidor elegido: se
                está usando el campo de unidades acumuladas capturado a mano. Elígele uno en «Depreciación».
              </Aviso></div>
            )}
            {f.depreciacion.aviso === 'SIN_VIDA_UTIL_EN_UNIDADES' && (
              <div className="mt-2"><Aviso tipo="info">Falta la vida útil total en unidades: sin ella no hay cómo repartir el costo.</Aviso></div>
            )}
            {f.depreciacion_historial.length > 0 && (
              <div className="mt-3" data-testid="grafica-depreciacion">
                <p className="text-xs font-semibold uppercase text-slate-500">Valor en libros por período</p>
                <div className="mt-1 flex items-end gap-1" role="img" aria-label="Evolución del valor en libros">
                  {f.depreciacion_historial.slice(-12).map((h) => {
                    const max = Math.max(...f.depreciacion_historial.map((x) => Number(x.valor_en_libros)), 1)
                    return <div key={h.periodo} title={`${h.periodo}: ${moneda(h.valor_en_libros)}`} className="w-6 rounded-t bg-primario/70" style={{ height: `${Math.max(4, (Number(h.valor_en_libros) / max) * 80)}px` }} />
                  })}
                </div>
                <ul className="mt-1 text-xs text-slate-500">{f.depreciacion_historial.slice(-3).map((h) => (
                  <li key={h.periodo}>{h.periodo}: en libros {moneda(h.valor_en_libros)} · del período {moneda(h.depreciacion_periodo)} · acumulada {moneda(h.depreciacion_acumulada)}</li>
                ))}</ul>
              </div>
            )}
          </>
        ) : <p className="text-sm text-slate-500">Sin método de depreciación configurado. El valor residual del TCO usa el costo de adquisición.</p>}
      </Tarjeta>

      <Tarjeta titulo={`Historial de folios (${f.historial_folios.length})`}>
        <Tabla filas={f.historial_folios} vacio="El equipo no tiene folios registrados" columnas={[
          { titulo: 'Folio', celda: (h) => <Link className="font-mono text-xs text-primario underline" to={`/folios/${h.id}`}>{h.numero_folio}</Link> },
          { titulo: 'Tipo', celda: (h) => <Insignia tono={h.tipo_folio === 'preventivo' ? 'acento' : 'neutro'}>{h.tipo_folio}</Insignia> },
          { titulo: 'Falla', celda: (h) => <span className="text-sm">{h.tipo_falla ?? h.descripcion.slice(0, 50)}</span> },
          { titulo: 'Técnico', celda: (h) => h.tecnico_nombre ?? '—' },
          { titulo: 'Cierre', celda: (h) => <span className="text-xs">{h.fecha_cierre ? fmtFecha(h.fecha_cierre) : h.estado}</span> },
          { titulo: 'Desvío', celda: (h) => <span className="text-xs">{h.desvio ?? '—'}</span> },
          { titulo: 'Costo', celda: (h) => h.costo_total == null ? <span className="text-xs text-slate-400">—</span>
            : <span>{moneda(h.costo_total)}{h.costo_validado && <> <Insignia tono="ok">validado</Insignia></>}</span> },
        ]} />
      </Tarjeta>

      <Tarjeta titulo={`Refacciones consumidas (${f.refacciones.length})`}>
        {f.refacciones.length === 0 ? <p className="text-sm text-slate-500">Sin refacciones registradas.</p> : (
          <ul className="text-sm" data-testid="refacciones-activo">{f.refacciones.slice(0, 20).map((r) => (
            <li key={r.id}>{r.descripcion} — {Number(r.cantidad)} {r.importe ? `· ${moneda(r.importe)}` : ''} <span className="text-xs text-slate-500">({r.origen})</span></li>
          ))}</ul>
        )}
      </Tarjeta>

      <Tarjeta titulo="Disponible en Fase 2">
        <ul className="list-disc pl-5 text-sm text-slate-600">{f.fase_2.map((x) => <li key={x}>{x}</li>)}</ul>
      </Tarjeta>
      </>)}

      {modal === 'economicos' && <FormEconomicos ficha={f} alCerrar={() => setModal(null)}
        alGuardar={(d) => ejecutar(() => guardarDatosEconomicos(equipoId!, d), 'Datos económicos guardados')} />}
      {modal === 'depreciacion' && <FormDepreciacion ficha={f} alCerrar={() => setModal(null)}
        alGuardar={(d) => ejecutar(() => guardarDepreciacion(equipoId!, d), 'Depreciación configurada')} />}
      {modal === 'decision' && f.alerta_reemplazo && (
        <Modal titulo="Reemplazar o reparar" abierto alCerrar={() => setModal(null)}>
          <DecisionReemplazo alertaId={f.alerta_reemplazo.id} alDecidir={async (decision, razon) => {
            setError(null)
            try {
              const r = await decidirReemplazo(f.alerta_reemplazo!.id, decision, razon)
              setModal(null)
              setAviso(r.trabajo_especial
                ? `Reemplazo aceptado: trabajo especial ${r.trabajo_especial.numero} creado para que el prestador lo cotice`
                : 'Reemplazo pospuesto con la razón documentada')
              await cargar()
            } catch (err) { setError(mensajeDeError(err)) }
          }} />
        </Modal>
      )}
    </div>
  )
}

function DecisionReemplazo({ alertaId, alDecidir }: { alertaId: string; alDecidir: (d: 'aceptado' | 'pospuesto', razon: string) => Promise<void> }) {
  const [razon, setRazon] = useState('')
  return (
    <div className="space-y-3 text-sm" data-testid="decision-ficha">
      <Aviso tipo="info">Aceptar genera el trabajo especial de reemplazo en estado creado para que el prestador lo cotice; posponer exige razón documentada.</Aviso>
      <Campo etiqueta="Razón (obligatoria al posponer)" value={razon} onChange={(e) => setRazon(e.target.value)} />
      <div className="flex gap-2">
        <Boton onClick={() => void alDecidir('aceptado', razon)}>Aceptar reemplazo</Boton>
        <Boton variante="secundario" disabled={razon.trim().length < 3} onClick={() => void alDecidir('pospuesto', razon)}>Posponer</Boton>
      </div>
      <p className="text-xs text-slate-400">Alerta {alertaId.slice(0, 8)}</p>
    </div>
  )
}

function FormEconomicos({ ficha, alCerrar, alGuardar }: { ficha: FichaActivo; alCerrar: () => void; alGuardar: (d: Record<string, string>) => Promise<void> }) {
  const e = ficha.equipo as Record<string, string | null>
  const [d, setD] = useState({ costo_adquisicion: e.costo_adquisicion ?? '', fecha_adquisicion: e.fecha_adquisicion ?? '',
                               valor_reposicion: e.valor_reposicion ?? '', costo_hora_inactividad: e.costo_hora_inactividad ?? '',
                               numero_activo_fijo_erp: e.numero_activo_fijo_erp ?? '' })
  return (
    <Modal titulo="Datos económicos del activo" abierto alCerrar={alCerrar}>
      <div className="space-y-3" data-testid="form-economicos">
        <div className="grid gap-2 sm:grid-cols-2">
          <Campo etiqueta="Costo de adquisición" type="number" value={d.costo_adquisicion} onChange={(x) => setD({ ...d, costo_adquisicion: x.target.value })} />
          <Campo etiqueta="Fecha de adquisición" type="date" value={d.fecha_adquisicion} onChange={(x) => setD({ ...d, fecha_adquisicion: x.target.value })} />
          <Campo etiqueta="Valor de reposición" type="number" value={d.valor_reposicion} onChange={(x) => setD({ ...d, valor_reposicion: x.target.value })} />
          <Campo etiqueta="Costo por hora de inactividad" type="number" value={d.costo_hora_inactividad} onChange={(x) => setD({ ...d, costo_hora_inactividad: x.target.value })} />
        </div>
        <Campo etiqueta="Número de activo fijo en el ERP" value={d.numero_activo_fijo_erp} onChange={(x) => setD({ ...d, numero_activo_fijo_erp: x.target.value })} />
        <div className="flex gap-2">
          <Boton onClick={() => void alGuardar(Object.fromEntries(Object.entries(d).filter(([, v]) => v !== '')) as Record<string, string>)}>Guardar</Boton>
          <Boton variante="secundario" onClick={alCerrar}>Cancelar</Boton>
        </div>
      </div>
    </Modal>
  )
}

function FormDepreciacion({ ficha, alCerrar, alGuardar }: { ficha: FichaActivo; alCerrar: () => void; alGuardar: (d: Record<string, string | number>) => Promise<void> }) {
  const dep = ficha.depreciacion
  const [d, setD] = useState({ metodo: (dep?.metodo ?? 'linea_recta') as MetodoDepreciacion, vida_util_anios: String(dep?.vida_util_anios ?? 10),
                               valor_salvamento: dep?.valor_salvamento ?? '0', valor_reposicion: dep?.valor_reposicion ?? '',
                               unidades_vida_util: dep?.unidades_vida_util ?? '', unidades_acumuladas: dep?.unidades_acumuladas ?? '',
                               valor_en_libros_manual: dep?.valor_en_libros_manual ?? '', fecha_inicio: dep?.fecha_inicio ?? '',
                               // F2-04: de qué medidor del equipo salen las unidades producidas (§6.9.4).
                               equipo_medidor_id: dep?.equipo_medidor_id ?? '', unidades_al_inicio: dep?.unidades_al_inicio ?? '' })
  return (
    <Modal titulo="Método de depreciación" abierto alCerrar={alCerrar}>
      <div className="space-y-3" data-testid="form-depreciacion">
        <Selector etiqueta="Método" value={d.metodo} onChange={(e) => setD({ ...d, metodo: e.target.value as MetodoDepreciacion })}
          opciones={(Object.keys(NOMBRE_METODO) as MetodoDepreciacion[]).map((m) => ({ valor: m, texto: NOMBRE_METODO[m] }))} />
        <p className="text-xs text-slate-600">{DESCRIPCION_METODO[d.metodo]}</p>
        {d.metodo === 'unidades_produccion' && (
          <Aviso tipo="info">
            Elige de qué medidor del equipo salen las unidades: ACMA toma las del período de sus lecturas válidas. Sin
            medidor se usa el campo de unidades acumuladas capturado a mano.
          </Aviso>
        )}
        <div className="grid gap-2 sm:grid-cols-2">
          {d.metodo !== 'manual' && <Campo etiqueta="Vida útil (años)" type="number" value={d.vida_util_anios} onChange={(e) => setD({ ...d, vida_util_anios: e.target.value })} />}
          {d.metodo !== 'manual' && <Campo etiqueta="Valor de salvamento" type="number" value={d.valor_salvamento} onChange={(e) => setD({ ...d, valor_salvamento: e.target.value })} />}
          <Campo etiqueta="Valor de reposición" type="number" value={d.valor_reposicion} onChange={(e) => setD({ ...d, valor_reposicion: e.target.value })} />
          <Campo etiqueta="Inicio de la depreciación" type="date" value={d.fecha_inicio} onChange={(e) => setD({ ...d, fecha_inicio: e.target.value })} />
          {d.metodo === 'unidades_produccion' && <Campo etiqueta="Unidades de vida útil" type="number" value={d.unidades_vida_util} onChange={(e) => setD({ ...d, unidades_vida_util: e.target.value })} />}
          {d.metodo === 'unidades_produccion' && (
            <Selector etiqueta="Medidor del que salen las unidades" value={d.equipo_medidor_id}
              onChange={(e) => setD({ ...d, equipo_medidor_id: e.target.value })}
              opciones={[{ valor: '', texto: 'Sin medidor (capturar a mano)' },
                         ...(ficha.medidores ?? []).map((m) => ({ valor: m.id, texto: `${m.tipo} (${m.unidad})` }))]} />
          )}
          {d.metodo === 'unidades_produccion' && <Campo etiqueta={d.equipo_medidor_id ? 'Unidades que ya traía al inicio' : 'Unidades acumuladas'} type="number"
            value={d.equipo_medidor_id ? d.unidades_al_inicio : d.unidades_acumuladas}
            onChange={(e) => setD(d.equipo_medidor_id ? { ...d, unidades_al_inicio: e.target.value } : { ...d, unidades_acumuladas: e.target.value })} />}
          {(d.metodo === 'manual' || d.metodo === 'unidades_produccion') && <Campo etiqueta="Valor en libros" type="number" value={d.valor_en_libros_manual} onChange={(e) => setD({ ...d, valor_en_libros_manual: e.target.value })} />}
        </div>
        <div className="flex gap-2">
          <Boton onClick={() => void alGuardar(Object.fromEntries(Object.entries(d).filter(([, v]) => v !== '')) as Record<string, string>)}>Guardar</Boton>
          <Boton variante="secundario" onClick={alCerrar}>Cancelar</Boton>
        </div>
      </div>
    </Modal>
  )
}
