import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { aplicarEvento } from '../src/pages/operaciones/Operaciones'
import { intervaloMs } from '../src/services/posiciones'
import type { PerfilConTema, Rol } from '../src/types/api'
import type {
  AlertaDelTecnico, MiJornada, Parametros, Recorrido, Tablero, TecnicoEnTablero,
} from '../src/types/operaciones'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const TEC = 't0000000-0000-0000-0000-000000000001'
const TEC2 = 't0000000-0000-0000-0000-000000000002'
const JORNADA = 'j0000000-0000-0000-0000-000000000001'

const parametros: Parametros = {
  frecuencias: { jornada_activa_s: 30, pausa_s: 300, bateria_baja_s: 120, bateria_baja_pct: 20 },
  geocerca_radio_m: 150, jornada_cierre_horas: 2, sin_senal_min: 15, tiempo_muerto_min: 20,
  aviso_geolocalizacion: 'Mientras tu jornada esté iniciada, ACMA registra la ubicación de tu teléfono cada 30 segundos.',
  max_lote: 60, precision_maxima_m: 500, horas_recorrido: 2,
  desvio_ruta: 'El desvío se marca cuando el técnico se sale del corredor de su ruta',
}

const tecnicos: TecnicoEnTablero[] = [
  { tecnico_id: TEC, usuario_id: 'u1', nombre: 'Tomás Técnico', numero_empleado: 'EMP-001',
    estatus: 'en_servicio', estatus_texto: 'En servicio', en_jornada: true,
    jornada_desde: '2026-11-10T14:00:00Z', minutos_en_estatus: 35, folios_pendientes: 2,
    lat: 19.4326, lng: -99.1332, ultima_posicion_at: '2026-11-10T15:30:00Z', precision_m: '12.0',
    bateria_pct: 80, vehiculo_placas: 'ACM-001', telefono: '+528711234567', alerta: null,
    respuesta_tecnico: null },
  { tecnico_id: TEC2, usuario_id: 'u2', nombre: 'Tadeo Técnico', numero_empleado: 'EMP-003',
    estatus: 'en_ruta', estatus_texto: 'En ruta', en_jornada: true, jornada_desde: '2026-11-10T13:30:00Z',
    minutos_en_estatus: 26, folios_pendientes: 1, lat: 19.4005, lng: -99.17,
    ultima_posicion_at: '2026-11-10T15:29:00Z', precision_m: '18.0', bateria_pct: 45, vehiculo_placas: null,
    telefono: null, alerta: { tipo: 'TECNICO_TIEMPO_MUERTO', desde: '2026-11-10T15:10:00Z', escalada: false },
    respuesta_tecnico: null },
  { tecnico_id: 't3', usuario_id: 'u3', nombre: 'Tania Técnica', numero_empleado: 'EMP-004',
    estatus: 'sin_senal', estatus_texto: 'Sin señal', en_jornada: true, jornada_desde: '2026-11-10T13:00:00Z',
    minutos_en_estatus: 20, folios_pendientes: 0, lat: 19.38, lng: -99.16,
    ultima_posicion_at: '2026-11-10T15:10:00Z', precision_m: null, bateria_pct: null, vehiculo_placas: null,
    telefono: null, alerta: null, respuesta_tecnico: null },
]

const tableroDemo: Tablero = {
  generado_at: '2026-11-10T15:30:00Z',
  tecnicos,
  folios: [
    { folio_id: 'f1', numero_folio: 'CD-000120', estado: 'en_ejecucion', tecnico_id: 'u1',
      tecnico: 'Tomás Técnico', un_id: 'un1', sucursal: 'SUC-001 Sucursal Centro',
      capturado_at: '2026-11-10T14:05:00Z', sla_disponible: true, minutos_restantes: 18, limite_sla_min: 240,
      minutos_transcurridos: 222, umbral_riesgo_pct: 80, en_riesgo: true, incumplido: false, cumplimiento: null },
    { folio_id: 'f2', numero_folio: 'CD-000121', estado: 'asignado', tecnico_id: 'u2', tecnico: 'Tadeo Técnico',
      un_id: 'un2', sucursal: 'SUC-002 Sucursal Polanco', capturado_at: '2026-11-10T10:00:00Z',
      sla_disponible: true, minutos_restantes: -30, limite_sla_min: 240, minutos_transcurridos: 270,
      umbral_riesgo_pct: 80, en_riesgo: false, incumplido: true, cumplimiento: false },
    { folio_id: 'f3', numero_folio: 'CD-000122', estado: 'autorizado', tecnico_id: null, tecnico: null,
      un_id: 'un3', sucursal: 'SUC-003 Sucursal Coyoacán', capturado_at: '2026-11-10T15:00:00Z',
      sla_disponible: false, minutos_restantes: null, limite_sla_min: null, en_riesgo: false,
      incumplido: false, cumplimiento: null },
  ],
  unidades: [{ un_id: 'un1', codigo: 'SUC-001', nombre: 'Sucursal Centro', lat: 19.4326, lng: -99.1332,
               folios_activos: 1 }],
  alertas: [
    { id: 'a1', clave: 'TECNICO_TIEMPO_MUERTO', nombre: 'Técnico sin movimiento GPS', entidad_tipo: 'tecnico',
      entidad_id: TEC2,
      timestamp: '2026-11-10T15:10:00Z', estado: 'disparada', escalada: false, vista: false,
      datos: { minutos: 20, radio_m: 50 } },
    { id: null, clave: 'FOLIO_AUTORIZADO_SIN_TECNICO', nombre: 'Folio autorizado sin técnico asignado',
      entidad_tipo: 'folio', entidad_id: 'f3',
      timestamp: '2026-11-10T15:00:00Z', estado: 'disparada', escalada: false, vista: false,
      datos: { numero_folio: 'CD-000122', sucursal: 'SUC-003 Sucursal Coyoacán' } },
  ],
  indicadores: { completados: 4, total_dia: 9, tecnicos_activos: 3, alertas_abiertas: 2,
                 tiempo_promedio_atencion_horas: '2.40',
                 aviso_fase_2: 'El desvío de ruta y el ETA ya operan con distancias estimadas' },
  parametros,
  solo_lectura: false,
}

const recorrido: Recorrido = {
  tecnico_id: TEC, nombre: 'Tomás Técnico', desde: '2026-11-10T13:30:00Z', estatus: 'en_servicio',
  puntos: [
    { lat: 19.43, lng: -99.14, capturada_at: '2026-11-10T14:00:00Z', precision_m: '10.0',
      velocidad_mps: '5.00', bateria_pct: 90, tardia: false },
    { lat: 19.4326, lng: -99.1332, capturada_at: '2026-11-10T15:30:00Z', precision_m: '12.0',
      velocidad_mps: '0.00', bateria_pct: 80, tardia: false },
  ],
}

const sinJornada: MiJornada = { ...parametros, tecnico_id: TEC, estatus: 'fuera_de_jornada', jornada: null,
                                aviso_aceptado: false }
const conJornada: MiJornada = {
  ...parametros, tecnico_id: TEC, estatus: 'en_ruta', aviso_aceptado: true,
  jornada: { id: JORNADA, inicio: '2026-11-10T14:00:00Z', estado: 'activa', dispositivo_id: 'demo',
             posiciones: 12, pausa_desde: null, pausa_motivo: null },
}
const alertasDelTecnico: AlertaDelTecnico[] = [
  { id: 'seg1', tipo: 'TECNICO_TIEMPO_MUERTO', desde: '2026-11-10T15:10:00Z', folio_id: 'f2',
    pregunta: '¿Todo bien? Si necesitas apoyo, dinos y avisamos al despachador.', datos: { minutos: 20 } },
]

async function entrar(rol: Rol, ruta: string, rutas: Parameters<typeof simularApi>[0] = {},
                      extra: Partial<PerfilConTema> = {}) {
  localStorage.setItem('acma.sesion', '1')
  const llamadas = simularApi({
    'POST /api/auth/refresh': () => ({ json: TOKENS }),
    'GET /api/auth/yo': () => ({ json: perfil(rol, { prestador_id: 'p1', ...extra }) }),
    'GET /api/notificaciones/no-leidas': () => ({ json: { no_leidas: 0 } }),
    'GET /api/operacion/tablero': () => ({ json: tableroDemo }),
    'GET /api/operacion/usuarios-compartiendo': () => ({ json: [] }),
    [`GET /api/operacion/tecnicos/${TEC}/recorrido`]: () => ({ json: recorrido }),
    [`GET /api/operacion/tecnicos/${TEC2}/recorrido`]: () => ({ json: { ...recorrido, tecnico_id: TEC2 } }),
    'GET /api/operacion/mi-jornada': () => ({ json: sinJornada }),
    'GET /api/operacion/mis-alertas': () => ({ json: [] }),
    ...rutas,
  })
  renderApp(ruta)
  return llamadas
}

beforeEach(() => {
  // El tablero abre un WebSocket y, si falla, un EventSource: en jsdom no existen.
  vi.stubGlobal('WebSocket', class {
    static OPEN = 1
    readyState = 0
    onopen: (() => void) | null = null
    onmessage: ((m: { data: string }) => void) | null = null
    onerror: (() => void) | null = null
    onclose: (() => void) | null = null
    send() { /* latidos */ }
    close() { /* nada */ }
  })
  vi.stubGlobal('EventSource', class {
    onopen: (() => void) | null = null
    onmessage: ((m: { data: string }) => void) | null = null
    onerror: (() => void) | null = null
    close() { /* nada */ }
  })
})

describe('Operaciones en tiempo real (F2-03)', () => {
  it('el tablero muestra técnicos con su estatus en texto, folios con SLA y el feed de alertas', async () => {
    await entrar('despachador', '/operaciones')
    await screen.findAllByText('Tomás Técnico')  // el tablero ya respondió (el nombre sale también en «Centrar»)
    const panel = screen.getByTestId('panel-tecnicos')
    expect(within(panel).getByText('Tomás Técnico')).toBeInTheDocument()
    // El estatus va en texto, no solo en color (§6.8.4, accesibilidad).
    expect(within(panel).getByText('En servicio')).toBeInTheDocument()
    expect(within(panel).getByText('Sin señal')).toBeInTheDocument()
    expect(within(panel).getByText(/Técnico detenido/)).toBeInTheDocument()
    // El tiempo en el estatus se lee en horas y minutos, no en «219 min».
    expect(within(panel).getByText(/35 min en este estatus/)).toBeInTheDocument()

    const folios = screen.getByTestId('panel-folios')
    expect(within(folios).getByText('CD-000120')).toBeInTheDocument()
    expect(within(folios).getByText(/18 min/)).toBeInTheDocument()
    expect(within(folios).getByText('incumplido')).toBeInTheDocument()

    const alertas = screen.getByTestId('panel-alertas')
    expect(within(alertas).getByText('Folio autorizado sin técnico')).toBeInTheDocument()
    expect(within(alertas).getAllByText('Abrir el folio').length).toBeGreaterThan(0)

    const indicadores = screen.getByTestId('indicadores-jornada')
    expect(within(indicadores).getByText('Técnicos en jornada')).toBeInTheDocument()
    // Tres técnicos en jornada y tres con folio activo: el valor sale dos veces, una por celda.
    expect(within(indicadores).getAllByText('3')).toHaveLength(2)
    expect(within(indicadores).getByText('Folios del día')).toBeInTheDocument()
    expect(within(indicadores).getByText('9')).toBeInTheDocument()
  })

  it('al seleccionar folio rastrea al usuario que comparte GPS y no confunde su ubicación con la sucursal', async () => {
    await entrar('despachador', '/operaciones', {
      'GET /api/operacion/usuarios-compartiendo': () => ({
        json: [{
          folio_id: 'f3', usuario_id: 'u-operador', usuario_nombre: 'Usuario de Android',
          lat: 25.54, lng: -103.42, precision_m: 14,
          ultima_at: '2026-11-23T17:00:00Z',
        }],
      }),
    })
    const fila = (await screen.findByText('CD-000122')).closest('tr')
    expect(fila).not.toBeNull()
    const user = userEvent.setup()
    await user.click(within(fila!).getByRole('button', { name: 'Rastrear' }))
    const panel = await screen.findByTestId('operaciones-folio-rastreado')
    expect(await within(panel).findByText(/Marcador verde: ubicación compartida voluntariamente/)).toBeInTheDocument()
    expect(within(panel).getByRole('button', { name: 'Centrar en el usuario' })).toBeInTheDocument()
  })

  it('al rastrear un folio sin técnico muestra la sucursal como referencia y no inventa GPS', async () => {
    const unidades = [...tableroDemo.unidades, {
      un_id: 'un3', codigo: 'SUC-003', nombre: 'Sucursal Coyoacán',
      lat: 19.346, lng: -99.16, folios_activos: 0,
    }]
    await entrar('despachador', '/operaciones', {
      'GET /api/operacion/tablero': () => ({ json: { ...tableroDemo, unidades } }),
    })
    const fila = (await screen.findByText('CD-000122')).closest('tr')
    expect(fila).not.toBeNull()
    const user = userEvent.setup()
    await user.click(within(fila!).getByRole('button', { name: 'Rastrear' }))
    const panel = await screen.findByTestId('operaciones-folio-rastreado')
    expect(within(panel).getByText(/Marcador ámbar: ubicación registrada de la sucursal/)).toBeInTheDocument()
    expect(within(panel).getByRole('button', { name: 'Ver sucursal en el mapa' })).toBeInTheDocument()
    expect(screen.getByText(/NO un GPS en tiempo real/)).toBeInTheDocument()
  })

  it('al elegir un técnico pide su recorrido y lo muestra en su detalle', async () => {
    const llamadas = await entrar('despachador', '/operaciones')
    await screen.findAllByText('Tomás Técnico')
    const panel = screen.getByTestId('panel-tecnicos')
    const user = userEvent.setup()
    await user.click(within(panel).getByText('Tomás Técnico'))
    const detalle = await screen.findByTestId('detalle-tecnico')
    expect(within(detalle).getByText(/2 punto\(s\) en las últimas horas/)).toBeInTheDocument()
    expect(within(detalle).getByText('CD-000120')).toBeInTheDocument()
    expect(within(detalle).getByRole('link', { name: 'Llamar' })).toHaveAttribute('href', 'tel:+528711234567')
    await waitFor(() => expect(llamadas.some((l) =>
      l.clave === `GET /api/operacion/tecnicos/${TEC}/recorrido`)).toBe(true))
  })

  it('un evento de posición mueve solo al técnico que cambió', () => {
    const despues = aplicarEvento(tableroDemo, {
      evento: 'posicion', tecnico_id: TEC, lat: 19.5, lng: -99.2, estatus: 'en_ruta',
      capturada_at: '2026-11-10T15:31:00Z', bateria_pct: 75,
    })
    const movido = despues!.tecnicos.find((t) => t.tecnico_id === TEC)!
    const otro = despues!.tecnicos.find((t) => t.tecnico_id === TEC2)!
    expect([movido.lat, movido.lng]).toEqual([19.5, -99.2])
    expect(movido.estatus_texto).toBe('En ruta')
    expect(otro).toEqual(tableroDemo.tecnicos[1])  // el resto del tablero queda intacto
    // La escalación marca la alerta del técnico, sin pedir el tablero completo.
    const escalado = aplicarEvento(despues, { evento: 'escalacion', tecnico_id: TEC2 })
    expect(escalado!.tecnicos.find((t) => t.tecnico_id === TEC2)!.alerta!.escalada).toBe(true)
    // Cerrar la jornada lo saca del mapa.
    const cerrado = aplicarEvento(despues, { evento: 'jornada', tecnico_id: TEC, estado: 'cerrada' })
    expect(cerrado!.tecnicos.find((t) => t.tecnico_id === TEC)!.en_jornada).toBe(false)
  })

  it('el técnico inicia su jornada aceptando el aviso y luego la pausa', async () => {
    let estado = sinJornada
    const llamadas = await entrar('tecnico', '/campo', {
      'GET /api/folios': () => ({ json: [] }),
      'GET /api/configuracion/mis-permisos': () => ({ json: [] }),
      'GET /api/operacion/mi-jornada': () => ({ json: estado }),
      'POST /api/operacion/jornada/iniciar': () => { estado = conJornada; return { estado: 201, json: estado } },
      'POST /api/operacion/jornada/pausar': () => {
        estado = { ...conJornada, estatus: 'pausa',
                   jornada: { ...conJornada.jornada!, estado: 'pausa', pausa_desde: '2026-11-10T15:00:00Z',
                              pausa_motivo: 'comida' } }
        return { json: estado }
      },
      'GET /api/operacion/mis-alertas': () => ({ json: [] }),
    })
    const tarjeta = await screen.findByTestId('mi-jornada')
    expect(within(tarjeta).getByText('Sin iniciar')).toBeInTheDocument()
    // La primera vez el aviso de qué se registra está a la vista y el botón lo dice.
    expect(within(tarjeta).getByText(/registra la ubicación de tu teléfono/)).toBeInTheDocument()

    const user = userEvent.setup()
    await user.click(within(tarjeta).getByRole('button', { name: 'Acepto y inicio mi jornada' }))
    await screen.findByText('Jornada iniciada')
    expect(llamadas.find((l) => l.clave === 'POST /api/operacion/jornada/iniciar')?.cuerpo)
      .toMatchObject({ acepta_aviso: true })
    expect(within(screen.getByTestId('mi-jornada')).getByText(/cada 30 s/)).toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('Motivo de la pausa'), 'comida')
    await user.click(screen.getByRole('button', { name: 'Pausar' }))
    await screen.findByText('Jornada en pausa')
    expect(within(screen.getByTestId('mi-jornada')).getByText(/5 min \(en pausa\)/)).toBeInTheDocument()
  })

  it('el técnico contesta el aviso de tiempo muerto con «Necesito apoyo»', async () => {
    const llamadas = await entrar('tecnico', '/campo', {
      'GET /api/folios': () => ({ json: [] }),
      'GET /api/configuracion/mis-permisos': () => ({ json: [] }),
      'GET /api/operacion/mi-jornada': () => ({ json: conJornada }),
      'GET /api/operacion/mis-alertas': () => ({ json: alertasDelTecnico }),
      'POST /api/operacion/alertas/seg1/responder': () => ({
        json: { id: 'seg1', respuesta: 'necesito_apoyo', respondida_at: '2026-11-10T15:12:00Z' } }),
    })
    const alerta = await screen.findByTestId('alerta-tecnico')
    expect(within(alerta).getByText(/¿Todo bien\?/)).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(within(alerta).getByRole('button', { name: 'Necesito apoyo' }))
    await screen.findByText('Avisamos al despachador que necesitas apoyo')
    expect(llamadas.find((l) => l.clave === 'POST /api/operacion/alertas/seg1/responder')?.cuerpo)
      .toEqual({ respuesta: 'necesito_apoyo' })
  })

  it('las posiciones que no se pudieron enviar quedan en la cola y salen marcadas como tardías', async () => {
    const { baseLocal } = await import('../src/services/db')
    const { enviarPendientes, pendientes } = await import('../src/services/posiciones')
    await baseLocal.posiciones_pendientes.clear()
    await baseLocal.posiciones_pendientes.bulkPut([
      { id_cliente: 'p1', jornada_id: JORNADA, lat: 19.43, lng: -99.13, capturada_at: '2026-11-10T15:00:00Z',
        precision_m: 10, velocidad_mps: 0, rumbo: null, bateria_pct: 80, intentos: 0, enviado: 0 },
      { id_cliente: 'p2', jornada_id: JORNADA, lat: 19.431, lng: -99.131, capturada_at: '2026-11-10T15:00:30Z',
        precision_m: 12, velocidad_mps: 2, rumbo: 90, bateria_pct: 79, intentos: 0, enviado: 0 },
    ])
    expect((await pendientes()).length).toBe(2)

    let enviado: unknown = null
    simularApi({
      'POST /api/auth/refresh': () => ({ json: TOKENS }),
      'POST /api/operacion/posiciones': (cuerpo) => {
        enviado = cuerpo
        return { json: { aceptadas: 2, descartadas: [], jornada_id: JORNADA, estatus: 'en_ruta',
                         sugerencia_llegada: null } }
      },
    })
    const aceptadas = await enviarPendientes()
    expect(aceptadas).toBe(2)
    expect((enviado as { posiciones: { tardia: boolean }[] }).posiciones.every((p) => p.tardia)).toBe(true)
    expect((await pendientes()).length).toBe(0)
  })

  it('la frecuencia de envío sigue las tres del diseño', () => {
    expect(intervaloMs(parametros, false, 90)).toBe(30000)
    expect(intervaloMs(parametros, true, 90)).toBe(300000)
    expect(intervaloMs(parametros, false, 15)).toBe(120000)
    // Sin Battery Status API se usa el intervalo normal.
    expect(intervaloMs(parametros, false, null)).toBe(30000)
  })

  it('el cliente no entra a la pantalla de operaciones', async () => {
    await entrar('admin_un', '/operaciones')
    expect(await screen.findByText('Sin acceso')).toBeInTheDocument()
  })
})
