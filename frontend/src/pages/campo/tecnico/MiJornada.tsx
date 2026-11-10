import { useCallback, useEffect, useRef, useState } from 'react'
import { Aviso, Boton, Insignia } from '../../../components/ui'
import { useConexion } from '../../../hooks/useConexion'
import { mensajeDeError } from '../../../services/api'
import {
  cerrarJornada, iniciarJornada, miJornada, misAlertas, pausarJornada, reanudarJornada, responderAlerta,
} from '../../../services/operacion'
import { detenerSeguimiento, enviarPendientes, iniciarSeguimiento, pendientes } from '../../../services/posiciones'
import type { AlertaDelTecnico, MiJornada as Estado, MotivoPausa, SugerenciaLlegada } from '../../../types/operaciones'
import { COLOR_ESTATUS, MOTIVOS_PAUSA, NOMBRE_ESTATUS } from '../../../types/operaciones'
import { fecha as fmtFecha } from '../../folios/comunes'

/**
 * Jornada del técnico en «Mis folios» (§6.8.4): iniciar, pausar y cerrar, con el aviso de qué se registra la
 * primera vez. Mientras la jornada está abierta, la app manda su posición con las frecuencias del diseño; sin
 * señal las guarda y las envía al reconectar.
 */
export function MiJornada({ alSugerirLlegada }: { alSugerirLlegada?: (s: SugerenciaLlegada) => void }) {
  const { enLinea } = useConexion()
  const [estado, setEstado] = useState<Estado | null>(null)
  const [alertas, setAlertas] = useState<AlertaDelTecnico[]>([])
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [mostrarAviso, setMostrarAviso] = useState(false)
  const [sinEnviar, setSinEnviar] = useState(0)
  const [sugerencia, setSugerencia] = useState<SugerenciaLlegada | null>(null)
  const [motivo, setMotivo] = useState<MotivoPausa>('comida')
  const [ocupado, setOcupado] = useState(false)
  const siguiendoRef = useRef(false)

  const cargar = useCallback(async () => {
    try {
      const e = await miJornada()
      setEstado(e)
      setAlertas(await misAlertas())
      setSinEnviar((await pendientes()).length)
    } catch (e) { setError(mensajeDeError(e)) }
  }, [])

  useEffect(() => { void cargar() }, [cargar])

  // Seguimiento del GPS: arranca con la jornada y se detiene al cerrarla (§6.8.4: fuera de jornada no se registra).
  useEffect(() => {
    const abierta = estado?.jornada && estado.jornada.estado !== 'cerrada'
    if (!estado || !abierta) {
      if (siguiendoRef.current) {
        detenerSeguimiento()
        siguiendoRef.current = false
      }
      return
    }
    siguiendoRef.current = true
    void iniciarSeguimiento({
      parametros: estado,
      jornadaId: estado.jornada!.id,
      enPausa: estado.jornada!.estado === 'pausa',
      alEnviar: (aceptadas, s) => {
        if (aceptadas > 0) setSinEnviar(0)
        if (s) { setSugerencia(s); alSugerirLlegada?.(s) }
      },
      alGuardarSinSenal: setSinEnviar,
      alFallar: setError,
    })
  }, [estado, alSugerirLlegada])

  useEffect(() => () => { detenerSeguimiento() }, [])

  // Al volver la conexión, lo que se guardó sin señal sale marcado como tardío.
  useEffect(() => {
    if (!enLinea) return
    void enviarPendientes().then(async (cuantas) => {
      if (cuantas > 0) setAviso(`Se enviaron ${cuantas} posición(es) que quedaron guardadas sin señal`)
      setSinEnviar((await pendientes()).length)
    }).catch(() => undefined)
  }, [enLinea])

  async function ejecutar(accion: () => Promise<Estado>, mensaje: string) {
    setError(null)
    setOcupado(true)
    try {
      setEstado(await accion())
      setAviso(mensaje)
    } catch (e) { setError(mensajeDeError(e)) } finally { setOcupado(false) }
  }

  if (!estado) return null
  const jornada = estado.jornada
  const abierta = jornada != null && jornada.estado !== 'cerrada'
  const enPausa = jornada?.estado === 'pausa'

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4" data-testid="mi-jornada">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">Mi jornada</p>
          <p className="text-base font-semibold text-slate-900">
            {abierta ? `Iniciada ${fmtFecha(jornada!.inicio)}` : 'Sin iniciar'}
          </p>
        </div>
        <span className={`rounded-full border px-2 py-0.5 text-xs ${COLOR_ESTATUS[estado.estatus]}`}>
          {NOMBRE_ESTATUS[estado.estatus]}
        </span>
      </div>

      {error && <div className="mt-2"><Aviso>{error}</Aviso></div>}
      {aviso && <div className="mt-2"><Aviso tipo="exito">{aviso}</Aviso></div>}

      {alertas.map((a) => (
        <div key={a.id} className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3" data-testid="alerta-tecnico">
          <p className="text-sm font-medium text-amber-900">{a.pregunta}</p>
          <div className="mt-2 flex gap-2">
            <Boton className="min-h-12" onClick={() => void responderAlerta(a.id, 'estoy_bien')
              .then(() => { setAlertas(alertas.filter((x) => x.id !== a.id)); setAviso('Gracias, avisamos que estás bien') })
              .catch((e) => setError(mensajeDeError(e)))}>Estoy bien</Boton>
            <Boton variante="secundario" className="min-h-12"
              onClick={() => void responderAlerta(a.id, 'necesito_apoyo')
                .then(() => { setAlertas(alertas.filter((x) => x.id !== a.id)); setAviso('Avisamos al despachador que necesitas apoyo') })
                .catch((e) => setError(mensajeDeError(e)))}>Necesito apoyo</Boton>
          </div>
        </div>
      ))}

      {sugerencia && (
        <div className="mt-3 rounded-lg border border-emerald-300 bg-emerald-50 p-3">
          <p className="text-sm text-emerald-900">{sugerencia.mensaje} ({sugerencia.sucursal})</p>
          <p className="mt-1 text-xs text-emerald-800">
            Estás a {sugerencia.distancia_m} m. La llegada la confirmas tú en el folio {sugerencia.numero_folio}.
          </p>
        </div>
      )}

      {!abierta ? (
        <div className="mt-3 space-y-2">
          {mostrarAviso || !estado.aviso_aceptado ? (
            <details className="rounded-lg bg-slate-50 p-3 text-xs text-slate-700" open={!estado.aviso_aceptado}>
              <summary className="cursor-pointer font-medium">Qué se registra mientras tu jornada está abierta</summary>
              <p className="mt-1">{estado.aviso_geolocalizacion}</p>
            </details>
          ) : null}
          <Boton className="min-h-12 w-full text-base" disabled={ocupado || !enLinea}
            onClick={() => void ejecutar(() => iniciarJornada(dispositivo(), true), 'Jornada iniciada')}>
            {estado.aviso_aceptado ? 'Iniciar mi jornada' : 'Acepto y inicio mi jornada'}
          </Boton>
          {!estado.aviso_aceptado && (
            <button className="text-xs text-primario underline" onClick={() => setMostrarAviso(true)}>
              Leer otra vez el aviso
            </button>
          )}
          {!enLinea && <p className="text-xs text-slate-500">Necesitas señal para iniciar la jornada.</p>}
        </div>
      ) : (
        <div className="mt-3 space-y-2">
          <p className="text-xs text-slate-500">
            Mandando tu posición cada {enPausa ? estado.frecuencias.pausa_s / 60 + ' min (en pausa)'
              : estado.frecuencias.jornada_activa_s + ' s'}
            {' · '}{jornada!.posiciones} enviada(s)
            {sinEnviar > 0 && ` · ${sinEnviar} guardada(s) sin señal`}
          </p>
          {sinEnviar > 0 && (
            <Insignia tono="alerta">{sinEnviar} posición(es) esperando señal</Insignia>
          )}
          <div className="flex flex-wrap gap-2">
            {enPausa ? (
              <Boton className="min-h-12" disabled={ocupado}
                onClick={() => void ejecutar(reanudarJornada, 'Jornada reanudada')}>Reanudar</Boton>
            ) : (
              <>
                <select className="min-h-12 rounded-lg border border-slate-300 px-2 text-sm" value={motivo}
                  aria-label="Motivo de la pausa" onChange={(e) => setMotivo(e.target.value as MotivoPausa)}>
                  {MOTIVOS_PAUSA.map((m) => <option key={m.valor} value={m.valor}>{m.texto}</option>)}
                </select>
                <Boton variante="secundario" className="min-h-12" disabled={ocupado}
                  onClick={() => void ejecutar(() => pausarJornada(motivo), 'Jornada en pausa')}>Pausar</Boton>
              </>
            )}
            <Boton variante="secundario" className="min-h-12" disabled={ocupado}
              onClick={() => void ejecutar(cerrarJornada, 'Jornada cerrada')}>Cerrar jornada</Boton>
          </div>
          {enPausa && jornada?.pausa_desde && (
            <p className="text-xs text-slate-500">En pausa desde {fmtFecha(jornada.pausa_desde)}
              {jornada.pausa_motivo && ` (${jornada.pausa_motivo})`}</p>
          )}
        </div>
      )}
    </section>
  )
}

/** Identificador del teléfono, para saber desde qué dispositivo se abrió la jornada. */
function dispositivo(): string {
  try {
    const clave = 'acma.dispositivo'
    let id = localStorage.getItem(clave)
    if (!id) {
      id = crypto.randomUUID().slice(0, 8)
      localStorage.setItem(clave, id)
    }
    return `${id} · ${navigator.platform || 'teléfono'}`.slice(0, 80)
  } catch {
    return 'teléfono'
  }
}
