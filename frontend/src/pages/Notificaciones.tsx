import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'
import { Aviso, Boton, Campo, Encabezado, Insignia, Tarjeta } from '../components/ui'
import { mensajeDeError } from '../services/api'
import {
  borrarMiTelefono, fijarConsentimiento, guardarMiTelefono, miTelefono, pedirCodigo, verificarTelefono,
} from '../services/mensajeria'
import { bandejaNotificaciones, eventosNotificables, guardarPreferencia, marcarLeidas, preferencias } from '../services/minutas'
import type { CanalMensajeria, MiTelefono } from '../types/mensajeria'
import type { EventoNotificable, Notificacion, Preferencia } from '../types/minutas'
import { fecha as fmtFecha } from './folios/comunes'

interface CanalDisponible {
  clave: string
  nombre: string
  disponible?: boolean
  requiere_telefono?: boolean
  modo?: string
}

/**
 * Bandeja de notificaciones (canal app) y preferencias de canal por evento (§6.1). Desde F2-02 WhatsApp y SMS son
 * canales normales: el usuario registra su celular, lo verifica con un código y da su consentimiento por canal.
 */
export function Notificaciones() {
  const [lista, setLista] = useState<Notificacion[]>([])
  const [soloNoLeidas, setSoloNoLeidas] = useState(false)
  const [eventos, setEventos] = useState<EventoNotificable[]>([])
  const [canales, setCanales] = useState<CanalDisponible[]>([])
  const [prefs, setPrefs] = useState<Record<string, string[]>>({})
  const [telefono, setTelefono] = useState<MiTelefono | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)

  const cargar = useCallback(async () => {
    try {
      setLista(await bandejaNotificaciones(soloNoLeidas, 100))
      const [ev, pr, tel] = await Promise.all([eventosNotificables(), preferencias(), miTelefono()])
      setEventos(ev.eventos)
      setCanales((ev as unknown as { canales: CanalDisponible[] }).canales ?? [])
      setPrefs(Object.fromEntries(pr.map((p: Preferencia) => [p.evento, p.canales])))
      setTelefono(tel)
    } catch (e) { setError(mensajeDeError(e)) }
  }, [soloNoLeidas])
  useEffect(() => { void cargar() }, [cargar])

  async function alternar(evento: string, canal: string, defecto: string[]) {
    const actual = prefs[evento] ?? defecto
    const nuevos = actual.includes(canal) ? actual.filter((c) => c !== canal) : [...actual, canal]
    try {
      const p = await guardarPreferencia(evento, nuevos)
      setPrefs({ ...prefs, [evento]: p.canales })
      setAviso('Preferencia guardada')
    } catch (e) { setError(mensajeDeError(e)) }
  }

  const sinVerificar = telefono != null && !telefono.verificado

  return (
    <div>
      <Encabezado titulo="Notificaciones"
        descripcion="Avisos del sistema por evento: bandeja interna, push, correo y —si registras tu celular— WhatsApp y SMS."
        acciones={<div className="flex gap-2">
          <Boton variante="secundario" onClick={() => setSoloNoLeidas((v) => !v)}>{soloNoLeidas ? 'Ver todas' : 'Solo no leídas'}</Boton>
          <Boton onClick={() => void marcarLeidas().then(cargar).catch((e) => setError(mensajeDeError(e)))}>Marcar todas como leídas</Boton>
        </div>} />
      {error && <div className="mb-3"><Aviso>{error}</Aviso></div>}
      {aviso && <div className="mb-3"><Aviso tipo="exito">{aviso}</Aviso></div>}
      <div className="grid gap-5 lg:grid-cols-[2fr_1fr]">
        <div className="rounded-xl border border-slate-200 bg-white" data-testid="bandeja">
          {lista.length === 0 && <p className="p-4 text-sm text-slate-500">Sin notificaciones.</p>}
          <ul className="divide-y divide-slate-100">
            {lista.map((n) => (
              <li key={n.id} className={`px-4 py-3 text-sm ${n.leida_at ? '' : 'bg-primario/5'}`}>
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className={n.leida_at ? 'text-slate-800' : 'font-semibold text-slate-900'}>{n.url ? <Link to={n.url} className="hover:underline" onClick={() => void marcarLeidas([n.id])}>{n.asunto}</Link> : n.asunto}</p>
                    {n.cuerpo && <p className="text-slate-600">{n.cuerpo}</p>}
                    <p className="text-xs text-slate-500">{fmtFecha(n.timestamp)} · <Insignia>{n.evento}</Insignia></p>
                  </div>
                  {!n.leida_at && <Boton variante="fantasma" onClick={() => void marcarLeidas([n.id]).then(cargar)}>Leída</Boton>}
                </div>
              </li>
            ))}
          </ul>
        </div>
        <div className="space-y-5">
          <MiCelular telefono={telefono} alCambiar={setTelefono} alAvisar={setAviso} alFallar={setError} />
          <Tarjeta titulo="Preferencias por evento">
            <p className="mb-2 text-xs text-slate-500">Marca por qué canales quieres recibir cada evento.</p>
            {sinVerificar && (
              <p className="mb-2 text-xs text-amber-700">
                WhatsApp y SMS solo llegan si tu celular está verificado y diste tu consentimiento.
              </p>
            )}
            <ul className="space-y-2 text-sm" data-testid="preferencias">
              {eventos.map((e) => {
                const elegidos = prefs[e.clave] ?? e.canales_default
                return (
                  <li key={e.clave} className="border-b border-slate-100 pb-1">
                    <p className="font-medium text-slate-800">{e.nombre}</p>
                    <div className="flex flex-wrap gap-3">
                      {canales.map((c) => (
                        <label key={c.clave} className="flex items-center gap-1 text-xs">
                          <input type="checkbox" checked={elegidos.includes(c.clave)}
                            onChange={() => void alternar(e.clave, c.clave, e.canales_default)}
                            aria-label={`${e.nombre} por ${c.clave}`} />
                          {c.clave}
                          {c.requiere_telefono && c.disponible === false && (
                            <span className="text-slate-400">(inactivo)</span>
                          )}
                        </label>
                      ))}
                    </div>
                  </li>
                )
              })}
            </ul>
          </Tarjeta>
        </div>
      </div>
    </div>
  )
}

/** Mi celular: alta, verificación por código de un solo uso y consentimiento por canal (§6.9.5). */
function MiCelular({ telefono, alCambiar, alAvisar, alFallar }: {
  telefono: MiTelefono | null
  alCambiar: (t: MiTelefono) => void
  alAvisar: (t: string | null) => void
  alFallar: (t: string | null) => void
}) {
  const [numero, setNumero] = useState('')
  const [codigo, setCodigo] = useState('')
  const [pidiendo, setPidiendo] = useState(false)
  const [canalCodigo, setCanalCodigo] = useState<CanalMensajeria>('sms')

  async function ejecutar(accion: () => Promise<MiTelefono>, mensaje: string) {
    alFallar(null)
    try {
      alCambiar(await accion())
      alAvisar(mensaje)
    } catch (e) { alFallar(mensajeDeError(e)) }
  }

  if (!telefono) return null

  return (
    <Tarjeta titulo="Mi celular para WhatsApp y SMS">
      {!telefono.tiene_telefono ? (
        <div className="space-y-2">
          <Campo etiqueta="Celular (formato internacional)" value={numero} placeholder="+52 871 123 4567"
            onChange={(e) => setNumero(e.target.value)} />
          <Boton onClick={() => void ejecutar(() => guardarMiTelefono(numero), 'Celular guardado: ahora verifícalo')}>
            Guardar
          </Boton>
        </div>
      ) : (
        <div className="space-y-3 text-sm" data-testid="mi-telefono">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-slate-800">{telefono.telefono_mascara}</span>
            {telefono.verificado
              ? <Insignia tono="ok">Verificado</Insignia>
              : <Insignia tono="alerta">Sin verificar</Insignia>}
          </div>

          {!telefono.verificado && (
            <div className="space-y-2 rounded-lg bg-slate-50 p-3">
              <p className="text-xs text-slate-600">
                Te mandamos un código de 6 dígitos por el canal que elijas; vence en 10 minutos.
              </p>
              <div className="flex flex-wrap items-end gap-2">
                <label className="text-xs">
                  <span className="mb-1 block font-medium text-slate-700">Por</span>
                  <select className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm" value={canalCodigo}
                    aria-label="Canal del código" onChange={(e) => setCanalCodigo(e.target.value as CanalMensajeria)}>
                    <option value="sms">SMS</option>
                    <option value="whatsapp">WhatsApp</option>
                  </select>
                </label>
                <Boton variante="secundario" disabled={pidiendo} onClick={() => {
                  setPidiendo(true)
                  alFallar(null)
                  void pedirCodigo(canalCodigo)
                    .then((r) => alAvisar(r.modo === 'stub'
                      ? 'Código generado (modo simulado: míralo en la bitácora de mensajería)'
                      : `Código enviado por ${r.canal}`))
                    .catch((e) => alFallar(mensajeDeError(e)))
                    .finally(() => setPidiendo(false))
                }}>Enviarme el código</Boton>
              </div>
              <div className="flex flex-wrap items-end gap-2">
                <Campo etiqueta="Código" value={codigo} inputMode="numeric" maxLength={6}
                  onChange={(e) => setCodigo(e.target.value)} />
                <Boton onClick={() => void ejecutar(() => verificarTelefono(codigo), 'Celular verificado')}>
                  Verificar
                </Boton>
              </div>
            </div>
          )}

          <div className="space-y-1">
            {(['whatsapp', 'sms'] as CanalMensajeria[]).map((canal) => (
              <label key={canal} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={telefono[canal].activo} disabled={!telefono.verificado}
                  aria-label={`Consentimiento para ${canal}`}
                  onChange={(e) => void ejecutar(() => fijarConsentimiento(canal, e.target.checked),
                    e.target.checked ? `Activaste ${canal}` : `Te diste de baja de ${canal}`)} />
                Acepto recibir avisos operativos por {canal === 'whatsapp' ? 'WhatsApp' : 'SMS'}
                {telefono[canal].baja_at && !telefono[canal].activo && (
                  <span className="text-xs text-slate-500">· baja el {fmtFecha(telefono[canal].baja_at)}</span>
                )}
              </label>
            ))}
          </div>

          <details className="text-xs text-slate-600">
            <summary className="cursor-pointer font-medium text-slate-700">Aviso de privacidad</summary>
            <p className="mt-1">{telefono.aviso_privacidad}</p>
          </details>

          <Boton variante="fantasma"
            onClick={() => void ejecutar(borrarMiTelefono, 'Celular eliminado')}>Quitar mi celular</Boton>
        </div>
      )}
    </Tarjeta>
  )
}
