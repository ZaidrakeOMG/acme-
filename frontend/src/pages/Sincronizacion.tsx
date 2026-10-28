import { useCallback, useEffect, useState } from 'react'
import { Aviso, Boton, Encabezado, Insignia, Tarjeta } from '../components/ui'
import { useConexion } from '../hooks/useConexion'
import { syncEngine } from '../services/syncEngine'
import type { EvidenciaPendiente, MutacionPendiente } from '../services/db'

const NOMBRE_TIPO: Record<string, string> = {
  crear_folio: 'Captura de folio', transicion: 'Cambio de estado', guardar_respuesta: 'Formulario (borrador)', enviar_respuesta: 'Formulario enviado',
  subir_evidencia: 'Evidencia', agregar_refaccion: 'Refacción', mensaje_chat: 'Mensaje de chat',
}

/** "Pendientes de sincronizar": cola en orden, estado de cada operación, reintento manual y descarte. */
export function Sincronizacion() {
  const estado = useConexion()
  const [mutaciones, setMutaciones] = useState<MutacionPendiente[]>([])
  const [evidencias, setEvidencias] = useState<EvidenciaPendiente[]>([])
  const [mensaje, setMensaje] = useState<string | null>(null)

  const cargar = useCallback(async () => {
    const p = await syncEngine.pendientes()
    setMutaciones(p.mutaciones)
    setEvidencias(p.evidencias)
  }, [])
  useEffect(() => { void cargar() }, [cargar, estado.pendientes, estado.errores, estado.sincronizando])

  async function sincronizarAhora() {
    const r = await syncEngine.procesar()
    setMensaje(r.enLinea ? `Sincronización ejecutada: ${r.pendientes} pendiente(s), ${r.errores} con error` : 'Sin conexión: se reintentará al recuperar la señal')
    await cargar()
  }

  const tono = (e: string) => (e === 'pendiente' || e === 'enviando' ? 'alerta' : e === 'rechazada' || e === 'atencion' || e === 'error' ? 'alerta' : 'ok')
  return (
    <div className="space-y-4">
      <Encabezado titulo="Pendientes de sincronizar" descripcion="Todo lo capturado sin señal se guarda en este dispositivo y se envía en orden al recuperar la conexión. Nada se pierde."
                  acciones={<Boton onClick={() => void sincronizarAhora()} disabled={estado.sincronizando}>{estado.sincronizando ? 'Sincronizando…' : 'Sincronizar ahora'}</Boton>} />
      <p className="text-sm text-slate-600">
        Estado: <strong>{estado.enLinea ? 'en línea' : 'sin conexión'}</strong> · {estado.pendientes} pendiente(s) · {estado.errores} con error
        {estado.ultimoSync && <> · última sincronización {new Date(estado.ultimoSync).toLocaleString('es-MX')}</>}
      </p>
      {mensaje && <Aviso tipo="info">{mensaje}</Aviso>}
      <Tarjeta titulo="Operaciones en cola">
        {mutaciones.length === 0 && evidencias.length === 0 && <p className="text-sm text-slate-500">No hay operaciones pendientes.</p>}
        <ul className="divide-y divide-slate-100 text-sm">
          {mutaciones.map((m) => (
            <li key={m.id_cliente} data-testid={`pendiente-${m.id_cliente}`} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <div>
                <p className="font-medium text-slate-800">{NOMBRE_TIPO[m.tipo] ?? m.tipo} · <span className="font-normal text-slate-600">{m.descripcion}</span></p>
                <p className="text-xs text-slate-500">Escrito {new Date(m.timestamp_dispositivo).toLocaleString('es-MX')} · intentos {m.intentos}{m.ultimo_error && <> · {m.ultimo_error}</>}</p>
              </div>
              <div className="flex items-center gap-2">
                <Insignia tono={tono(m.estado)}>{m.estado === 'atencion' ? 'requiere atención' : m.estado}</Insignia>
                {(m.estado === 'atencion' || m.estado === 'rechazada' || m.estado === 'pendiente') && <Boton variante="secundario" onClick={() => void syncEngine.reintentar(m.id_cliente).then(cargar)}>Reintentar</Boton>}
                {(m.estado === 'atencion' || m.estado === 'rechazada') && <Boton variante="fantasma" onClick={() => void syncEngine.descartar(m.id_cliente).then(cargar)}>Descartar</Boton>}
              </div>
            </li>
          ))}
          {evidencias.map((e) => (
            <li key={e.id_cliente} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <div>
                <p className="font-medium text-slate-800">Evidencia · <span className="font-normal text-slate-600">{e.nombre} ({Math.round(e.blob.size / 1024)} KB)</span></p>
                <p className="text-xs text-slate-500">Capturada {new Date(e.creado).toLocaleString('es-MX')} · intentos {e.intentos}{e.ultimo_error && <> · {e.ultimo_error}</>}</p>
              </div>
              <div className="flex items-center gap-2">
                <Insignia tono={tono(e.estado)}>{e.estado === 'atencion' ? 'requiere atención' : e.estado}</Insignia>
                {e.estado !== 'pendiente' && <Boton variante="secundario" onClick={() => void syncEngine.reintentar(e.id_cliente).then(cargar)}>Reintentar</Boton>}
              </div>
            </li>
          ))}
        </ul>
      </Tarjeta>
    </div>
  )
}
