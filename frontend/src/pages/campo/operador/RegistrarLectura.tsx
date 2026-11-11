import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { Aviso, Boton, Campo, Insignia } from '../../../components/ui'
import { useConexion } from '../../../hooks/useConexion'
import { mensajeDeError } from '../../../services/api'
import { medidoresDelOperador, registrarLecturaCampo } from '../../../services/campo'
import type { EquipoDelOperador } from '../../../types/medidores'
import { formatoValor } from '../../../types/medidores'
import { fecha as fmtFecha } from '../../folios/comunes'

/**
 * «Registrar lectura» de la app del operador (§6.9.2, método «lectura manual por el operador»): los equipos de su
 * unidad cuyo marcador él puede leer. Funciona sin señal: la lista viaja en el paquete de catálogos y la lectura se
 * encola con la hora del dispositivo.
 *
 * La foto del marcador se pide cuando el tipo de medidor la exige; en esta pantalla es el aviso lo que lo dice, y la
 * foto se sube como evidencia desde el formulario de atención del técnico, que es donde vive el motor de evidencias.
 */
export function RegistrarLectura() {
  const { enLinea } = useConexion()
  const [lista, setLista] = useState<EquipoDelOperador[] | null>(null)
  const [valores, setValores] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [enviando, setEnviando] = useState<string | null>(null)

  useEffect(() => {
    medidoresDelOperador().then(setLista).catch((e) => setError(mensajeDeError(e)))
  }, [enLinea])

  async function registrar(m: EquipoDelOperador) {
    const valor = valores[m.equipo_medidor_id]
    if (!valor) return
    setError(null)
    setEnviando(m.equipo_medidor_id)
    try {
      const { valor: r, encolada } = await registrarLecturaCampo(m.equipo_medidor_id, valor, `${m.equipo_codigo} ${m.medidor}`)
      if (encolada) {
        setAviso(`Sin señal: la lectura de ${m.equipo_codigo} quedó en la cola y se enviará al reconectar.`)
      } else if (r?.anomalia) {
        setAviso(`La lectura de ${m.equipo_codigo} quedó en revisión: ${r.anomalia}`)
      } else {
        setAviso(`Lectura registrada: ${m.equipo_codigo} en ${formatoValor(valor, m.decimales, m.unidad)}`
          + (r?.folios_generados[0] ? ` · se generó el mantenimiento preventivo ${r.folios_generados[0].numero_folio}` : ''))
      }
      setValores({ ...valores, [m.equipo_medidor_id]: '' })
      const refrescada = await medidoresDelOperador()
      setLista(refrescada)
    } catch (e) { setError(mensajeDeError(e)) } finally { setEnviando(null) }
  }

  return (
    <div className="mx-auto max-w-lg space-y-4">
      <div>
        <Link to="/campo" className="text-xs text-primario underline">← Mi unidad</Link>
        <h1 className="mt-1 text-xl font-semibold text-slate-900">Registrar lectura</h1>
        <p className="text-sm text-slate-600">
          Anota lo que marca el medidor de cada equipo. Con estas lecturas, los mantenimientos se programan por el uso
          real y no solo por el calendario. Si no hay señal, la lectura se guarda y se envía al reconectar.
        </p>
      </div>
      {error && <Aviso>{error}</Aviso>}
      {aviso && <Aviso tipo="exito">{aviso}</Aviso>}
      {lista && lista.length === 0 && <p className="text-sm text-slate-500">No hay equipos con medidor asignados a tu unidad.</p>}
      {(lista ?? []).map((m) => (
        <article key={m.equipo_medidor_id} className="rounded-xl border border-slate-200 bg-white p-4" data-testid={`medidor-operador-${m.equipo_codigo}`}>
          <p className="font-medium text-slate-900">{m.equipo_codigo} · {m.equipo}</p>
          <p className="text-sm text-slate-600">{m.medidor} · va en <strong>{formatoValor(m.valor_actual, m.decimales, m.unidad)}</strong></p>
          <p className="text-xs text-slate-500">
            {m.fecha_ultima_lectura ? `Última lectura ${fmtFecha(m.fecha_ultima_lectura)}` : 'Sin lecturas todavía'}
            {m.valor_maximo && ` · el marcador llega hasta ${formatoValor(m.valor_maximo, m.decimales, m.unidad)}`}
          </p>
          {m.requiere_foto && <div className="mt-2"><Insignia tono="alerta">Este medidor pide foto del marcador</Insignia></div>}
          <div className="mt-3 flex items-end gap-2">
            <Campo etiqueta={`Lectura (${m.unidad})`} type="number" inputMode="decimal" className="flex-1"
              value={valores[m.equipo_medidor_id] ?? ''}
              onChange={(e) => setValores({ ...valores, [m.equipo_medidor_id]: e.target.value })} />
            <Boton disabled={!valores[m.equipo_medidor_id] || enviando === m.equipo_medidor_id} onClick={() => void registrar(m)}>
              {enviando === m.equipo_medidor_id ? 'Guardando…' : 'Guardar'}
            </Boton>
          </div>
        </article>
      ))}
    </div>
  )
}
