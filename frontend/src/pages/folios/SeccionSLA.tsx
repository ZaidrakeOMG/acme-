import { useCallback, useEffect, useState } from 'react'
import { Aviso, Boton, Campo, Insignia, Modal, Selector } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { mensajeDeError } from '../../services/api'
import { registrarExclusion, slaDelFolio } from '../../services/sla'
import type { CausaExclusion, SLAFolio } from '../../types/sla'
import { NOMBRE_CAUSA, NOMBRE_MOTIVO_PAUSA, ROLES_REGISTRAN_EXCLUSION } from '../../types/sla'
import { fecha as fmtFecha } from './comunes'

function horas(min: number | null | undefined) {
  if (min == null) return '—'
  const h = Math.floor(min / 60)
  return h >= 1 ? `${h} h ${min % 60} min` : `${min} min`
}

/** Contador de SLA del folio (§6.10.1): tiempo efectivo, límite, pausas, exclusiones y cumplimiento. P10. */
export function SeccionSLA({ folioId, alCambiar }: { folioId: string; alCambiar?: () => Promise<void> | void }) {
  const { usuario } = useAuth()
  const [d, setD] = useState<SLAFolio | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [abierto, setAbierto] = useState(false)
  const cargar = useCallback(async () => {
    try { setD(await slaDelFolio(folioId)) } catch (e) { setError(mensajeDeError(e)) }
  }, [folioId])
  useEffect(() => { void cargar() }, [cargar])
  if (!usuario) return null
  if (!d) return <p className="text-sm text-slate-500">{error ?? 'Cargando el contador de SLA…'}</p>
  if (!d.disponible) return <p className="text-sm text-slate-500" data-testid="sla-sin-contrato">{d.motivo}</p>
  const registra = ROLES_REGISTRAN_EXCLUSION.includes(usuario.rol)
  const avance = d.limite_sla_min && d.tiempo_efectivo_min != null
    ? Math.min(150, Math.round((d.tiempo_efectivo_min / d.limite_sla_min) * 100)) : 0
  const color = d.cumplimiento === false ? 'bg-red-600' : avance >= 80 ? 'bg-amber-500' : 'bg-green-500'

  return (
    <div className="space-y-3 text-sm" data-testid="sla-folio">
      {error && <Aviso>{error}</Aviso>}
      {aviso && <Aviso tipo="exito">{aviso}</Aviso>}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-2xl font-semibold" data-testid="tiempo-efectivo">{horas(d.tiempo_efectivo_min)}</span>
        <span className="text-slate-500">de {horas(d.limite_sla_min)} de resolución</span>
        {d.cumplimiento === true && <Insignia tono="ok">Dentro del SLA</Insignia>}
        {d.cumplimiento === false && <Insignia tono="alerta">SLA incumplido</Insignia>}
        {d.cumplimiento === null && <Insignia tono="acento">En curso</Insignia>}
        {d.excluir_sla_por_cliente && <Insignia>Excluido por decisión del cliente</Insignia>}
      </div>
      <div>
        <div className="h-2 w-full rounded bg-slate-200"><div className={`h-2 rounded ${color}`} style={{ width: `${Math.min(100, avance)}%` }} /></div>
        <p className="mt-1 text-xs text-slate-600">{avance}% del tiempo de resolución consumido</p>
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        <dt className="text-slate-500">Inicio del contador</dt><dd>{fmtFecha(d.tiempo_inicio)}</dd>
        <dt className="text-slate-500">Respuesta</dt>
        <dd>{d.tiempo_respuesta_at ? `${fmtFecha(d.tiempo_respuesta_at)} · ${horas(d.tiempo_respuesta_efectivo_min)} de ${horas(d.limite_respuesta_min)}` : 'sin asignar'}
          {d.cumplimiento_respuesta === true && <> <Insignia tono="ok">Cumplida</Insignia></>}
          {d.cumplimiento_respuesta === false && <> <Insignia tono="alerta">Fuera de tiempo</Insignia></>}</dd>
        <dt className="text-slate-500">Cierre</dt><dd>{d.tiempo_fin ? fmtFecha(d.tiempo_fin) : 'abierto'}</dd>
        <dt className="text-slate-500">Pausado</dt><dd>{horas(d.tiempo_pausado_min)} <span className="text-xs text-slate-500">({d.pausas.length} pausa(s))</span></dd>
        <dt className="text-slate-500">Excluido</dt><dd>{horas(d.tiempo_exclusion_min)} <span className="text-xs text-slate-500">(solo lo aprobado)</span></dd>
        {d.cumplimiento === false && <><dt className="text-slate-500">Penalización</dt>
          <dd>${Number(d.penalizacion_calculada).toLocaleString('es-MX', { minimumFractionDigits: 2 })}
            {String(d.penalizacion_detalle.tipo ?? '') && <span className="text-xs text-slate-500"> ({String(d.penalizacion_detalle.tipo)} {String(d.penalizacion_detalle.valor ?? '')})</span>}</dd></>}
      </dl>
      {d.pausas.length > 0 && (
        <ul className="text-xs text-slate-600" data-testid="pausas-sla">{d.pausas.map((p) => (
          <li key={p.id}>{NOMBRE_MOTIVO_PAUSA[p.motivo]} · {fmtFecha(p.inicio)} → {p.fin ? fmtFecha(p.fin) : 'en curso'} · {horas(p.minutos)}</li>
        ))}</ul>
      )}
      {d.exclusiones.length > 0 && (
        <ul className="text-xs text-slate-600" data-testid="exclusiones-sla">{d.exclusiones.map((x) => (
          <li key={x.id}>{NOMBRE_CAUSA[x.causa]} · {horas(x.minutos)} ·{' '}
            <Insignia tono={x.aprobada === true ? 'ok' : x.aprobada === false ? 'neutro' : 'alerta'}>
              {x.aprobada === true ? 'Aprobada' : x.aprobada === false ? 'Rechazada' : 'Por aprobar'}
            </Insignia>{x.razon_decision && ` · ${x.razon_decision}`}</li>
        ))}</ul>
      )}
      {registra && (
        <Boton variante="secundario" onClick={() => setAbierto(true)}>Registrar exclusión</Boton>
      )}
      {abierto && (
        <FormExclusion alCerrar={() => setAbierto(false)} alGuardar={async (datos) => {
          setError(null)
          try {
            await registrarExclusion(folioId, datos)
            setAbierto(false)
            setAviso('Exclusión registrada: el Admin empresa debe aprobarla para que descuente del contador')
            await cargar()
            await alCambiar?.()
          } catch (e) { setError(mensajeDeError(e)) }
        }} />
      )}
    </div>
  )
}

function FormExclusion({ alCerrar, alGuardar }: {
  alCerrar: () => void
  alGuardar: (d: { causa: string; descripcion: string; timestamp_inicio: string; timestamp_fin: string }) => Promise<void>
}) {
  const ahora = new Date()
  const local = (d: Date) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
  const [d, setD] = useState({ causa: 'cliente_sin_acceso' as CausaExclusion, descripcion: '',
                               inicio: local(new Date(ahora.getTime() - 4 * 3600000)), fin: local(ahora) })
  const listo = d.descripcion.trim().length >= 10 && d.fin > d.inicio
  return (
    <Modal titulo="Registrar exclusión de SLA" abierto alCerrar={alCerrar}>
      <div className="space-y-3" data-testid="form-exclusion">
        <Aviso tipo="info">El prestador registra la causa y el período; el Admin empresa lo aprueba o lo rechaza (§6.10.1).
          Solo los períodos aprobados se descuentan del contador.</Aviso>
        <Selector etiqueta="Causa" value={d.causa} onChange={(e) => setD({ ...d, causa: e.target.value as CausaExclusion })}
          opciones={(Object.keys(NOMBRE_CAUSA) as CausaExclusion[]).map((c) => ({ valor: c, texto: NOMBRE_CAUSA[c] }))} />
        <div className="grid gap-2 sm:grid-cols-2">
          <Campo etiqueta="Desde" type="datetime-local" value={d.inicio} onChange={(e) => setD({ ...d, inicio: e.target.value })} />
          <Campo etiqueta="Hasta" type="datetime-local" value={d.fin} onChange={(e) => setD({ ...d, fin: e.target.value })} />
        </div>
        <Campo etiqueta="Descripción (mínimo 10 caracteres)" value={d.descripcion} onChange={(e) => setD({ ...d, descripcion: e.target.value })} />
        <div className="flex gap-2">
          <Boton disabled={!listo} onClick={() => void alGuardar({
            causa: d.causa, descripcion: d.descripcion,
            timestamp_inicio: new Date(d.inicio).toISOString(), timestamp_fin: new Date(d.fin).toISOString(),
          })}>Registrar</Boton>
          <Boton variante="secundario" onClick={alCerrar}>Cancelar</Boton>
        </div>
      </div>
    </Modal>
  )
}
