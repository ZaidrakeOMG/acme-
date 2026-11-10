import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { PerfilConTema, Rol } from '../src/types/api'
import type { ConfiguracionMensajeria, Consumo, Envio, MiTelefono, Modos, Plantilla, VistaPrevia } from '../src/types/mensajeria'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const PLANTILLA = 'pl000000-0000-0000-0000-000000000001'

const sinTelefono: MiTelefono = {
  telefono_mascara: null, tiene_telefono: false, verificado: false, verificado_at: null,
  whatsapp: { consentimiento_at: null, baja_at: null, activo: false },
  sms: { consentimiento_at: null, baja_at: null, activo: false },
  aviso_privacidad: 'Tu número se usa solo para avisos operativos; escribe BAJA para darte de baja.',
}
const sinVerificar: MiTelefono = {
  ...sinTelefono, telefono_mascara: '+52 871 ••• ••67', tiene_telefono: true,
}
const verificado: MiTelefono = {
  ...sinVerificar, verificado: true, verificado_at: '2026-11-09T18:00:00Z',
}
const conWhatsapp: MiTelefono = {
  ...verificado, whatsapp: { consentimiento_at: '2026-11-09T18:01:00Z', baja_at: null, activo: true },
}

const configuracion: ConfiguracionMensajeria = {
  id: 'cfg1', prestador_id: 'p1', tenant_id: null, whatsapp_activo: true, sms_activo: false,
  eventos_whatsapp: [], eventos_sms: [],
  horario_silencio: { inicio: '22:00', fin: '07:00', zona: 'America/Mexico_City' },
  tope_mensual_mensajes: 1000, alerta_consumo_pct: 80, remitente_whatsapp: 'numero-demo',
  remitente_sms: '+520000000000', tarifa_whatsapp: '0.4000', tarifa_sms: '0.6000', moneda: 'MXN',
  ventana_respuesta_horas: 24,
}
const consumo: Consumo = {
  mes: '2026-11-01', mensajes: 850, tope: 1000, porcentaje: 85, costo_estimado: '340.0000', moneda: 'MXN',
  alerta_pct: 80, por_canal: { whatsapp: { mensajes: 800, costo: '320.0000' }, sms: { mensajes: 50, costo: '20.0000' } },
}
const modos: Modos = {
  whatsapp: { modo: 'stub', proveedor: 'stub', remitente: 'stub' },
  sms: { modo: 'stub', proveedor: 'stub', remitente: 'stub' },
  pendiente_para_produccion: ['Plantillas aprobadas por Meta (categoría utility).'],
  guia: 'docs/operacion/mensajeria.md',
}
const plantillas: Plantilla[] = [
  { id: PLANTILLA, clave: 'folio_asignado', nombre: 'Folio asignado a un técnico', evento: 'folio.estado',
    canal: 'whatsapp', idioma: 'es_MX', nombre_proveedor: 'acma_folio_asignado', categoria: 'utility',
    cuerpo: 'El folio {{1}} de {{2}} quedó asignado a {{3}}.', encabezado: '', pie: '',
    botones: [{ tipo: 'url', texto: 'Ver folio', ruta: '/folios/{folio_id}' }],
    variables: ['folio', 'sucursal', 'tecnico'], estado_aprobacion: 'aprobada', motivo_rechazo: '', version: 1,
    activa: true, prestador_id: null, es_global: true },
  { id: 'pl2', clave: 'aprobacion_pendiente', nombre: 'Folio pendiente de tu autorización',
    evento: 'aprobacion.pendiente', canal: 'whatsapp', idioma: 'es_MX', nombre_proveedor: 'acma_aprobacion',
    categoria: 'utility', cuerpo: 'Tienes el folio {{1}} esperando tu autorización.', encabezado: '', pie: '',
    botones: [], variables: ['folio'], estado_aprobacion: 'rechazada',
    motivo_rechazo: 'Meta rechazó la categoría: usa utility', version: 2, activa: true, prestador_id: 'p1',
    es_global: false },
]
const previa: VistaPrevia = {
  clave: 'folio_asignado', canal: 'whatsapp',
  cuerpo: 'El folio F-2026-000123 de Sucursal Centro quedó asignado a Tadeo Tecnico.',
  botones: [{ texto: 'Ver folio', tipo: 'url' }], segmentos: 0, codificacion: '', caracteres: 69,
  critica: false, aviso: '',
}
const envios: Envio[] = [
  { id: 'e1', canal: 'whatsapp', estado: 'leido', evento: 'folio.estado', plantilla: 'folio_asignado',
    proveedor: 'stub', telefono: '+52 871 ••• ••67', cuerpo: 'El folio F-1 quedó asignado a Tadeo.',
    costo_estimado: '0.4000', moneda: 'MXN', segmentos_sms: 0, intentos: 1, codigo_error: '', detalle_error: '',
    created_at: '2026-11-09T18:00:00Z', enviado_at: '2026-11-09T18:00:01Z', entregado_at: '2026-11-09T18:00:30Z',
    leido_at: '2026-11-09T18:02:00Z', abierto_at: '2026-11-09T18:03:00Z', usuario_id: 'u1', critico: false,
    enlace_destino: '/folios/f1', mensaje_id_proveedor: 'stub-abc' },
  { id: 'e2', canal: 'sms', estado: 'rechazado_por_proveedor', evento: 'folio.estado', plantilla: 'folio_cerrado',
    proveedor: 'twilio', telefono: '+52 871 ••• ••11', cuerpo: 'ACMA: folio F-2 cerrado.', costo_estimado: '0.0000',
    moneda: 'MXN', segmentos_sms: 1, intentos: 1, codigo_error: '21211',
    detalle_error: 'Numero invalido: el aviso salio por correo', created_at: '2026-11-09T17:00:00Z',
    enviado_at: null, entregado_at: null, leido_at: null, abierto_at: null, usuario_id: 'u2', critico: false,
    enlace_destino: '/folios/f2', mensaje_id_proveedor: null },
]

async function entrar(rol: Rol, ruta: string, rutas: Parameters<typeof simularApi>[0] = {},
                      extra: Partial<PerfilConTema> = {}) {
  localStorage.setItem('acma.sesion', '1')
  const llamadas = simularApi({
    'POST /api/auth/refresh': () => ({ json: TOKENS }),
    'GET /api/auth/yo': () => ({ json: perfil(rol, { prestador_id: 'p1', ...extra }) }),
    'GET /api/notificaciones/no-leidas': () => ({ json: { no_leidas: 0 } }),
    'GET /api/mensajeria/modos': () => ({ json: modos }),
    'GET /api/mensajeria/configuracion': () => ({ json: configuracion }),
    'GET /api/mensajeria/consumo': () => ({ json: consumo }),
    'GET /api/mensajeria/plantillas': () => ({ json: plantillas }),
    'GET /api/mensajeria/envios': () => ({ json: envios }),
    [`GET /api/mensajeria/plantillas/${PLANTILLA}/vista-previa`]: () => ({ json: previa }),
    'GET /api/notificaciones': () => ({ json: [] }),
    'GET /api/notificaciones/preferencias': () => ({ json: [] }),
    'GET /api/notificaciones/eventos': () => ({ json: {
      eventos: [{ clave: 'folio.estado', nombre: 'Cambio de estado del folio',
                  canales_default: ['app', 'push'], tiene_plantilla: true }],
      canales: [{ clave: 'app', nombre: 'Bandeja en la app', disponible: true },
                { clave: 'push', nombre: 'Push', disponible: true },
                { clave: 'email', nombre: 'Correo', disponible: true },
                { clave: 'whatsapp', nombre: 'WhatsApp', disponible: true, requiere_telefono: true, modo: 'stub' },
                { clave: 'sms', nombre: 'SMS', disponible: false, requiere_telefono: true, modo: 'stub' }] } }),
    'GET /api/usuarios/me/telefono': () => ({ json: sinTelefono }),
    ...rutas,
  })
  renderApp(ruta)
  return llamadas
}

describe('Mensajería por WhatsApp y SMS (F2-02)', () => {
  it('registra el celular, lo verifica con el código y guarda el consentimiento', async () => {
    let estado = sinTelefono
    const llamadas = await entrar('despachador', '/notificaciones', {
      'GET /api/usuarios/me/telefono': () => ({ json: estado }),
      'PUT /api/usuarios/me/telefono': () => { estado = sinVerificar; return { json: estado } },
      'POST /api/usuarios/me/telefono/codigo': () => ({ json: { enviado: true, canal: 'sms', minutos: 10, modo: 'stub' } }),
      'POST /api/usuarios/me/telefono/verificar': () => { estado = verificado; return { json: estado } },
      'PUT /api/usuarios/me/consentimiento': () => { estado = conWhatsapp; return { json: estado } },
    })
    const user = userEvent.setup()
    await screen.findByText('Mi celular para WhatsApp y SMS')

    await user.type(screen.getByLabelText('Celular (formato internacional)'), '+528711234567')
    await user.click(screen.getByRole('button', { name: 'Guardar' }))
    // Queda guardado pero sin verificar: así nadie activa un número que no es suyo.
    const tarjeta = await screen.findByTestId('mi-telefono')
    expect(within(tarjeta).getByText('+52 871 ••• ••67')).toBeInTheDocument()
    expect(within(tarjeta).getByText('Sin verificar')).toBeInTheDocument()
    expect(within(tarjeta).getByLabelText('Consentimiento para whatsapp')).toBeDisabled()

    await user.click(within(tarjeta).getByRole('button', { name: 'Enviarme el código' }))
    await screen.findByText(/modo simulado/)
    await user.type(within(tarjeta).getByLabelText('Código'), '482913')
    await user.click(within(tarjeta).getByRole('button', { name: 'Verificar' }))
    await screen.findByText('Verificado')

    await user.click(screen.getByLabelText('Consentimiento para whatsapp'))
    await screen.findByText('Activaste whatsapp')
    expect(llamadas.filter((l) => l.clave === 'PUT /api/usuarios/me/consentimiento')[0]?.cuerpo)
      .toEqual({ canal: 'whatsapp', acepta: true })
  })

  it('las preferencias por evento ya incluyen WhatsApp y SMS, sin leyendas de Fase 2', async () => {
    const llamadas = await entrar('despachador', '/notificaciones', {
      'GET /api/usuarios/me/telefono': () => ({ json: conWhatsapp }),
      'PUT /api/notificaciones/preferencias': (cuerpo) => ({ json: cuerpo }),
    })
    const preferencias = await screen.findByTestId('preferencias')
    expect(screen.queryByText(/Fase 2/)).not.toBeInTheDocument()
    const casilla = await screen.findByLabelText('Cambio de estado del folio por whatsapp')

    const user = userEvent.setup()
    await user.click(casilla)
    await waitFor(() => expect(llamadas.some((l) => l.clave === 'PUT /api/notificaciones/preferencias')).toBe(true))
    const enviado = llamadas.find((l) => l.clave === 'PUT /api/notificaciones/preferencias')!.cuerpo as
      { evento: string; canales: string[] }
    expect(enviado.canales).toEqual(['app', 'push', 'whatsapp'])
    // El canal que el prestador no tiene activo se muestra como inactivo, pero no se esconde.
    expect(within(preferencias).getByText('(inactivo)')).toBeInTheDocument()
  })

  it('muestra el consumo del mes con aviso cuando se acerca al tope', async () => {
    await entrar('admin_prestador', '/mensajeria')
    const panel = await screen.findByTestId('consumo-mensajeria')
    expect(within(panel).getByText('850 de 1000 mensajes')).toBeInTheDocument()
    expect(within(panel).getByText('340.00 MXN estimados')).toBeInTheDocument()  // en pesos, no en diezmilésimos
    expect(screen.getByText(/Llegaste al 85% del tope/)).toBeInTheDocument()
    expect(screen.getByText(/WhatsApp: modo stub/)).toBeInTheDocument()
  })

  it('la vista previa de la plantilla se ve como en WhatsApp y marca la rechazada', async () => {
    await entrar('admin_prestador', '/mensajeria?vista=plantillas')
    await screen.findByText('Folio asignado a un técnico')
    expect(screen.getByText('Aprobada')).toBeInTheDocument()
    expect(screen.getByText('Rechazada')).toBeInTheDocument()
    expect(screen.getByText('Meta rechazó la categoría: usa utility')).toBeInTheDocument()

    const user = userEvent.setup()
    await user.click(screen.getAllByRole('button', { name: 'Ver y editar' })[0]!)
    const previaVista = await screen.findByTestId('vista-previa')
    expect(within(previaVista).getByText(/El folio F-2026-000123 de Sucursal Centro/)).toBeInTheDocument()
    expect(within(previaVista).getByText('Ver folio')).toBeInTheDocument()
    expect(screen.getByLabelText('Cuerpo de la plantilla')).toHaveValue('El folio {{1}} de {{2}} quedó asignado a {{3}}.')
  })

  it('la bitácora de envíos dice el estado de entrega y el motivo del fallo', async () => {
    await entrar('admin_prestador', '/mensajeria?vista=envios')
    await screen.findByText('folio_asignado')
    // Dentro de la tabla: «Leído» también es una opción del filtro de estado.
    const tabla = within(screen.getByRole('table'))
    expect(tabla.getByText('Leído')).toBeInTheDocument()
    expect(tabla.getByText('Abrió el enlace')).toBeInTheDocument()
    expect(tabla.getByText('Rechazado por el proveedor')).toBeInTheDocument()
    expect(tabla.getByText('21211: Numero invalido: el aviso salio por correo')).toBeInTheDocument()
    expect(tabla.getByText('+52 871 ••• ••67')).toBeInTheDocument()
  })

  it('el enlace corto resuelve el destino y lleva a la pantalla', async () => {
    await entrar('despachador', '/l/abc12345', {
      'GET /api/mensajeria/enlaces/abc12345': () => ({ json: { destino: '/notificaciones', canal: 'whatsapp', evento: 'folio.estado' } }),
      'GET /api/usuarios/me/telefono': () => ({ json: conWhatsapp }),
    })
    // Se resuelve sin sesión y navega a la pantalla del aviso.
    await screen.findByText('Notificaciones')
  })

  it('un enlace corto que ya no sirve se explica', async () => {
    await entrar('despachador', '/l/caduco', {
      'GET /api/mensajeria/enlaces/caduco': () => ({ estado: 404, json: { codigo: 'NO_ENCONTRADO', mensaje: 'Enlace no encontrado', detalles: [] } }),
    })
    await screen.findByText(/Este enlace ya no sirve/)
  })
})
