import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { Aviso, Boton, Campo, Encabezado, Insignia, Modal, Selector, Tabla, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { mensajeDeError } from '../../services/api'
import {
  configuracionMensajeria, consumoMensajeria, editarPlantilla, exportarPlantilla, guardarConfiguracionMensajeria,
  listarEnvios, listarPlantillas, modosMensajeria, pruebaDeEnvio, simularWebhook, vistaPreviaPlantilla,
} from '../../services/mensajeria'
import { eventosNotificables } from '../../services/minutas'
import type { EventoNotificable } from '../../types/minutas'
import type {
  CanalMensajeria, ConfiguracionMensajeria, Consumo, Envio, Modos, Plantilla, VistaPrevia,
} from '../../types/mensajeria'
import { NOMBRE_APROBACION, NOMBRE_ESTADO_ENVIO } from '../../types/mensajeria'
import { fecha as fmtFecha } from '../folios/comunes'

type Vista = 'canales' | 'plantillas' | 'envios'

const TONO_ENVIO: Record<string, 'neutro' | 'ok' | 'alerta' | 'acento'> = {
  en_cola: 'neutro', enviado: 'acento', entregado: 'ok', leido: 'ok', fallido: 'alerta',
  rechazado_por_proveedor: 'alerta',
}
const TONO_APROBACION: Record<string, 'neutro' | 'ok' | 'alerta' | 'acento'> = {
  borrador: 'neutro', enviada: 'acento', aprobada: 'ok', rechazada: 'alerta', pausada: 'alerta',
}

/**
 * Mensajería por WhatsApp y SMS (§6.1, §7.5): canales activos y eventos por canal, horario de silencio, tope
 * mensual con su consumo, plantillas con su estado de aprobación y vista previa, y la bitácora de envíos con el
 * estado de entrega y el motivo cuando un aviso tuvo que cambiar de canal.
 */
export function Mensajeria() {
  const { usuario } = useAuth()
  const [params, setParams] = useSearchParams()
  const vista = (params.get('vista') as Vista) || 'canales'
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [modos, setModos] = useState<Modos | null>(null)

  useEffect(() => { void modosMensajeria().then(setModos).catch(() => setModos(null)) }, [])

  function ir(v: Vista) {
    const p = new URLSearchParams(params)
    p.set('vista', v)
    setParams(p)
  }

  if (!usuario) return null

  return (
    <div>
      <Encabezado titulo="Mensajería (WhatsApp y SMS)"
        descripcion="Avisos operativos por WhatsApp y SMS: el usuario los activa en su perfil con su teléfono verificado y su consentimiento; aquí se decide qué eventos salen por cada canal, en qué horario y con qué tope de gasto." />
      {modos && (
        <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
          <Insignia tono={modos.whatsapp.modo === 'real' ? 'ok' : 'neutro'}>
            WhatsApp: modo {modos.whatsapp.modo} ({modos.whatsapp.proveedor})
          </Insignia>
          <Insignia tono={modos.sms.modo === 'real' ? 'ok' : 'neutro'}>
            SMS: modo {modos.sms.modo} ({modos.sms.proveedor})
          </Insignia>
          {modos.whatsapp.modo === 'stub' && (
            <span className="text-xs text-slate-500">
              En modo simulado nada sale de la máquina: el mensaje se guarda como vista previa. La guía para usar las
              cuentas gratuitas está en {modos.guia}.
            </span>
          )}
        </div>
      )}
      <div className="mb-3 flex flex-wrap gap-1" role="tablist" aria-label="Vistas de mensajería">
        {([['canales', 'Canales y consumo'], ['plantillas', 'Plantillas'], ['envios', 'Bitácora de envíos']] as [Vista, string][]).map(([v, texto]) => (
          <button key={v} role="tab" aria-selected={vista === v}
            className={`rounded-lg px-3 py-1.5 text-sm ${vista === v ? 'bg-primario text-white' : 'border border-slate-300'}`}
            onClick={() => ir(v)}>{texto}</button>
        ))}
      </div>
      {error && <div className="mb-3"><Aviso>{error}</Aviso></div>}
      {aviso && <div className="mb-3"><Aviso tipo="exito">{aviso}</Aviso></div>}
      {vista === 'canales' && <Canales alAvisar={setAviso} alFallar={setError} modos={modos} />}
      {vista === 'plantillas' && <Plantillas alAvisar={setAviso} alFallar={setError} />}
      {vista === 'envios' && <Envios alFallar={setError} />}
    </div>
  )
}

/** El costo del mes se lee en pesos y centavos; la tarifa por mensaje sí lleva cuatro decimales. */
function pesos(valor: string): string {
  const n = Number(valor)
  return Number.isFinite(n) ? n.toFixed(2) : valor
}

interface Props {
  alAvisar?: (t: string | null) => void
  alFallar: (t: string | null) => void
}

// ------------------------------------------------------------------ canales y consumo
function Canales({ alAvisar, alFallar, modos }: Props & { modos: Modos | null }) {
  const [cfg, setCfg] = useState<ConfiguracionMensajeria | null>(null)
  const [consumo, setConsumo] = useState<Consumo | null>(null)
  const [eventos, setEventos] = useState<EventoNotificable[]>([])
  const [guardando, setGuardando] = useState(false)
  // Sin esto, un fallo al cargar se vería igual que «este prestador no tiene mensajería configurada», y el botón
  // de crearla sobreescribiría una configuración que sí existe (dejando los canales apagados).
  const [cargado, setCargado] = useState(false)

  const cargar = useCallback(async () => {
    try {
      const [c, u, ev] = await Promise.all([configuracionMensajeria(), consumoMensajeria(), eventosNotificables()])
      setCfg(c)
      setConsumo(u)
      setEventos(ev.eventos)
      setCargado(true)
    } catch (e) { alFallar(mensajeDeError(e)) }
  }, [alFallar])
  useEffect(() => { void cargar() }, [cargar])

  async function guardar(cambios: Partial<ConfiguracionMensajeria>) {
    setGuardando(true)
    alFallar(null)
    try {
      setCfg(await guardarConfiguracionMensajeria(cambios))
      setConsumo(await consumoMensajeria())
      alAvisar?.('Configuración guardada')
    } catch (e) { alFallar(mensajeDeError(e)) } finally { setGuardando(false) }
  }

  function alternarEvento(canal: CanalMensajeria, clave: string) {
    if (!cfg) return
    const campo = canal === 'whatsapp' ? 'eventos_whatsapp' : 'eventos_sms'
    const actuales = cfg[campo]
    const nuevos = actuales.includes(clave) ? actuales.filter((e) => e !== clave) : [...actuales, clave]
    void guardar({ [campo]: nuevos } as Partial<ConfiguracionMensajeria>)
  }

  if (!cargado) {
    return <div className="h-32 animate-pulse rounded-xl bg-slate-100" aria-label="Cargando la configuración" />
  }
  if (!cfg) {
    return (
      <Tarjeta titulo="Sin configurar">
        <p className="mb-3 text-sm text-slate-600">
          Este prestador todavía no tiene mensajería configurada: ningún aviso saldrá por WhatsApp ni por SMS.
        </p>
        <Boton disabled={guardando} onClick={() => void guardar({ whatsapp_activo: false, sms_activo: false })}>
          Crear la configuración
        </Boton>
      </Tarjeta>
    )
  }

  const pct = consumo?.porcentaje ?? 0
  const cerca = consumo != null && consumo.tope > 0 && pct >= consumo.alerta_pct

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Tarjeta titulo="Canales activos">
        <div className="space-y-3 text-sm">
          {(['whatsapp', 'sms'] as CanalMensajeria[]).map((canal) => (
            <label key={canal} className="flex items-center gap-2">
              <input type="checkbox" aria-label={`Canal ${canal}`}
                checked={canal === 'whatsapp' ? cfg.whatsapp_activo : cfg.sms_activo}
                onChange={(e) => void guardar(canal === 'whatsapp' ? { whatsapp_activo: e.target.checked } : { sms_activo: e.target.checked })} />
              <span className="font-medium">{canal === 'whatsapp' ? 'WhatsApp' : 'SMS'}</span>
              <span className="text-xs text-slate-500">
                {canal === 'whatsapp'
                  ? 'Plantillas aprobadas por Meta, con botón a la pantalla de ACMA.'
                  : 'Un segmento de 160 caracteres con enlace corto propio.'}
              </span>
            </label>
          ))}
          <p className="text-xs text-slate-500">
            Un aviso solo sale por estos canales si el usuario registró su teléfono, lo verificó y dio su
            consentimiento. Si no puede salir, cae al siguiente canal (push, correo o bandeja) y el motivo queda en
            la bitácora.
          </p>
        </div>
      </Tarjeta>

      <Tarjeta titulo="Consumo del mes">
        {consumo && (
          <div className="space-y-2 text-sm" data-testid="consumo-mensajeria">
            <div className="flex items-center justify-between">
              <span>{consumo.mensajes} de {consumo.tope || '∞'} mensajes</span>
              <span className="text-slate-500">{pesos(consumo.costo_estimado)} {consumo.moneda} estimados</span>
            </div>
            <div className="h-2 w-full rounded bg-slate-200">
              <div className={`h-2 rounded ${cerca ? 'bg-red-500' : 'bg-acento'}`}
                style={{ width: `${Math.min(100, pct)}%` }} />
            </div>
            {cerca && (
              <p className="text-xs text-red-700">
                Llegaste al {pct}% del tope: al alcanzarlo solo saldrán los avisos críticos.
              </p>
            )}
            <ul className="text-xs text-slate-600">
              {Object.entries(consumo.por_canal).map(([canal, v]) => (
                <li key={canal}>{canal}: {v.mensajes} mensaje(s) · {pesos(v.costo)} {consumo.moneda}</li>
              ))}
            </ul>
          </div>
        )}
        <div className="mt-3 grid grid-cols-2 gap-2">
          <Campo etiqueta="Tope mensual de mensajes" type="number" min={0} defaultValue={cfg.tope_mensual_mensajes}
            onBlur={(e) => void guardar({ tope_mensual_mensajes: Number(e.target.value) })} />
          <Campo etiqueta="Avisar al llegar al (%)" type="number" min={50} max={100} defaultValue={cfg.alerta_consumo_pct}
            onBlur={(e) => void guardar({ alerta_consumo_pct: Number(e.target.value) })} />
          <Campo etiqueta="Tarifa WhatsApp" type="number" step="0.0001" defaultValue={cfg.tarifa_whatsapp}
            onBlur={(e) => void guardar({ tarifa_whatsapp: e.target.value })} />
          <Campo etiqueta="Tarifa SMS" type="number" step="0.0001" defaultValue={cfg.tarifa_sms}
            onBlur={(e) => void guardar({ tarifa_sms: e.target.value })} />
        </div>
        <p className="mt-2 text-xs text-slate-500">
          Las tarifas son las que ACMA usa para estimar el gasto; no se consultan precios del proveedor.
        </p>
      </Tarjeta>

      <Tarjeta titulo="Horario de silencio">
        <p className="mb-2 text-xs text-slate-500">
          Fuera de este horario solo salen los avisos críticos: aprobaciones pendientes, SLA y severidad crítica.
        </p>
        <div className="grid grid-cols-2 gap-2">
          <Campo etiqueta="Desde" type="time" defaultValue={cfg.horario_silencio.inicio}
            onBlur={(e) => void guardar({ horario_silencio: { ...cfg.horario_silencio, inicio: e.target.value } })} />
          <Campo etiqueta="Hasta" type="time" defaultValue={cfg.horario_silencio.fin}
            onBlur={(e) => void guardar({ horario_silencio: { ...cfg.horario_silencio, fin: e.target.value } })} />
        </div>
        <Campo etiqueta="Zona horaria" defaultValue={cfg.horario_silencio.zona}
          onBlur={(e) => void guardar({ horario_silencio: { ...cfg.horario_silencio, zona: e.target.value } })} />
        <div className="mt-3 grid grid-cols-2 gap-2">
          <Campo etiqueta="Remitente de WhatsApp (id del número en Meta)" defaultValue={cfg.remitente_whatsapp}
            onBlur={(e) => void guardar({ remitente_whatsapp: e.target.value })} />
          <Campo etiqueta="Remitente de SMS" defaultValue={cfg.remitente_sms}
            onBlur={(e) => void guardar({ remitente_sms: e.target.value })} />
        </div>
      </Tarjeta>

      <Tarjeta titulo="Eventos por canal">
        <p className="mb-2 text-xs text-slate-500">
          Sin marcar nada, todos los eventos pueden salir por el canal. Si marcas alguno, solo saldrán esos.
        </p>
        <ul className="max-h-72 space-y-1 overflow-y-auto text-sm" data-testid="eventos-por-canal">
          {eventos.filter((e) => e.tiene_plantilla !== false).map((e) => (
            <li key={e.clave} className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-1">
              <span>{e.nombre}</span>
              <span className="flex gap-3">
                {(['whatsapp', 'sms'] as CanalMensajeria[]).map((canal) => (
                  <label key={canal} className="flex items-center gap-1 text-xs">
                    <input type="checkbox" aria-label={`${e.nombre} por ${canal}`}
                      checked={(canal === 'whatsapp' ? cfg.eventos_whatsapp : cfg.eventos_sms).includes(e.clave)}
                      onChange={() => alternarEvento(canal, e.clave)} />
                    {canal}
                  </label>
                ))}
              </span>
            </li>
          ))}
        </ul>
      </Tarjeta>

      {modos && (
        <Tarjeta titulo="Para usarlo de verdad">
          <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
            {modos.pendiente_para_produccion.map((p) => <li key={p}>{p}</li>)}
          </ul>
          <Prueba alAvisar={alAvisar} alFallar={alFallar} />
        </Tarjeta>
      )}
    </div>
  )
}

function Prueba({ alAvisar, alFallar }: Props) {
  const [canal, setCanal] = useState<CanalMensajeria>('whatsapp')
  const [telefono, setTelefono] = useState('')
  const [resultado, setResultado] = useState<string | null>(null)

  async function enviar() {
    alFallar(null)
    setResultado(null)
    try {
      const r = await pruebaDeEnvio(canal, telefono || undefined)
      setResultado(`${r.estado} (modo ${r.modo}, proveedor ${r.proveedor}): ${r.cuerpo}`)
      alAvisar?.('Mensaje de prueba enviado')
    } catch (e) { alFallar(mensajeDeError(e)) }
  }

  return (
    <div className="mt-3 border-t border-slate-100 pt-3">
      <p className="mb-2 text-xs text-slate-500">
        Prueba de envío. En modo simulado el mensaje solo se guarda; con una cuenta de prueba, el proveedor entrega
        únicamente a los números verificados en su panel.
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <Selector etiqueta="Canal" value={canal} onChange={(e) => setCanal(e.target.value as CanalMensajeria)}
          opciones={[{ valor: 'whatsapp', texto: 'WhatsApp' }, { valor: 'sms', texto: 'SMS' }]} />
        <Campo etiqueta="Número verificado (opcional)" value={telefono} placeholder="+52 871 123 4567"
          onChange={(e) => setTelefono(e.target.value)} />
        <Boton onClick={() => void enviar()}>Enviar prueba</Boton>
      </div>
      {resultado && <p className="mt-2 rounded bg-slate-50 p-2 text-xs text-slate-700">{resultado}</p>}
    </div>
  )
}

// ------------------------------------------------------------------ plantillas
function Plantillas({ alAvisar, alFallar }: Props) {
  const [canal, setCanal] = useState<CanalMensajeria>('whatsapp')
  const [lista, setLista] = useState<Plantilla[]>([])
  const [elegida, setElegida] = useState<Plantilla | null>(null)
  const [previa, setPrevia] = useState<VistaPrevia | null>(null)
  const [cuerpo, setCuerpo] = useState('')
  const [exportada, setExportada] = useState<string | null>(null)

  const cargar = useCallback(async () => {
    try { setLista(await listarPlantillas({ canal })) } catch (e) { alFallar(mensajeDeError(e)) }
  }, [canal, alFallar])
  useEffect(() => { void cargar() }, [cargar])

  async function abrir(p: Plantilla) {
    setElegida(p)
    setCuerpo(p.cuerpo)
    setExportada(null)
    setPrevia(null)
    try { setPrevia(await vistaPreviaPlantilla(p.id)) } catch (e) { alFallar(mensajeDeError(e)) }
  }

  async function guardar() {
    if (!elegida) return
    try {
      await editarPlantilla(elegida.id, { cuerpo })
      alAvisar?.('Plantilla guardada en borrador: sométela a Meta para poder usarla con una cuenta real')
      setElegida(null)
      await cargar()
    } catch (e) { alFallar(mensajeDeError(e)) }
  }

  return (
    <div>
      <div className="mb-3 flex items-end gap-2">
        <Selector etiqueta="Canal" value={canal} onChange={(e) => setCanal(e.target.value as CanalMensajeria)}
          opciones={[{ valor: 'whatsapp', texto: 'WhatsApp' }, { valor: 'sms', texto: 'SMS' }]} />
      </div>
      <Tabla<Plantilla> columnas={[
        { titulo: 'Plantilla', celda: (p) => (
          <div>
            <p className="font-medium text-slate-800">{p.nombre}</p>
            <p className="text-xs text-slate-500">{p.clave} · {p.evento} {p.es_global ? '· de la plataforma' : '· propia'}</p>
          </div>
        ) },
        { titulo: 'Aprobación', celda: (p) => (
          <span className="flex flex-col gap-1">
            <Insignia tono={TONO_APROBACION[p.estado_aprobacion]}>{NOMBRE_APROBACION[p.estado_aprobacion]}</Insignia>
            {p.motivo_rechazo && <span className="text-xs text-red-700">{p.motivo_rechazo}</span>}
          </span>
        ) },
        { titulo: 'Versión', celda: (p) => <span>v{p.version}</span> },
        { titulo: '', celda: (p) => (
          <Boton variante="secundario" onClick={() => void abrir(p)}>Ver y editar</Boton>
        ) },
      ]} filas={lista} vacio="Sin plantillas" />

      <Modal titulo={elegida ? `Plantilla · ${elegida.nombre}` : ''} abierto={elegida != null}
        alCerrar={() => setElegida(null)}>
        {elegida && (
          <div className="space-y-3">
            {previa && (
              <div className="rounded-xl bg-[#d9fdd3] p-3 text-sm text-slate-800 shadow-inner" data-testid="vista-previa">
                <p className="whitespace-pre-line">{previa.cuerpo}</p>
                {previa.botones.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-2 border-t border-emerald-200 pt-2">
                    {previa.botones.map((b) => (
                      <span key={b.texto} className="rounded bg-white px-2 py-1 text-xs text-primario">{b.texto}</span>
                    ))}
                  </div>
                )}
                <p className="mt-2 text-xs text-slate-600">
                  {previa.caracteres} caracteres
                  {previa.canal === 'sms' && ` · ${previa.segmentos} segmento(s) ${previa.codificacion}`}
                  {previa.critica && ' · evento crítico: ignora el horario de silencio'}
                </p>
                {previa.aviso && <p className="mt-1 text-xs text-amber-700">{previa.aviso}</p>}
              </div>
            )}
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-slate-700">Cuerpo (variables {'{{1}}'}, {'{{2}}'}…)</span>
              <textarea className="w-full rounded-lg border border-slate-300 p-2 text-sm" rows={4} value={cuerpo}
                onChange={(e) => setCuerpo(e.target.value)} aria-label="Cuerpo de la plantilla" />
            </label>
            <p className="text-xs text-slate-500">
              Variables en orden: {elegida.variables.join(', ') || 'ninguna'}. No escribas montos ni datos de
              terceros: el mensaje solo lleva folio, sucursal, estado y enlace.
            </p>
            <div className="flex flex-wrap gap-2">
              <Boton onClick={() => void guardar()}>Guardar</Boton>
              {elegida.canal === 'whatsapp' && (
                <Boton variante="secundario"
                  onClick={() => void exportarPlantilla(elegida.id).then((d) => setExportada(JSON.stringify(d, null, 2)))}>
                  Exportar para Meta
                </Boton>
              )}
              <Boton variante="fantasma" onClick={() => setElegida(null)}>Cerrar</Boton>
            </div>
            {exportada && (
              <pre className="max-h-48 overflow-auto rounded bg-slate-900 p-3 text-xs text-slate-100">{exportada}</pre>
            )}
          </div>
        )}
      </Modal>
    </div>
  )
}

// ------------------------------------------------------------------ bitácora
function Envios({ alFallar }: Props) {
  const [lista, setLista] = useState<Envio[]>([])
  const [canal, setCanal] = useState('')
  const [estado, setEstado] = useState('')
  const [elegido, setElegido] = useState<Envio | null>(null)

  const cargar = useCallback(async () => {
    try { setLista(await listarEnvios({ canal: canal || undefined, estado: estado || undefined, limite: 200 })) }
    catch (e) { alFallar(mensajeDeError(e)) }
  }, [canal, estado, alFallar])
  useEffect(() => { void cargar() }, [cargar])

  async function simularEntrega(e: Envio, nuevo: string) {
    try {
      await simularWebhook({ mensaje_id: e.mensaje_id_proveedor, estado: nuevo })
      await cargar()
      setElegido(null)
    } catch (err) { alFallar(mensajeDeError(err)) }
  }

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <Selector etiqueta="Canal" value={canal} onChange={(ev) => setCanal(ev.target.value)}
          opciones={[{ valor: '', texto: 'Todos' }, { valor: 'whatsapp', texto: 'WhatsApp' },
            { valor: 'sms', texto: 'SMS' }]} />
        <Selector etiqueta="Estado" value={estado} onChange={(ev) => setEstado(ev.target.value)}
          opciones={[{ valor: '', texto: 'Todos' },
            ...Object.entries(NOMBRE_ESTADO_ENVIO).map(([valor, texto]) => ({ valor, texto }))]} />
        <Boton variante="secundario" onClick={() => void cargar()}>Actualizar</Boton>
      </div>
      <Tabla<Envio> columnas={[
        { titulo: 'Cuándo', celda: (e) => <span className="text-xs">{fmtFecha(e.created_at)}</span> },
        { titulo: 'Canal', celda: (e) => <span>{e.canal}</span> },
        { titulo: 'Evento', celda: (e) => (
          <div>
            <p>{e.evento}</p>
            <p className="text-xs text-slate-500">{e.plantilla}{e.critico ? ' · crítico' : ''}</p>
          </div>
        ) },
        { titulo: 'Destino', celda: (e) => <span>{e.telefono}</span> },
        { titulo: 'Entrega', celda: (e) => (
          <span className="flex flex-col gap-1">
            <Insignia tono={TONO_ENVIO[e.estado]}>{NOMBRE_ESTADO_ENVIO[e.estado]}</Insignia>
            {e.detalle_error && <span className="text-xs text-red-700">{e.codigo_error}: {e.detalle_error}</span>}
            {e.abierto_at && <span className="text-xs text-emerald-700">Abrió el enlace</span>}
          </span>
        ) },
        { titulo: 'Costo', celda: (e) => (
          <span className="text-xs">{e.costo_estimado} {e.moneda}{e.segmentos_sms ? ` · ${e.segmentos_sms} seg.` : ''}</span>
        ) },
        { titulo: '', celda: (e) => (
          <Boton variante="fantasma" onClick={() => setElegido(e)}>Ver</Boton>
        ) },
      ]} filas={lista} vacio="Todavía no se ha enviado ningún mensaje" />

      <Modal titulo="Mensaje enviado" abierto={elegido != null} alCerrar={() => setElegido(null)}>
        {elegido && (
          <div className="space-y-2 text-sm">
            <div className="rounded-xl bg-[#d9fdd3] p-3 shadow-inner">
              <p className="whitespace-pre-line">{elegido.cuerpo}</p>
            </div>
            <p className="text-xs text-slate-600">
              {elegido.canal} · {elegido.proveedor} · {elegido.telefono} · {elegido.intentos} intento(s)
            </p>
            <ul className="text-xs text-slate-600">
              <li>Enviado: {elegido.enviado_at ? fmtFecha(elegido.enviado_at) : '—'}</li>
              <li>Entregado: {elegido.entregado_at ? fmtFecha(elegido.entregado_at) : '—'}</li>
              <li>Leído: {elegido.leido_at ? fmtFecha(elegido.leido_at) : '—'}</li>
              <li>Abrió el enlace: {elegido.abierto_at ? fmtFecha(elegido.abierto_at) : '—'}</li>
              <li>Lleva a: {elegido.enlace_destino || '—'}</li>
            </ul>
            <div className="flex flex-wrap gap-2">
              {elegido.mensaje_id_proveedor && (
                <Boton variante="secundario" onClick={() => void simularEntrega(elegido, 'entregado')}>
                  Simular entrega
                </Boton>
              )}
              <Boton variante="fantasma" onClick={() => setElegido(null)}>Cerrar</Boton>
            </div>
            <p className="text-xs text-slate-500">
              La simulación existe porque en una máquina local el proveedor no puede llamar al webhook de ACMA.
            </p>
          </div>
        )}
      </Modal>
    </div>
  )
}
