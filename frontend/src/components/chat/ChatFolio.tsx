import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { api, mensajeDeError } from '../../services/api'
import { agregarParticipante, chatsDelFolio, conectarTiempoReal, confirmarPendiente, descargarAdjunto, enviarImagen, enviarMensaje, marcarLeido, mensajesDe, NOMBRE_CANAL, quitarParticipante, type CanalChat, type Chat, type MensajeChat } from '../../services/chat'
import { syncEngine } from '../../services/syncEngine'
import type { Tecnico } from '../../types/api'
import { Aviso, Boton, Insignia } from '../ui'
import { marcarMensaje } from '../../services/minutas'
import { ROLES_MARCAN_CHAT } from '../../types/minutas'

function hora(iso: string | null | undefined) {
  return iso ? new Date(iso).toLocaleString('es-MX', { dateStyle: 'short', timeStyle: 'short' }) : ''
}

/** Burbuja con doble timestamp (§6.8.1): hora de escritura en el dispositivo y hora de entrega al servidor. */
function Burbuja({ m, propio, alMarcar }: { m: MensajeChat; propio: boolean; alMarcar?: (m: MensajeChat, como: 'hallazgo' | 'peticion') => void }) {
  const retrasado = m.timestamp_dispositivo && Math.abs(new Date(m.timestamp_servidor).getTime() - new Date(m.timestamp_dispositivo).getTime()) > 60000
  const marcado = typeof m.datos_json.marcado_como === 'string' ? m.datos_json.marcado_como : null
  if (m.tipo === 'sistema') {
    return <li data-testid="mensaje-sistema" className="my-1 text-center text-xs text-slate-500"><span className="rounded-full bg-slate-100 px-2 py-0.5">{m.contenido_texto} · {hora(m.timestamp_servidor)}</span></li>
  }
  return (
    <li data-testid={m.pendiente ? 'mensaje-pendiente' : 'mensaje'} className={`flex ${propio ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[80%] rounded-2xl px-3 py-2 text-sm ${propio ? 'bg-primario text-white' : 'bg-slate-100 text-slate-900'} ${m.pendiente ? 'opacity-70' : ''}`}>
        {!propio && m.usuario_nombre && <p className="text-xs font-semibold opacity-80">{m.usuario_nombre}</p>}
        {m.contenido_texto && <p className="whitespace-pre-wrap">{m.contenido_texto}</p>}
        {m.archivos.map((a) => <AdjuntoChat key={a.id} chatId={m.chat_id} archivo={a} />)}
        {m.datos_json.evidencia_posterior === true && <p className="mt-1 text-[10px] uppercase tracking-wide opacity-80">Evidencia posterior al cierre</p>}
        {marcado && <p className="mt-1 text-[10px] uppercase tracking-wide opacity-80">Marcado como {marcado === 'peticion' ? 'petición especial' : 'hallazgo'}</p>}
        {!marcado && alMarcar && m.contenido_texto && !m.pendiente && (
          <p className="mt-1 flex gap-2 text-[10px]"><button className="underline opacity-80" onClick={() => alMarcar(m, 'hallazgo')}>Marcar como hallazgo</button><button className="underline opacity-80" onClick={() => alMarcar(m, 'peticion')}>Petición especial</button></p>
        )}
        <p className="mt-1 text-[10px] opacity-75">
          {m.pendiente ? `Escrito ${hora(m.timestamp_dispositivo)} · pendiente de envío` : retrasado ? `Escrito ${hora(m.timestamp_dispositivo)} · entregado ${hora(m.timestamp_servidor)}` : hora(m.timestamp_servidor)}
        </p>
      </div>
    </li>
  )
}

function AdjuntoChat({ chatId, archivo }: { chatId: string; archivo: MensajeChat['archivos'][number] }) {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    let revocar: string | null = null
    descargarAdjunto(chatId, archivo.id).then((b) => { revocar = URL.createObjectURL(b); setUrl(revocar) }).catch(() => undefined)
    return () => { if (revocar) URL.revokeObjectURL(revocar) }
  }, [chatId, archivo.id])
  if (archivo.tipo_mime.startsWith('image/') && url) return <img src={url} alt={archivo.nombre_original} className="mt-1 max-h-48 rounded-lg" />
  return <p className="mt-1 text-xs underline">{archivo.nombre_original} ({Math.round(archivo.tamano_bytes / 1024)} KB)</p>
}

/**
 * Chat del folio: pestañas por canal (según participación/permisos), tiempo real por WebSocket con fallback SSE,
 * adjuntos, eventos de sistema, leído y gestión de participantes. `canales` limita las pestañas (app de campo: solo `campo`).
 */
export function ChatFolio({ folioId, canales, compacto = false }: { folioId: string; canales?: CanalChat[]; compacto?: boolean }) {
  const { usuario } = useAuth()
  const [chats, setChats] = useState<Chat[]>([])
  const [activo, setActivo] = useState<Chat | null>(null)
  const [mensajes, setMensajes] = useState<MensajeChat[]>([])
  const [texto, setTexto] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [modo, setModo] = useState<'websocket' | 'sse' | 'ninguno'>('ninguno')
  const [gestionando, setGestionando] = useState(false)
  const [tecnicos, setTecnicos] = useState<Tecnico[]>([])
  const [nuevoId, setNuevoId] = useState('')
  const fin = useRef<HTMLLIElement>(null)

  const cargarChats = useCallback(async () => {
    try {
      const lista = (await chatsDelFolio(folioId)).filter((c) => !canales || canales.includes(c.canal))
      setChats(lista)
      setActivo((prev) => lista.find((c) => c.id === prev?.id) ?? lista.find((c) => c.es_participante) ?? lista[0] ?? null)
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }, [folioId, canales])
  useEffect(() => { void cargarChats() }, [cargarChats])

  useEffect(() => {
    if (!activo || !activo.es_participante) { setMensajes([]); return }
    let vivo = true
    mensajesDe(activo.id).then((m) => { if (vivo) setMensajes(m) }).catch((e) => setError(mensajeDeError(e)))
    if (syncEngine.enLinea()) marcarLeido(activo.id).catch(() => undefined)
    const cerrar = conectarTiempoReal(activo.id, (ev) => {
      if (ev.evento === 'mensaje') {
        setMensajes((prev) => {
          const sinPendiente = prev.filter((x) => x.id_cliente !== ev.mensaje.id_cliente)
          if (ev.mensaje.id_cliente) void confirmarPendiente(ev.mensaje.id_cliente)
          return [...sinPendiente, ev.mensaje]
        })
        if (ev.mensaje.usuario_id !== usuario?.id) marcarLeido(activo.id).catch(() => undefined)
      } else if (ev.evento === 'leido') {
        setMensajes((prev) => prev.map((m) => ({ ...m, leido_por_json: { ...m.leido_por_json, [ev.usuario_id]: ev.hasta } })))
      }
    }, setModo)
    return () => { vivo = false; cerrar() }
  }, [activo?.id, activo?.es_participante, usuario?.id])

  useEffect(() => { fin.current?.scrollIntoView({ block: 'end' }) }, [mensajes.length])

  async function enviar() {
    if (!activo || !texto.trim()) return
    const contenido = texto.trim()
    setTexto('')
    try {
      const m = await enviarMensaje(activo.id, contenido)
      setMensajes((prev) => (prev.some((x) => x.id === m.id) ? prev : [...prev, { ...m, usuario_id: m.usuario_id ?? usuario?.id ?? null }]))
    } catch (e) {
      setError(mensajeDeError(e))
      setTexto(contenido)
    }
  }

  async function adjuntar(archivo: File) {
    if (!activo) return
    try {
      const m = await enviarImagen(activo.id, archivo, archivo.name)
      setMensajes((prev) => (prev.some((x) => x.id === m.id) ? prev : [...prev, m]))
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  async function agregar() {
    if (!activo || !nuevoId) return
    try {
      await agregarParticipante(activo.id, nuevoId)
      setNuevoId('')
      await cargarChats()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  if (!usuario) return null
  const cerrado = activo?.estado === 'archivado'
  return (
    <section data-testid="chat-folio" className={`flex flex-col rounded-xl border border-slate-200 bg-white ${compacto ? 'h-[60vh]' : 'h-[32rem]'}`}>
      <div className="flex flex-wrap items-center gap-1 border-b border-slate-200 p-2">
        {chats.map((c) => (
          <button key={c.id} onClick={() => setActivo(c)} className={`rounded-lg px-3 py-1.5 text-xs font-medium ${activo?.id === c.id ? 'bg-primario text-white' : 'bg-slate-100 text-slate-700'}`}>
            {NOMBRE_CANAL[c.canal]}{c.no_leidos > 0 && <span className="ml-1 rounded-full bg-acento px-1.5 text-[10px] text-slate-900">{c.no_leidos}</span>}
          </button>
        ))}
        <span className="ml-auto text-[10px] uppercase tracking-wide text-slate-400">{modo === 'websocket' ? 'tiempo real' : modo === 'sse' ? 'tiempo real (SSE)' : 'sin tiempo real'}</span>
        {activo && (activo.puede_gestionar || activo.es_participante) && (
          <button className="text-xs text-primario underline" onClick={() => { setGestionando((v) => !v); if (tecnicos.length === 0 && ['admin_prestador', 'despachador', 'superadmin'].includes(usuario.rol)) api<Tecnico[]>('/catalogos/tecnicos').then(setTecnicos).catch(() => undefined) }}>
            Participantes ({activo.participantes.length})
          </button>
        )}
      </div>
      {error && <div className="p-2"><Aviso>{error}</Aviso></div>}
      {gestionando && activo && (
        <div className="border-b border-slate-200 bg-slate-50 p-2 text-xs">
          <ul className="flex flex-wrap gap-1">
            {activo.participantes.map((p) => (
              <li key={p.usuario_id} className="flex items-center gap-1 rounded-full bg-white px-2 py-0.5">
                <span>{p.nombre}</span><Insignia>{p.rol}</Insignia>
                {activo.puede_gestionar && !p.fijo && <button aria-label={`Quitar a ${p.nombre}`} className="text-red-700" onClick={() => void quitarParticipante(activo.id, p.usuario_id).then(cargarChats).catch((e) => setError(mensajeDeError(e)))}>✕</button>}
              </li>
            ))}
          </ul>
          {activo.puede_gestionar && (
            <div className="mt-2 flex gap-2">
              {tecnicos.length > 0 ? (
                <select aria-label="Agregar técnico" value={nuevoId} onChange={(e) => setNuevoId(e.target.value)} className="rounded border border-slate-300 px-2 py-1">
                  <option value="">Agregar técnico…</option>
                  {tecnicos.map((t) => <option key={t.usuario_id} value={t.usuario_id}>{t.nombre}</option>)}
                </select>
              ) : (
                <input aria-label="Id del usuario a agregar" placeholder="Id del usuario" value={nuevoId} onChange={(e) => setNuevoId(e.target.value)} className="rounded border border-slate-300 px-2 py-1" />
              )}
              <Boton variante="secundario" onClick={() => void agregar()} disabled={!nuevoId}>Agregar</Boton>
            </div>
          )}
        </div>
      )}
      {!activo ? (
        <p className="p-4 text-sm text-slate-500">Sin chats disponibles.</p>
      ) : !activo.es_participante ? (
        <p className="p-4 text-sm text-slate-500">No participas en este canal{activo.puede_gestionar ? '; puedes agregarte desde «Participantes».' : '.'}</p>
      ) : (
        <>
          <ul className="flex-1 space-y-1 overflow-y-auto p-3">
            {mensajes.map((m) => <Burbuja key={m.id} m={m} propio={m.usuario_id === usuario.id || (m.pendiente === true)}
                                          alMarcar={ROLES_MARCAN_CHAT.includes(usuario.rol) && activo ? (msg, como) => { void marcarMensaje(activo.id, msg.id, como).then(() => setMensajes((l) => l.map((x) => (x.id === msg.id ? { ...x, datos_json: { ...x.datos_json, marcado_como: como } } : x)))).catch((e) => setError(mensajeDeError(e))) } : undefined} />)}
            <li ref={fin} />
          </ul>
          <form className="flex items-center gap-2 border-t border-slate-200 p-2" onSubmit={(e) => { e.preventDefault(); void enviar() }}>
            <label className="cursor-pointer rounded-lg bg-slate-100 px-2 py-2 text-xs" title="Adjuntar imagen">
              📷<input type="file" accept="image/*" className="hidden" aria-label="Adjuntar imagen" onChange={(e) => { const f = e.target.files?.[0]; if (f) void adjuntar(f); e.target.value = '' }} />
            </label>
            <input aria-label="Mensaje" value={texto} onChange={(e) => setTexto(e.target.value)} disabled={cerrado} placeholder={cerrado ? 'Chat archivado' : 'Escribe un mensaje…'}
                   className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            <Boton type="submit" disabled={cerrado || !texto.trim()}>Enviar</Boton>
          </form>
        </>
      )}
    </section>
  )
}
