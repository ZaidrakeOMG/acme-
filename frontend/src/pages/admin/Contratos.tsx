import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { Aviso, Boton, Campo, Encabezado, Insignia, Modal, Selector, Tabla, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { useRecurso } from '../../hooks/useRecurso'
import { api, mensajeDeError } from '../../services/api'
import { abrirBlob } from '../../services/minutas'
import {
  archivoPenalizaciones, calcularIguala, calcularPenalizaciones, cambiarEstadoPenalizacion, cumplimientoContrato,
  decidirExclusion, listarExclusiones, listarIguala, listarPenalizaciones,
} from '../../services/sla'
import type { Contrato, NivelSeveridad, SLA, Tenant } from '../../types/api'
import type { CumplimientoContrato, Exclusion, Iguala, Penalizacion } from '../../types/sla'
import {
  NOMBRE_CAUSA, NOMBRE_ESTADO_PENALIZACION, ROLES_APRUEBAN_EXCLUSION, ROLES_REVISAN_PENALIZACION,
} from '../../types/sla'
import { fecha as fmtFecha } from '../folios/comunes'

export const NIVELES: { nivel: NivelSeveridad; nombre: string }[] = [
  { nivel: 'critica', nombre: 'Crítica' },
  { nivel: 'alta', nombre: 'Alta' },
  { nivel: 'media', nombre: 'Media' },
  { nivel: 'baja', nombre: 'Baja' },
  { nivel: 'muy_baja', nombre: 'Muy baja' },
]
const SLA_INICIAL: Record<NivelSeveridad, [number, number]> = {
  critica: [2, 8], alta: [4, 24], media: [8, 72], baja: [24, 168], muy_baja: [72, 720],
}
const UNIDADES: { valor: 'horas' | 'dias' | 'semanas' | 'meses'; texto: string; factor: number }[] = [
  { valor: 'horas', texto: 'Horas', factor: 1 }, { valor: 'dias', texto: 'Días', factor: 24 },
  { valor: 'semanas', texto: 'Semanas', factor: 168 }, { valor: 'meses', texto: 'Meses', factor: 720 },
]
type Vista = 'contratos' | 'cumplimiento' | 'exclusiones'

function moneda(v: string | number | null | undefined) {
  return v == null ? '—' : `$${Number(v).toLocaleString('es-MX', { minimumFractionDigits: 2 })}`
}
function periodoActual() {
  return new Date().toISOString().slice(0, 7)
}

/** Contratos y SLAs (§6.10.1): estructura, modalidad e iguala, cumplimiento, penalizaciones y bandeja de exclusiones. */
export function Contratos() {
  const { usuario } = useAuth()
  const [params, setParams] = useSearchParams()
  const vista = (params.get('vista') as Vista) || 'contratos'
  const { datos, error, recargar } = useRecurso<Contrato[]>('/contratos')
  const tenants = useRecurso<Tenant[]>('/tenants')
  const [editar, setEditar] = useState<Contrato | 'nuevo' | null>(null)
  const puedeEditar = usuario?.rol === 'admin_prestador' || usuario?.rol === 'superadmin'
  const nombreTenant = (id: string) => tenants.datos?.find((t) => t.id === id)?.razon_social ?? id.slice(0, 8)
  function ir(v: Vista) {
    const p = new URLSearchParams(params)
    p.set('vista', v)
    setParams(p)
  }
  if (!usuario) return null

  return (
    <div>
      <Encabezado
        titulo="Contratos y SLAs"
        descripcion="Un contrato por relación cliente–prestador: vigencia, modalidad por evento o iguala, SLA y penalización por cada nivel de severidad, cumplimiento del período y exclusiones justificadas."
        acciones={puedeEditar && vista === 'contratos' ? <Boton onClick={() => setEditar('nuevo')}>Nuevo contrato</Boton> : undefined}
      />
      <div className="mb-3 flex flex-wrap gap-1" role="tablist" aria-label="Vistas de contratos">
        {([['contratos', 'Contratos'], ['cumplimiento', 'Cumplimiento y penalizaciones'], ['exclusiones', 'Exclusiones de SLA']] as [Vista, string][]).map(([v, texto]) => (
          <button key={v} role="tab" aria-selected={vista === v} onClick={() => ir(v)}
            className={`rounded-lg px-3 py-1.5 text-sm ${vista === v ? 'bg-primario text-white' : 'border border-slate-300'}`}>{texto}</button>
        ))}
      </div>

      {vista === 'contratos' && (
        <Tarjeta>
          {error && <Aviso>{error}</Aviso>}
          <Tabla
            filas={datos ?? []}
            columnas={[
              { titulo: 'Contrato', celda: (c) => <><p className="font-medium">{c.nombre}</p><p className="text-xs text-slate-500">{nombreTenant(c.tenant_id)}</p></> },
              { titulo: 'Vigencia', celda: (c) => `${c.fecha_inicio} → ${c.fecha_fin}` },
              { titulo: 'Modalidad', celda: (c) => <div className="flex flex-wrap gap-1">
                <Insignia tono="acento">{c.modalidad === 'iguala' ? 'Iguala mensual' : 'Por evento'}</Insignia>
                {c.modalidad === 'iguala' && <Insignia>{c.folios_correctivos_iguala ?? 0} correctivos · {moneda(c.tarifa_iguala_mensual)}</Insignia>}
              </div> },
              {
                titulo: 'SLA crítico (resp./resol.)',
                celda: (c) => {
                  const s = c.slas.find((x) => x.nivel_severidad === 'critica')
                  return s ? `${s.tiempo_respuesta_horas} h / ${s.tiempo_resolucion_horas} h` : '—'
                },
              },
              { titulo: '', celda: (c) => <Boton variante="fantasma" onClick={() => setEditar(c)}>{puedeEditar ? 'Editar' : 'Ver'}</Boton> },
            ]}
          />
        </Tarjeta>
      )}
      {vista === 'cumplimiento' && <Cumplimiento contratos={datos ?? []} nombreTenant={nombreTenant} />}
      {vista === 'exclusiones' && <BandejaExclusiones />}

      <Modal titulo={editar === 'nuevo' ? 'Nuevo contrato' : 'Contrato'} abierto={editar !== null} alCerrar={() => setEditar(null)}>
        {editar && (
          <FormularioContrato
            contrato={editar === 'nuevo' ? null : editar}
            tenants={tenants.datos ?? []}
            soloLectura={!puedeEditar}
            alGuardar={async () => {
              setEditar(null)
              await recargar()
            }}
          />
        )}
      </Modal>
    </div>
  )
}

function FormularioContrato({ contrato, tenants, soloLectura, alGuardar }: { contrato: Contrato | null; tenants: Tenant[]; soloLectura: boolean; alGuardar: () => Promise<void> }) {
  const [error, setError] = useState<string | null>(null)
  const [tenantId, setTenantId] = useState(contrato?.tenant_id ?? tenants[0]?.id ?? '')
  const [nombre, setNombre] = useState(contrato?.nombre ?? '')
  const [modalidad, setModalidad] = useState<'evento' | 'iguala'>(contrato?.modalidad ?? 'evento')
  const [folios, setFolios] = useState(String(contrato?.folios_correctivos_iguala ?? ''))
  const [tarifa, setTarifa] = useState(String(contrato?.tarifa_iguala_mensual ?? ''))
  const prev = (contrato?.preventivos_iguala_json ?? {}) as Record<string, unknown>
  const [preventivos, setPreventivos] = useState(String((prev.cantidad as number | undefined) ?? ''))
  const [periodicidad, setPeriodicidad] = useState(String((prev.periodicidad as string | undefined) ?? 'mensual'))
  const [puntos, setPuntos] = useState(String((prev.puntos_a_revisar as string | undefined) ?? ''))
  const [inicio, setInicio] = useState(contrato?.fecha_inicio ?? '')
  const [fin, setFin] = useState(contrato?.fecha_fin ?? '')
  const [slas, setSlas] = useState<Record<NivelSeveridad, { resp: string; resol: string; unidad: string; tipo: string; pen: string }>>(() =>
    Object.fromEntries(
      NIVELES.map(({ nivel }) => {
        const s: SLA | undefined = contrato?.slas.find((x) => x.nivel_severidad === nivel)
        const factor = UNIDADES.find((u) => u.valor === (s?.unidad_expresion ?? 'horas'))?.factor ?? 1
        return [nivel, {
          resp: String(s?.tiempo_respuesta ?? (s ? Math.round(s.tiempo_respuesta_horas / factor) : SLA_INICIAL[nivel][0])),
          resol: String(s?.tiempo_resolucion ?? (s ? Math.round(s.tiempo_resolucion_horas / factor) : SLA_INICIAL[nivel][1])),
          unidad: s?.unidad_expresion ?? 'horas',
          tipo: s?.penalizacion_tipo ?? 'porcentaje',
          pen: String(s?.penalizacion_valor ?? 0),
        }]
      }),
    ) as Record<NivelSeveridad, { resp: string; resol: string; unidad: string; tipo: string; pen: string }>,
  )

  async function guardar() {
    setError(null)
    const cuerpoSlas = NIVELES.map(({ nivel }) => ({
      nivel_severidad: nivel,
      tiempo_respuesta: Number(slas[nivel].resp),
      tiempo_resolucion: Number(slas[nivel].resol),
      unidad_expresion: slas[nivel].unidad,
      penalizacion_tipo: slas[nivel].tipo,
      penalizacion_valor: Number(slas[nivel].pen),
    }))
    const invalido = cuerpoSlas.find((s) => {
      const f = UNIDADES.find((u) => u.valor === s.unidad_expresion)?.factor ?? 1
      const resp = s.tiempo_respuesta * f
      const resol = s.tiempo_resolucion * f
      return !(resp >= 1 && resol <= 4320 && resol >= resp)
    })
    if (invalido) return setError('Cada nivel requiere entre 1 y 4,320 horas equivalentes y resolución ≥ respuesta')
    if (modalidad === 'iguala' && !(Number(folios) >= 0 && Number(tarifa) > 0)) {
      return setError('La modalidad iguala requiere la tarifa mensual y los correctivos incluidos')
    }
    const cuerpo: Record<string, unknown> = {
      nombre, modalidad, fecha_inicio: inicio, fecha_fin: fin, slas: cuerpoSlas,
      folios_correctivos_iguala: modalidad === 'iguala' ? Number(folios || 0) : null,
      tarifa_iguala_mensual: modalidad === 'iguala' ? tarifa : null,
      preventivos_iguala_json: modalidad === 'iguala'
        ? { cantidad: Number(preventivos || 0), periodicidad, ...(puntos ? { puntos_a_revisar: puntos } : {}) }
        : {},
    }
    try {
      if (contrato) await api(`/contratos/${contrato.id}`, { metodo: 'PATCH', cuerpo })
      else await api('/contratos', { metodo: 'POST', cuerpo: { ...cuerpo, tenant_id: tenantId } })
      await alGuardar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  return (
    <fieldset disabled={soloLectura} className="space-y-3" data-testid="form-contrato">
      {error && <Aviso>{error}</Aviso>}
      {!contrato && <Selector etiqueta="Cliente" value={tenantId} onChange={(e) => setTenantId(e.target.value)} opciones={tenants.map((t) => ({ valor: t.id, texto: t.razon_social }))} />}
      <Campo etiqueta="Nombre del contrato" value={nombre} onChange={(e) => setNombre(e.target.value)} />
      <div className="grid grid-cols-2 gap-3">
        <Campo etiqueta="Inicio" type="date" value={inicio} onChange={(e) => setInicio(e.target.value)} />
        <Campo etiqueta="Fin" type="date" value={fin} onChange={(e) => setFin(e.target.value)} />
      </div>
      <Selector etiqueta="Modalidad" value={modalidad} onChange={(e) => setModalidad(e.target.value as 'evento' | 'iguala')}
        opciones={[{ valor: 'evento', texto: 'Por evento (cada folio se cotiza y cobra)' }, { valor: 'iguala', texto: 'Iguala mensual' }]} />
      {modalidad === 'iguala' && (
        <div className="grid gap-2 sm:grid-cols-2" data-testid="campos-iguala">
          <Campo etiqueta="Tarifa mensual" type="number" min={0} step="0.01" value={tarifa} onChange={(e) => setTarifa(e.target.value)} />
          <Campo etiqueta="Correctivos incluidos" type="number" min={0} value={folios} onChange={(e) => setFolios(e.target.value)} />
          <Campo etiqueta="Preventivos incluidos" type="number" min={0} value={preventivos} onChange={(e) => setPreventivos(e.target.value)} />
          <Selector etiqueta="Periodicidad de los preventivos" value={periodicidad} onChange={(e) => setPeriodicidad(e.target.value)}
            opciones={[{ valor: 'mensual', texto: 'Mensual' }, { valor: 'bimestral', texto: 'Bimestral' }, { valor: 'trimestral', texto: 'Trimestral' }]} />
          <div className="sm:col-span-2">
            <Campo etiqueta="Puntos a revisar (biblioteca de manuales)" value={puntos} onChange={(e) => setPuntos(e.target.value)} />
          </div>
        </div>
      )}
      <table className="w-full text-sm">
        <thead className="text-xs text-slate-500">
          <tr><th className="text-left">Severidad</th><th>Respuesta</th><th>Resolución</th><th>Unidad</th><th>Penalización</th><th>Valor</th></tr>
        </thead>
        <tbody>
          {NIVELES.map(({ nivel, nombre: n }) => (
            <tr key={nivel}>
              <td className="py-1 pr-2 font-medium">{n}</td>
              {(['resp', 'resol'] as const).map((k) => (
                <td key={k} className="px-1 py-1">
                  <input aria-label={`${n} ${k}`} type="number" min={1} value={slas[nivel][k]}
                    onChange={(e) => setSlas({ ...slas, [nivel]: { ...slas[nivel], [k]: e.target.value } })}
                    className="w-full rounded border border-slate-300 px-2 py-1" />
                </td>
              ))}
              <td className="px-1 py-1">
                <select aria-label={`${n} unidad`} value={slas[nivel].unidad}
                  onChange={(e) => setSlas({ ...slas, [nivel]: { ...slas[nivel], unidad: e.target.value } })}
                  className="w-full rounded border border-slate-300 px-2 py-1">
                  {UNIDADES.map((u) => <option key={u.valor} value={u.valor}>{u.texto}</option>)}
                </select>
              </td>
              <td className="px-1 py-1">
                <select aria-label={`${n} tipo`} value={slas[nivel].tipo}
                  onChange={(e) => setSlas({ ...slas, [nivel]: { ...slas[nivel], tipo: e.target.value } })}
                  className="w-full rounded border border-slate-300 px-2 py-1">
                  <option value="porcentaje">% del costo</option>
                  <option value="monto">Monto fijo</option>
                </select>
              </td>
              <td className="px-1 py-1">
                <input aria-label={`${n} pen`} type="number" min={0} max={slas[nivel].tipo === 'porcentaje' ? 100 : undefined}
                  value={slas[nivel].pen}
                  onChange={(e) => setSlas({ ...slas, [nivel]: { ...slas[nivel], pen: e.target.value } })}
                  className="w-full rounded border border-slate-300 px-2 py-1" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-xs text-slate-500">§6.10.1: el tiempo se firma en la unidad que elija el cliente y ACMA valida su
        equivalente entre 1 y 4,320 horas. La penalización solo se calcula cuando se incumple la resolución.</p>
      {!soloLectura && <Boton className="w-full" onClick={() => void guardar()}>Guardar contrato</Boton>}
    </fieldset>
  )
}

function Cumplimiento({ contratos, nombreTenant }: { contratos: Contrato[]; nombreTenant: (id: string) => string }) {
  const { usuario } = useAuth()
  const [contratoId, setContratoId] = useState('')
  const [periodo, setPeriodo] = useState(periodoActual())
  const [datos, setDatos] = useState<CumplimientoContrato | null>(null)
  const [penalizaciones, setPenalizaciones] = useState<Penalizacion[]>([])
  const [iguala, setIguala] = useState<Iguala[]>([])
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const contrato = contratos.find((c) => c.id === contratoId)
  const revisa = usuario ? ROLES_REVISAN_PENALIZACION.includes(usuario.rol) : false

  useEffect(() => { if (!contratoId && contratos[0]) setContratoId(contratos[0].id) }, [contratos, contratoId])
  const cargar = useCallback(async () => {
    if (!contratoId) return
    try {
      setDatos(await cumplimientoContrato(contratoId))
      setPenalizaciones(await listarPenalizaciones(contratoId))
      setIguala(await listarIguala(contratoId))
    } catch (e) { setError(mensajeDeError(e)) }
  }, [contratoId])
  useEffect(() => { void cargar() }, [cargar])

  async function ejecutar(fn: () => Promise<unknown>, texto: string) {
    setError(null)
    try { await fn(); setAviso(texto); await cargar() } catch (e) { setError(mensajeDeError(e)) }
  }

  return (
    <div className="space-y-4" data-testid="cumplimiento-contrato">
      <div className="flex flex-wrap items-end gap-2">
        <Selector etiqueta="Contrato" value={contratoId} onChange={(e) => setContratoId(e.target.value)}
          opciones={contratos.map((c) => ({ valor: c.id, texto: `${c.nombre} · ${nombreTenant(c.tenant_id)}` }))} />
        <Campo etiqueta="Período (YYYY-MM)" value={periodo} onChange={(e) => setPeriodo(e.target.value)} />
        {revisa && contratoId && (
          <Boton onClick={() => void ejecutar(() => calcularPenalizaciones(contratoId, periodo), `Penalizaciones de ${periodo} consolidadas`)}>
            Calcular penalizaciones
          </Boton>
        )}
        {revisa && contrato?.modalidad === 'iguala' && (
          <Boton variante="secundario" onClick={() => void ejecutar(() => calcularIguala(contratoId, periodo), `Consumo de iguala de ${periodo} actualizado`)}>
            Calcular iguala
          </Boton>
        )}
      </div>
      {error && <Aviso>{error}</Aviso>}
      {aviso && <Aviso tipo="exito">{aviso}</Aviso>}

      {datos && (
        <div className="grid gap-4 md:grid-cols-2">
          <Tarjeta titulo={`Cumplimiento · ${datos.periodo}`}>
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
              <dt className="text-slate-500">Folios cerrados</dt><dd>{datos.folios_cerrados}</dd>
              <dt className="text-slate-500">Respuesta</dt><dd data-testid="pct-respuesta">{datos.cumplimiento_respuesta_pct} %</dd>
              <dt className="text-slate-500">Resolución</dt><dd data-testid="pct-resolucion">{datos.cumplimiento_resolucion_pct} %</dd>
              <dt className="text-slate-500">Incumplidos</dt><dd>{datos.folios_incumplidos}</dd>
              <dt className="text-slate-500">Penalización</dt><dd>{moneda(datos.penalizacion)}</dd>
              <dt className="text-slate-500">Exclusiones por aprobar</dt><dd>{datos.exclusiones_pendientes}</dd>
            </dl>
            <table className="mt-2 w-full text-xs">
              <thead className="text-slate-500"><tr><th className="text-left">Severidad</th><th>Folios</th><th>Respuesta</th><th>Resolución</th><th>Penalizados</th></tr></thead>
              <tbody>{Object.entries(datos.por_severidad).map(([nombre, v]) => (
                <tr key={nombre}><td className="py-0.5">{nombre}</td><td className="text-center">{v.total}</td>
                  <td className="text-center">{v.respuesta_pct} %</td><td className="text-center">{v.resolucion_pct} %</td>
                  <td className="text-center">{v.penalizados}</td></tr>
              ))}</tbody>
            </table>
          </Tarjeta>
          {contrato?.modalidad === 'iguala' && (
            <Tarjeta titulo="Consumo de la iguala">
              {iguala.length === 0 ? <p className="text-sm text-slate-500">Sin períodos calculados.</p> : (
                <ul className="space-y-2 text-sm" data-testid="consumo-iguala">{iguala.map((x) => (
                  <li key={x.id}>
                    <p className="font-medium">{x.periodo} · {moneda(x.tarifa_mensual)} mensuales</p>
                    <p className="text-xs text-slate-600">Correctivos {x.correctivos_atendidos} de {x.correctivos_incluidos} incluidos
                      {x.correctivos_adicionales > 0 && <> · <strong className="text-red-700">{x.correctivos_adicionales} adicionales</strong></>}</p>
                    <p className="text-xs text-slate-600">Preventivos {x.preventivos_ejecutados} de {x.preventivos_incluidos} incluidos</p>
                  </li>
                ))}</ul>
              )}
            </Tarjeta>
          )}
        </div>
      )}

      <Tarjeta titulo="Penalizaciones por período">
        <Tabla filas={penalizaciones} vacio="Sin períodos consolidados" columnas={[
          { titulo: 'Período', celda: (p) => p.periodo },
          { titulo: 'Folios', celda: (p) => `${p.folios_incumplidos} de ${p.total_folios}` },
          { titulo: 'Monto', celda: (p) => moneda(p.monto_penalizacion) },
          { titulo: 'Estado', celda: (p) => <Insignia tono={p.estado === 'cerrado' ? 'ok' : p.estado === 'revisado' ? 'acento' : 'alerta'}>{NOMBRE_ESTADO_PENALIZACION[p.estado]}</Insignia> },
          { titulo: 'CFDI', celda: () => <span className="text-xs text-slate-500">descuento en factura: Fase 2</span> },
          { titulo: 'Acciones', celda: (p) => (
            <div className="flex flex-wrap gap-1">
              {revisa && p.estado === 'borrador' && <Boton variante="secundario" onClick={() => void ejecutar(() => cambiarEstadoPenalizacion(p.id, 'revisado'), `Período ${p.periodo} revisado`)}>Revisar</Boton>}
              {revisa && p.estado === 'revisado' && <Boton variante="secundario" onClick={() => void ejecutar(() => cambiarEstadoPenalizacion(p.id, 'cerrado'), `Período ${p.periodo} cerrado`)}>Cerrar</Boton>}
              <button className="text-xs text-primario underline" onClick={() => void archivoPenalizaciones(p.id, 'pdf').then((b) => abrirBlob(b, `penalizaciones-${p.periodo}.pdf`)).catch((e) => setError(mensajeDeError(e)))}>PDF</button>
              <button className="text-xs text-primario underline" onClick={() => void archivoPenalizaciones(p.id, 'xlsx').then((b) => abrirBlob(b, `penalizaciones-${p.periodo}.xlsx`)).catch((e) => setError(mensajeDeError(e)))}>Excel</button>
            </div>
          ) },
        ]} />
        {penalizaciones[0] && penalizaciones[0].detalle_json.length > 0 && (
          <ul className="mt-2 text-xs text-slate-600" data-testid="detalle-penalizacion">{penalizaciones[0].detalle_json.slice(0, 10).map((d) => (
            <li key={d.folio_id}>{d.numero_folio} · límite {d.limite_min} min · efectivo {d.efectivo_min} min · {moneda(d.penalizacion)}</li>
          ))}</ul>
        )}
      </Tarjeta>
    </div>
  )
}

function BandejaExclusiones() {
  const { usuario } = useAuth()
  const [filas, setFilas] = useState<Exclusion[]>([])
  const [pendientes, setPendientes] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [razon, setRazon] = useState<Record<string, string>>({})
  const cargar = useCallback(async () => {
    try { setFilas(await listarExclusiones({ pendientes })) } catch (e) { setError(mensajeDeError(e)) }
  }, [pendientes])
  useEffect(() => { void cargar() }, [cargar])
  const aprueba = usuario ? ROLES_APRUEBAN_EXCLUSION.includes(usuario.rol) : false

  async function decidir(e: Exclusion, aprobada: boolean) {
    setError(null)
    try {
      await decidirExclusion(e.id, aprobada, razon[e.id] ?? '')
      setAviso(aprobada ? 'Exclusión aprobada: el contador y la penalización se recalcularon' : 'Exclusión rechazada')
      await cargar()
    } catch (x) { setError(mensajeDeError(x)) }
  }

  return (
    <Tarjeta titulo="Exclusiones de SLA">
      <p className="mb-2 text-sm text-slate-600">El prestador registra la causa y el período; el Admin empresa decide.
        Solo los períodos aprobados se descuentan del contador, incluso si el folio ya cerró.</p>
      <label className="mb-2 flex items-center gap-1 text-sm"><input type="checkbox" checked={pendientes}
        onChange={(e) => setPendientes(e.target.checked)} /> Solo las pendientes de decisión</label>
      {error && <Aviso>{error}</Aviso>}
      {aviso && <Aviso tipo="exito">{aviso}</Aviso>}
      <div data-testid="bandeja-exclusiones">
        <Tabla filas={filas} vacio="Sin exclusiones registradas" columnas={[
          { titulo: 'Folio', celda: (e) => <span className="font-mono text-xs">{e.numero_folio ?? e.folio_id.slice(0, 8)}</span> },
          { titulo: 'Causa', celda: (e) => NOMBRE_CAUSA[e.causa] },
          { titulo: 'Período', celda: (e) => <span className="text-xs">{fmtFecha(e.timestamp_inicio)} → {fmtFecha(e.timestamp_fin)}</span> },
          { titulo: 'Minutos', celda: (e) => e.minutos },
          { titulo: 'Descripción', celda: (e) => <span className="text-xs">{e.descripcion.slice(0, 80)}</span> },
          { titulo: 'Estado', celda: (e) => <Insignia tono={e.aprobada === true ? 'ok' : e.aprobada === false ? 'neutro' : 'alerta'}>
            {e.aprobada === true ? 'Aprobada' : e.aprobada === false ? 'Rechazada' : 'Por aprobar'}</Insignia> },
          { titulo: 'Decisión', celda: (e) => aprueba && e.aprobada === null ? (
            <div className="flex flex-wrap items-end gap-1">
              <input aria-label={`Razón ${e.numero_folio ?? e.id}`} placeholder="Razón (al rechazar)" value={razon[e.id] ?? ''}
                onChange={(x) => setRazon({ ...razon, [e.id]: x.target.value })}
                className="rounded border border-slate-300 px-2 py-1 text-xs" />
              <Boton onClick={() => void decidir(e, true)}>Aprobar</Boton>
              <Boton variante="peligro" disabled={(razon[e.id] ?? '').trim().length < 3} onClick={() => void decidir(e, false)}>Rechazar</Boton>
            </div>
          ) : <span className="text-xs text-slate-500">{e.razon_decision || '—'}</span> },
        ]} />
      </div>
    </Tarjeta>
  )
}
