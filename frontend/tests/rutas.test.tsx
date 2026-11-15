/** Rutas, reasignación automática, ETA y desvío (§6.8.2, §6.8.4). F2-06. */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { PerfilConTema, Rol } from '../src/types/api'
import type { FolioDetalle, FolioResumen } from '../src/types/folios'
import type { Parametros, Tablero, TecnicoEnTablero } from '../src/types/operaciones'
import type {
  ConfiguracionRutas, Eta, Mercado, MiRuta, PlanDetalle, Propuesta, Simulacion, TiempoServicio, TrazoRuta,
} from '../src/types/rutas'
import { enlaceGoogleMaps, enlaceWaze, hora, sumaPesosRutas, textoHolgura } from '../src/types/rutas'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const T = '11111111-1111-1111-1111-111111111111'
const MERCADO = 'm0000000-0000-0000-0000-000000000001'
const PLAN = 'p0000000-0000-0000-0000-000000000001'
const TEC1 = 't0000000-0000-0000-0000-000000000001'
const TEC2 = 't0000000-0000-0000-0000-000000000002'
const PAR1 = 'a0000000-0000-0000-0000-000000000001'
const PAR2 = 'a0000000-0000-0000-0000-000000000002'
const FOLIO = 'f0000000-0000-0000-0000-000000000001'
const UN1 = 'u0000000-0000-0000-0000-000000000001'
const EQ1 = 'e0000000-0000-0000-0000-000000000001'
const PROP = 'r0000000-0000-0000-0000-000000000001'

const mercados: Mercado[] = [
  { id: MERCADO, prestador_id: 'p1', codigo: 'CDMX-CENTRO', nombre: 'Ciudad de México · Centro',
    zona_horaria: 'America/Mexico_City', activo: true, unidades: 6 },
]

const configuracion: ConfiguracionRutas = {
  id: 'cfg1', prestador_id: 'p1', mercado_id: null,
  pesos_json: { distancia: 1, sla: 600, criticidad: 300, folio_sin_asignar: 5000, horas_extra: 240, sin_refaccion: 400 },
  hora_inicio_jornada: '08:00', duracion_jornada_min: 480, tiempo_servicio_default_min: 60,
  factor_sinuosidad: '1.35', velocidades_json: { pico_am: 18, normal: 28, pico_pm: 16, noche: 35 },
  modo_reasignacion_automatica: 'solo_sugerir', minutos_vigencia_propuesta: 20,
  umbral_desvio_m: 500, umbral_desvio_min: 10, corredor_desvio_m: 300,
  proveedor_distancias: 'estimado', segundos_limite_calculo: 15, hora_calculo_automatico: '06:00',
  configurado_por: null, version_hash: 'x',
}

const tiempos: TiempoServicio[] = [
  { id: 'ts1', prestador_id: 'p1', tipo_folio: 'correctivo', tipo_equipo_id: 'te1',
    tipo_equipo: 'Refrigerador vertical', minutos_estimados: 75, origen: 'historial', muestras: 24 },
]

function detallePlan(estado: PlanDetalle['plan']['estado'] = 'borrador'): PlanDetalle {
  return {
    plan: {
      id: PLAN, mercado_id: MERCADO, fecha: new Date().toISOString().slice(0, 10), estado, version: 1,
      distancia_total_km: 44.2, folios_asignados: 3, folios_sin_asignar: 1,
      sin_asignar: [{ folio_id: 'f9', numero_folio: 'RT-000099',
                      motivo: 'Ningún técnico con la habilidad certificada tiene jornada abierta' }],
      tiempo_calculo_ms: 3600, motor: 'ortools', costo_objetivo: 18420,
      publicado_at: estado === 'borrador' ? null : '2026-11-13T13:00:00Z',
    },
    rutas: [
      { tecnico_id: TEC1, tecnico: 'Tomás Técnico', km: 26.4, minutos: 320,
        paradas: [
          { parada_id: PAR1, folio_id: FOLIO, numero_folio: 'RT-000001', orden: 0, un_codigo: 'SUC-001',
            un_nombre: 'Sucursal Centro', tipo_folio: 'correctivo', estado_folio: 'asignado', criticidad: 'A',
            llegada_estimada: '2026-11-13T14:30:00Z', fin_estimado: '2026-11-13T15:45:00Z',
            minutos_desde_anterior: 18, km_desde_anterior: 6.2, minutos_servicio: 75,
            ventana_ok: true, sla_ok: true, holgura_sla_min: 95, fijo: false },
          { parada_id: PAR2, folio_id: 'f2', numero_folio: 'RT-000002', orden: 1, un_codigo: 'SUC-002',
            un_nombre: 'Sucursal Polanco', tipo_folio: 'correctivo', estado_folio: 'en_ejecucion',
            criticidad: 'C', llegada_estimada: '2026-11-13T16:10:00Z', fin_estimado: '2026-11-13T17:10:00Z',
            minutos_desde_anterior: 25, km_desde_anterior: 9.8, minutos_servicio: 60,
            ventana_ok: false, sla_ok: false, holgura_sla_min: -40, fijo: true },
        ] },
      { tecnico_id: TEC2, tecnico: 'Tadeo Técnico', km: 17.8, minutos: 210,
        paradas: [
          { parada_id: 'a3', folio_id: 'f3', numero_folio: 'RT-000003', orden: 0, un_codigo: 'SUC-003',
            un_nombre: 'Sucursal Coyoacán', tipo_folio: 'preventivo', estado_folio: 'asignado', criticidad: null,
            llegada_estimada: '2026-11-13T15:00:00Z', fin_estimado: '2026-11-13T16:00:00Z',
            minutos_desde_anterior: 30, km_desde_anterior: 11.1, minutos_servicio: 60,
            ventana_ok: true, sla_ok: true, holgura_sla_min: 180, fijo: false },
        ] },
    ],
  }
}

const trazos: TrazoRuta[] = [
  { tecnico_id: TEC1, tecnico: 'Tomás Técnico', proveedor: 'estimado',
    puntos: [[19.43, -99.14], [19.4326, -99.1332], [19.4005, -99.17]] },
  { tecnico_id: TEC2, tecnico: 'Tadeo Técnico', proveedor: 'estimado',
    puntos: [[19.38, -99.16], [19.35, -99.162]] },
]

const propuesta: Propuesta = {
  id: PROP, plan_id: PLAN, disparador: 'desvio',
  motivo: 'Tomás Técnico se salió del corredor de su ruta 820 m durante 12 min',
  movimientos: [
    { folio_id: 'f3', numero_folio: 'RT-000003', de_tecnico_id: TEC1, a_tecnico_id: TEC2, orden: 1,
      llegada_estimada: '2026-11-13T16:40:00Z' },
  ],
  tecnicos_afectados: [TEC1, TEC2], vence_at: '2026-11-13T16:00:00Z',
  timestamp: '2026-11-13T15:40:00Z', tiempo_calculo_ms: 2500, sin_asignar: [],
}

const simulacion: Simulacion = {
  plan_id: PLAN, antes: { km: 44.2, fuera_ventana: 1, fuera_sla: 1 },
  despues: { km: 48.9, fuera_ventana: 0, fuera_sla: 1 }, diferencia_km: 4.7, rechazados: [],
  nota: 'Simulación sin efecto: nada se guardó.',
}

const RUTAS_PLAN = {
  'GET /api/rutas/mercados': () => ({ json: mercados }),
  'GET /api/rutas': () => ({ json: detallePlan() }),
  [`GET /api/rutas/${PLAN}/trazos`]: () => ({ json: trazos }),
  'GET /api/rutas/propuestas/pendientes': () => ({ json: [propuesta] }),
  'GET /api/rutas/configuracion': () => ({ json: configuracion }),
  'GET /api/rutas/tiempos-servicio': () => ({ json: tiempos }),
}

// ------------------------------------------------------------------ tablero y app de campo

const parametros: Parametros = {
  frecuencias: { jornada_activa_s: 30, pausa_s: 300, bateria_baja_s: 120, bateria_baja_pct: 20 },
  geocerca_radio_m: 150, jornada_cierre_horas: 2, sin_senal_min: 15, tiempo_muerto_min: 20,
  aviso_geolocalizacion: 'Mientras tu jornada esté iniciada, ACMA registra la ubicación de tu teléfono.',
  max_lote: 60, precision_maxima_m: 500, horas_recorrido: 2,
  desvio_ruta: 'El desvío se marca cuando el técnico se sale del corredor de su ruta',
}

const tecnicos: TecnicoEnTablero[] = [
  { tecnico_id: TEC1, usuario_id: 'u1', nombre: 'Tomás Técnico', numero_empleado: 'EMP-001',
    estatus: 'en_ruta', estatus_texto: 'En ruta', en_jornada: true, jornada_desde: '2026-11-13T14:00:00Z',
    minutos_en_estatus: 22, folios_pendientes: 2, lat: 19.4326, lng: -99.1332,
    ultima_posicion_at: '2026-11-13T15:30:00Z', precision_m: '12.0', bateria_pct: 80,
    vehiculo_placas: 'ACM-001', telefono: null,
    alerta: { tipo: 'TECNICO_DESVIO_RUTA', desde: '2026-11-13T15:20:00Z', escalada: false },
    respuesta_tecnico: null },
]

const tablero: Tablero = {
  generado_at: '2026-11-13T15:30:00Z', tecnicos, folios: [], unidades: [], alertas: [],
  indicadores: { completados: 2, total_dia: 6, tecnicos_activos: 1, alertas_abiertas: 1,
                 tiempo_promedio_atencion_horas: '2.10',
                 aviso_fase_2: 'El desvío de ruta y el ETA ya operan con distancias estimadas' },
  parametros, solo_lectura: false,
}

const eta: Eta = {
  tiene_eta: true, tecnico: 'Tomás Técnico', llegada_estimada: '2026-11-13T14:30:00Z', orden: 0,
  en_camino: false, minutos_restantes: 35, motivo: null,
}

const miRuta: MiRuta = {
  tiene_ruta: true, plan_id: PLAN, fecha: '2026-11-13', km: 26.4,
  paradas: [
    { folio_id: FOLIO, numero_folio: 'RT-000001', orden: 0, un_codigo: 'SUC-001', un_nombre: 'Sucursal Centro',
      direccion: 'Av. Juárez 100, Centro', estado_folio: 'asignado', tipo_folio: 'correctivo',
      llegada_estimada: '2026-11-13T14:30:00Z', fin_estimado: '2026-11-13T15:45:00Z', minutos_servicio: 75,
      minutos_desde_anterior: 18, km_desde_anterior: 6.2, lat: 19.4326, lng: -99.1332 },
    { folio_id: 'f2', numero_folio: 'RT-000002', orden: 1, un_codigo: 'SUC-002', un_nombre: 'Sucursal Polanco',
      direccion: 'Masaryk 200, Polanco', estado_folio: 'asignado', tipo_folio: 'correctivo',
      llegada_estimada: '2026-11-13T16:10:00Z', fin_estimado: '2026-11-13T17:10:00Z', minutos_servicio: 60,
      minutos_desde_anterior: 25, km_desde_anterior: 9.8, lat: null, lng: null },
  ],
}

function folio(): FolioResumen {
  return {
    id: FOLIO, created_at: '2026-11-13T12:00:00Z', updated_at: '2026-11-13T12:00:00Z', version_hash: null,
    numero_folio: 'RT-000001', tenant_id: T, prestador_id: 'p1', un_id: UN1, un_nombre: 'Sucursal Centro',
    un_codigo: 'SUC-001', equipo_id: EQ1, equipo_codigo: 'EQ-0001', equipo_nombre: 'Refrigerador vertical',
    tipo_falla_id: null, tipo_falla: null, tipo_folio: 'correctivo', estado: 'asignado', prioridad: 0,
    descripcion: 'No enfría la cámara de lácteos', tecnico_id: 'u1', tecnico_nombre: 'Tomás Técnico',
    severidad: { id: 's2', clave: 'alta', nombre: 'Alta', orden: 2, color_hex: '#b45309' },
    severidad_origen: 'automatica_matriz', confirmacion_un: true, monto_estimado: null,
    criticidad: 'A', capturado_por: 'sys', capturado_por_nombre: 'Sistema',
    capturado_at: '2026-11-13T12:00:00Z', fecha_falla: '2026-11-13T11:30:00Z', fecha_inicio_atencion: null,
    fecha_cierre: null, razon_cancelacion: null, flujo: null, triggers_pendientes: 0, antiguedad_horas: 3,
    plan_id: null, calendario_id: null, plan_nombre: null,
  }
}

function detalleFolio(): FolioDetalle {
  const f = folio()
  return {
    folio: f,
    captura: { capturado_por: 'sys', capturado_por_nombre: 'Sistema', capturado_at: f.capturado_at,
      un: { id: UN1, codigo: 'SUC-001', nombre: 'Sucursal Centro', direccion: 'Av. Juárez 100' },
      equipo: { id: EQ1, codigo: 'EQ-0001', nombre: 'Refrigerador vertical' },
      tipo_falla: null, descripcion: f.descripcion, geolat_captura: null, geolng_captura: null,
      confirmacion_un: true, confirmacion_un_timestamp: null, confirmacion_un_geolat: null,
      confirmacion_un_geolng: null, folio_duplicado_justificacion: null, folio_duplicado_ref_id: null,
      folio_duplicado_ref_numero: null },
    formulario_captura: null,
    asignacion: { tecnico_id: f.tecnico_id, tecnico_nombre: f.tecnico_nombre, asignado_at: null, vehiculo: null,
      orden_en_ruta: 1, ventana_inicio: null, ventana_fin: null },
    historial: [], reasignaciones: [], hallazgos: [], derivaciones: [], clasificacion: null, evidencias: [],
    formulario_atencion: null, refacciones: [], sla: null, encuesta: null, triggers_revision: [],
    aprobacion: null, decisiones: [], chat: [], financiero: {}, acciones: [], puede_aprobar: false,
  }
}

async function entrar(rol: Rol, ruta: string, rutas: Parameters<typeof simularApi>[0] = {},
                      extra: Partial<PerfilConTema> = {}) {
  localStorage.setItem('acma.sesion', '1')
  const llamadas = simularApi({
    'POST /api/auth/refresh': () => ({ json: TOKENS }),
    'GET /api/auth/yo': () => ({ json: perfil(rol, {
      prestador_id: ['despachador', 'admin_prestador', 'mesa_control', 'tecnico'].includes(rol) ? 'p1' : null,
      tenant_id: ['admin_empresa', 'admin_un', 'operador', 'supervisor_operadores'].includes(rol) ? T : null,
      ...extra }) }),
    'GET /api/configuracion/mis-permisos': () => ({ json: [] }),
    'GET /api/notificaciones/no-leidas': () => ({ json: { no_leidas: 0 } }),
    ...rutas,
  })
  renderApp(ruta)
  return llamadas
}

describe('Rutas y reasignación automática (F2-06)', () => {
  it('los enlaces de navegación son gratuitos y los textos dicen la hora y la holgura', () => {
    // Sin API ni llave: son los esquemas públicos de Waze y de Google Maps (§3 del prompt).
    expect(enlaceWaze(19.4326, -99.1332)).toBe('https://waze.com/ul?ll=19.4326,-99.1332&navigate=yes')
    expect(enlaceGoogleMaps(19.4326, -99.1332))
      .toBe('https://www.google.com/maps/dir/?api=1&destination=19.4326,-99.1332&travelmode=driving')
    expect(hora(null)).toBe('—')
    expect(hora('2026-11-13T14:05:00Z')).toMatch(/^\d{2}:\d{2}$/)
    expect(textoHolgura(null)).toBe('sin SLA')
    expect(textoHolgura(-40)).toBe('vencido por 40 min')
    expect(textoHolgura(45)).toBe('45 min de holgura')
    expect(textoHolgura(95)).toBe('1 h 35 min de holgura')
    expect(sumaPesosRutas(configuracion.pesos_json)).toBe(6541)
  })

  it('el despachador ve el plan en borrador con sus paradas, los motivos de lo que quedó fuera y lo publica',
     async () => {
    const llamadas = await entrar('despachador', '/rutas', {
      ...RUTAS_PLAN,
      [`POST /api/rutas/${PLAN}/publicar`]: () => ({
        json: { plan_id: PLAN, estado: 'publicado', asignados: 3, respetados: 1, tecnicos: 2 } }),
    })
    expect(await screen.findByText('Borrador')).toBeInTheDocument()
    expect(screen.getByText('3 folio(s) en ruta')).toBeInTheDocument()
    expect(screen.getByText('44.2 km en total')).toBeInTheDocument()
    expect(screen.getByText(/versión 1 · ortools · 3.6 s de cálculo/)).toBeInTheDocument()
    // El borrador avisa que los técnicos todavía no tienen nada.
    expect(screen.getByText(/los técnicos todavía no tienen estos folios/)).toBeInTheDocument()
    // Cada ruta con su orden, su llegada y su holgura; la parada en ejecución está fija.
    const ruta1 = screen.getByText('Tomás Técnico · 2 parada(s)').closest('section')!
    expect(within(ruta1).getByText('RT-000001')).toBeInTheDocument()
    expect(within(ruta1).getByText('1 h 35 min de holgura')).toBeInTheDocument()
    expect(within(ruta1).getByText('vencido por 40 min')).toBeInTheDocument()
    expect(within(ruta1).getByText('Fuera de ventana')).toBeInTheDocument()
    expect(within(ruta1).getByText('En ejecución')).toBeInTheDocument()
    // Solo una parada se puede mover: la que ya empezó, no.
    expect(within(ruta1).getAllByRole('button', { name: 'Mover' })).toHaveLength(1)
    // Lo que quedó fuera se explica en lugar de desaparecer.
    expect(screen.getByText(/Ningún técnico con la habilidad certificada/)).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Publicar y asignar' }))
    await waitFor(() => expect(llamadas.some((l) => l.clave === `POST /api/rutas/${PLAN}/publicar`)).toBe(true))
    expect(await screen.findByText(/3 folio\(s\) asignados y 1 respetados en 2 técnico\(s\)/)).toBeInTheDocument()
  })

  it('mover una parada se puede simular antes y respeta el destino elegido', async () => {
    const llamadas = await entrar('despachador', '/rutas', {
      ...RUTAS_PLAN,
      [`POST /api/rutas/${PLAN}/simulacion`]: () => ({ json: simulacion }),
      [`POST /api/rutas/${PLAN}/paradas/${PAR1}/mover`]: () => ({ json: detallePlan() }),
    })
    const user = userEvent.setup()
    const ruta1 = (await screen.findByText('Tomás Técnico · 2 parada(s)')).closest('section')!
    await user.click(within(ruta1).getByRole('button', { name: 'Mover' }))
    const dialogo = await screen.findByRole('dialog', { name: /Mover RT-000001/ })
    // El selector solo ofrece a los demás técnicos.
    expect(within(dialogo).getByRole('option', { name: 'Tadeo Técnico (1 paradas)' })).toBeInTheDocument()
    expect(within(dialogo).queryByRole('option', { name: /Tomás/ })).not.toBeInTheDocument()
    await user.selectOptions(within(dialogo).getByLabelText('Técnico destino'), TEC2)
    await user.click(within(dialogo).getByRole('button', { name: '¿Qué pasa si lo muevo?' }))
    // La simulación contesta en kilómetros y en paradas, y no guarda nada.
    expect(await within(dialogo).findByText(/\+4.7 km · 0 parada\(s\) fuera de ventana y 1 con el SLA vencido/))
      .toBeInTheDocument()
    expect(llamadas.some((l) => l.clave.startsWith(`POST /api/rutas/${PLAN}/paradas`))).toBe(false)
    await user.click(within(dialogo).getByRole('button', { name: 'Mover la parada' }))
    await waitFor(() => expect(llamadas.find((l) => l.clave === `POST /api/rutas/${PLAN}/paradas/${PAR1}/mover`)?.cuerpo)
      .toMatchObject({ tecnico_destino_id: TEC2, orden: null }))
  })

  it('la propuesta de desvío se acepta desde el tablero y hasta entonces nada cambia', async () => {
    const llamadas = await entrar('despachador', '/operaciones', {
      'GET /api/operacion/tablero': () => ({ json: tablero }),
      'GET /api/operacion/mi-jornada': () => ({ estado: 403,
        json: { codigo: 'PROHIBIDO', mensaje: 'Solo técnicos', detalles: [] } }),
      'GET /api/operacion/mis-alertas': () => ({ json: [] }),
      'GET /api/rutas/propuestas/pendientes': () => ({ json: [propuesta] }),
      [`POST /api/rutas/propuestas/${PROP}/aceptar`]: () => ({
        json: { recalculo_id: PROP, aplicados: 1, omitidos: [] } }),
    })
    // §6.8.4: el desvío se ve en la fila del técnico, con su nombre en texto y no solo por el color.
    const tecnicosPanel = await screen.findByTestId('panel-tecnicos')
    expect(await within(tecnicosPanel).findByText('Desvío de ruta')).toBeInTheDocument()
    const panel = await screen.findByTestId('panel-propuestas')
    expect(within(panel).getByText('Desvío de ruta')).toBeInTheDocument()
    expect(within(panel).getByText(/se salió del corredor de su ruta 820 m durante 12 min/)).toBeInTheDocument()
    expect(within(panel).getByText(/RT-000003 → llega/)).toBeInTheDocument()
    expect(screen.getByText('Nada cambia hasta que aceptas.')).toBeInTheDocument()
    expect(llamadas.some((l) => l.clave.includes('/aceptar'))).toBe(false)
    const user = userEvent.setup()
    await user.click(within(panel).getByRole('button', { name: 'Aceptar' }))
    await waitFor(() => expect(llamadas.some((l) => l.clave === `POST /api/rutas/propuestas/${PROP}/aceptar`))
      .toBe(true))
  })

  it('el operador ve la hora estimada de llegada, no la posición del técnico', async () => {
    await entrar('operador', `/campo/folio/${FOLIO}`, {
      [`GET /api/folios/${FOLIO}`]: () => ({ json: detalleFolio() }),
      [`GET /api/folios/${FOLIO}/chats`]: () => ({ json: [] }),
      'GET /api/operacion/eta': () => ({ json: eta }),
    })
    const tarjeta = await screen.findByTestId('eta-operador')
    expect(within(tarjeta).getByText('Llegada estimada')).toBeInTheDocument()
    expect(await within(tarjeta).findByText(/en 35 min/)).toBeInTheDocument()
    // §6.9.5: el cliente no ve el GPS ni el mapa del técnico.
    expect(screen.queryByTestId('mapa-tecnicos')).not.toBeInTheDocument()
  })

  it('sin ruta publicada la tarjeta del operador lo dice en vez de inventar una hora', async () => {
    await entrar('operador', `/campo/folio/${FOLIO}`, {
      [`GET /api/folios/${FOLIO}`]: () => ({ json: detalleFolio() }),
      [`GET /api/folios/${FOLIO}/chats`]: () => ({ json: [] }),
      'GET /api/operacion/eta': () => ({ json: {
        tiene_eta: false, tecnico: null, llegada_estimada: null, orden: null, en_camino: null,
        minutos_restantes: null, motivo: 'El folio no está en una ruta publicada de hoy' } as Eta }),
    })
    const tarjeta = await screen.findByTestId('eta-operador')
    expect(await within(tarjeta).findByText('El folio no está en una ruta publicada de hoy')).toBeInTheDocument()
  })

  it('el técnico ve su ruta ordenada con los enlaces de navegación y reporta una incidencia', async () => {
    const llamadas = await entrar('tecnico', '/campo', {
      'GET /api/folios': () => ({ json: [] }),
      'GET /api/operacion/mi-jornada': () => ({ json: {
        ...parametros, tecnico_id: TEC1, estatus: 'en_ruta', aviso_aceptado: true,
        jornada: { id: 'j1', inicio: '2026-11-13T14:00:00Z', estado: 'activa', dispositivo_id: 'demo',
                   posiciones: 12, pausa_desde: null, pausa_motivo: null } } }),
      'GET /api/operacion/mis-alertas': () => ({ json: [] }),
      'GET /api/operacion/mi-ruta': () => ({ json: miRuta }),
      'POST /api/operacion/incidencia': () => ({ json: {
        registrada: true, recalculo_id: PROP, movimientos: 2,
        mensaje: 'Listo: el despachador ya lo sabe y hay una propuesta con 2 movimiento(s)' } }),
    })
    const seccion = await screen.findByTestId('ruta-del-dia')
    expect(await within(seccion).findByText(/2 paradas · 26.4 km/)).toBeInTheDocument()
    expect(within(seccion).getByText('SUC-001 · Sucursal Centro')).toBeInTheDocument()
    expect(within(seccion).getByText('Av. Juárez 100, Centro')).toBeInTheDocument()
    expect(within(seccion).getByText(/6.2 km y 18 min de traslado · 75 min de trabajo/)).toBeInTheDocument()
    // La parada con coordenadas trae los dos enlaces; la que no las tiene, lo dice.
    expect(within(seccion).getByRole('link', { name: 'Abrir en Waze' }))
      .toHaveAttribute('href', enlaceWaze(19.4326, -99.1332))
    expect(within(seccion).getByRole('link', { name: 'Abrir en Google Maps' }))
      .toHaveAttribute('href', enlaceGoogleMaps(19.4326, -99.1332))
    expect(within(seccion).getByText('La unidad no tiene coordenadas registradas.')).toBeInTheDocument()
    // El reporte de incidencia es el disparador §6.8.2 que el técnico tiene a mano.
    const user = userEvent.setup()
    await user.click(within(seccion).getByRole('button', { name: 'Reportar incidencia' }))
    const dialogo = await screen.findByRole('dialog', { name: 'Reportar una incidencia' })
    await user.selectOptions(within(dialogo).getByLabelText('¿Qué pasó?'), 'salud')
    await user.type(within(dialogo).getByLabelText('Detalle (opcional)'), 'Me siento mal')
    await user.click(within(dialogo).getByRole('button', { name: 'Enviar el reporte' }))
    await waitFor(() => expect(llamadas.find((l) => l.clave === 'POST /api/operacion/incidencia')?.cuerpo)
      .toMatchObject({ tipo: 'salud', detalle: 'Me siento mal', folio_id: null }))
    expect(await screen.findByText(/hay una propuesta con 2 movimiento\(s\)/)).toBeInTheDocument()
  })

  it('el técnico sin ruta del día ve el motivo y no una pantalla vacía', async () => {
    await entrar('tecnico', '/campo', {
      'GET /api/folios': () => ({ json: [] }),
      'GET /api/operacion/mi-jornada': () => ({ json: {
        ...parametros, tecnico_id: TEC1, estatus: 'fuera_de_jornada', aviso_aceptado: false, jornada: null } }),
      'GET /api/operacion/mis-alertas': () => ({ json: [] }),
      'GET /api/operacion/mi-ruta': () => ({ json: {
        tiene_ruta: false, paradas: [], mensaje: 'Hoy no hay un plan de rutas publicado para tu mercado' } }),
    })
    const seccion = await screen.findByTestId('ruta-del-dia')
    expect(await within(seccion).findByText('Hoy no hay un plan de rutas publicado para tu mercado'))
      .toBeInTheDocument()
  })

  it('el cliente no entra al módulo de rutas: lo opera el prestador (§5.2)', async () => {
    await entrar('admin_empresa', '/rutas', RUTAS_PLAN)
    expect(await screen.findByText('Tu rol no tiene acceso a este módulo.')).toBeInTheDocument()
    expect(screen.queryByText('Rutas del día')).not.toBeInTheDocument()
  })
})
