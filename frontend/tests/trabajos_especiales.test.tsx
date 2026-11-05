import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { PerfilConTema, Rol } from '../src/types/api'
import type { RegistroSeguimiento } from '../src/types/minutas'
import type { TrabajoEspecial, TrabajoEspecialDetalle } from '../src/types/trabajos_especiales'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const T = '11111111-1111-1111-1111-111111111111'
const TE = 'e0000000-0000-0000-0000-000000000001'

function te(extra: Partial<TrabajoEspecial> = {}): TrabajoEspecial {
  return {
    id: TE, numero: 'TE-000002', tenant_id: T, prestador_id: 'p1', un_id: 'u1', un_codigo: 'SUC-002', un_nombre: 'Sucursal Polanco', equipo_id: null, equipo_codigo: null, equipo_nombre: null,
    cotizacion_id: null, cotizacion_numero: null, cotizacion_estado: null, cotizacion_retroactiva_id: null, cotizacion_retroactiva_numero: null, hallazgo_id: null,
    descripcion: 'Reubicación del anuncio luminoso', detalle_json: {}, estado: 'enviado_cliente', estado_desde: '2026-10-27T10:00:00Z', dias_en_estado: 1, urgencia: false,
    creado_por_id: 'd', creado_por_rol: 'despachador', creado_por_nombre: 'Diego Despachador', formulario_id: 'f', respuesta_formulario_id: null, monto: '8400.00', moneda: 'MXN',
    fecha_programada: null, fecha_inicio: null, fecha_cierre: null, tecnicos: [], tecnico_responsable_id: null, tecnico_responsable_nombre: null, folio_id: null, numero_folio: null,
    estado_folio: null, razon_cancelacion: null, version_enviada: 2, enviado_at: '2026-10-27T10:00:00Z', aceptado_at: null, programado_at: null, alertas_activas: [], destinos: ['aceptado', 'rechazado'],
    created_at: '2026-10-26T10:00:00Z', updated_at: '2026-10-27T10:00:00Z', ...extra,
  }
}

function detalle(extra: Partial<TrabajoEspecialDetalle> = {}): TrabajoEspecialDetalle {
  return {
    ...te(), historial: [{ id: 'h1', estado_anterior: null, estado_nuevo: 'creado', actor_id: 'd', actor_nombre: 'Diego', actor_rol: 'despachador', timestamp: '2026-10-26T10:00:00Z', notas: 'Creado', datos_json: {} },
      { id: 'h2', estado_anterior: 'rechazado', estado_nuevo: 'enviado_cliente', actor_id: 'd', actor_nombre: 'Diego', actor_rol: 'despachador', timestamp: '2026-10-27T10:00:00Z', notas: 'Se ajustó la mano de obra', datos_json: { version_enviada: 2 } }],
    respuestas_cliente: [{ id: 'r1', version_enviada: 1, respondido_por: 'a', respondido_por_nombre: 'Elena Empresa', decision: 'rechazado', comentario: 'El monto excede lo acordado', canal: 'email', timestamp: '2026-10-26T18:00:00Z' }],
    evidencias: [], requisitos_cierre_faltantes: [], puede_responder: true, ...extra,
  }
}

async function entrar(rol: Rol, ruta: string, rutas: Parameters<typeof simularApi>[0] = {}, extra: Partial<PerfilConTema> = {}) {
  localStorage.setItem('acma.sesion', '1')  // P11a: solo la marca; el refresh va en cookie httpOnly
  const llamadas = simularApi({
    'POST /api/auth/refresh': () => ({ json: TOKENS }),
    'GET /api/auth/yo': () => ({ json: perfil(rol, extra) }),
    'GET /api/notificaciones/no-leidas': () => ({ json: { no_leidas: 0 } }),
    'GET /api/unidades-negocio': () => ({ json: [] }),
    'GET /api/tenants': () => ({ json: [] }),
    ...rutas,
  })
  renderApp(ruta)
  return llamadas
}

describe('Trabajos especiales', () => {
  it('la bandeja del cliente muestra el TE por validar y acepta o rechaza con comentario', async () => {
    let estado = 'enviado_cliente'
    const llamadas = await entrar('admin_empresa', '/trabajos-especiales', {
      'GET /api/trabajos-especiales': () => ({ json: estado === 'enviado_cliente' ? [te()] : [] }),
      [`GET /api/trabajos-especiales/${TE}`]: () => ({ json: detalle({ estado: estado as TrabajoEspecial['estado'], puede_responder: estado === 'enviado_cliente' }) }),
      [`POST /api/trabajos-especiales/${TE}/rechazar`]: () => { estado = 'rechazado'; return { json: detalle({ estado: 'rechazado', puede_responder: false }) } },
    }, { tenant_id: T, prestador_id: null })
    await screen.findByRole('heading', { name: 'Trabajos especiales' })
    expect(screen.getByRole('tab', { name: 'Por validar', selected: true })).toBeInTheDocument()
    expect(await screen.findByText('TE-000002', {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByText('v2')).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'TE-000002' }))
    const panel = await screen.findByTestId('detalle-te', {}, { timeout: 5000 })
    expect(within(panel).getByText(/v1 · rechazado · Elena Empresa/)).toBeInTheDocument()
    const validacion = within(panel).getByTestId('validacion-cliente')
    expect(within(validacion).getByRole('button', { name: 'Rechazar' })).toBeDisabled()
    await user.type(within(validacion).getByLabelText('Comentario (obligatorio al rechazar)'), 'Sigue caro')
    await user.click(within(validacion).getByRole('button', { name: 'Rechazar' }))
    await waitFor(() => expect(llamadas.find((l) => l.clave === `POST /api/trabajos-especiales/${TE}/rechazar`)?.cuerpo).toEqual({ canal: 'app', comentario: 'Sigue caro' }))
    expect(await screen.findByText('TE-000002 rechazado')).toBeInTheDocument()
    expect(within(panel).queryByTestId('validacion-cliente')).not.toBeInTheDocument()
  })

  it('el Kanban del prestador mueve de columna y el detalle permite programar con técnicos', async () => {
    const aceptado = te({ estado: 'aceptado', destinos: ['programado', 'cancelado'], aceptado_at: '2026-10-27T12:00:00Z' })
    const programado = () => detalle({ ...aceptado, estado: 'programado', fecha_programada: '2026-11-03', folio_id: 'fo', numero_folio: 'CD-000050', estado_folio: 'asignado', destinos: ['cancelado'], puede_responder: false })
    let listo = false
    const llamadas = await entrar('despachador', '/trabajos-especiales?vista=kanban', {
      'GET /api/trabajos-especiales': () => ({ json: [listo ? programado() : aceptado] }),
      [`GET /api/trabajos-especiales/${TE}`]: () => ({ json: listo ? programado() : detalle({ ...aceptado, puede_responder: false }) }),
      'GET /api/catalogos/tecnicos': () => ({ json: [{ id: 't1', usuario_id: 'u-tomas', nombre: 'Tomás Técnico' }, { id: 't4', usuario_id: 'u-tania', nombre: 'Tania Técnica' }] }),
      [`POST /api/trabajos-especiales/${TE}/programar`]: () => { listo = true; return { json: programado() } },
    }, { prestador_id: 'p1' })
    const kanban = await screen.findByTestId('kanban-te')
    expect(within(kanban).getAllByRole('region').map((c) => c.getAttribute('aria-label'))).toEqual(['Creado', 'Enviado al cliente', 'Aceptado', 'Rechazado', 'Programado', 'En ejecución', 'Cerrado', 'Cancelado'])
    const tarjeta = await within(kanban).findByTestId(`tarjeta-te-${TE}`, {}, { timeout: 5000 })
    expect(within(within(kanban).getByRole('region', { name: 'Aceptado' })).getByText('TE-000002')).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(within(tarjeta).getByRole('button', { name: 'TE-000002' }))
    const panel = await screen.findByTestId('detalle-te', {}, { timeout: 5000 })
    const programar = await within(panel).findByTestId('programar-te', {}, { timeout: 5000 })
    await user.type(within(programar).getByLabelText('Fecha programada'), '2026-11-03')
    await user.selectOptions(await within(programar).findByLabelText('Técnico responsable'), 'u-tomas')
    await user.click(within(programar).getByLabelText('Tania Técnica'))
    await user.click(within(programar).getByRole('button', { name: 'Programar' }))
    await waitFor(() => expect(llamadas.find((l) => l.clave === `POST /api/trabajos-especiales/${TE}/programar`)?.cuerpo).toEqual({ fecha_programada: '2026-11-03', tecnico_ids: ['u-tomas', 'u-tania'], tecnico_responsable_id: 'u-tomas', notas: '' }))
    expect(await screen.findByText(/programado: el cliente recibe la confirmación de la fecha/)).toBeInTheDocument()
    expect(await within(panel).findByText(/CD-000050 · asignado/)).toBeInTheDocument()
  })

  it('la cotización autorizada se convierte en trabajo especial desde su detalle', async () => {
    const cot: RegistroSeguimiento = {
      id: 'q1', hallazgo_id: null, folio_id: null, numero_folio: null, tenant_id: T, prestador_id: 'p1', un_id: 'u1', un_codigo: 'SUC-002', un_nombre: 'Polanco', equipo_id: null, equipo_codigo: null,
      descripcion: 'Reemplazo del evaporador', origen: 'directo', estado: 'autorizada', estado_desde: '2026-10-27T10:00:00Z', dias_en_estado: 1, alertas_activas: [], proxima_alerta: 'COTIZACION_AUTORIZADA_SIN_CONVERTIR',
      urgencia_hallazgo: null, destinos: ['convertida'], created_at: '2026-10-27T10:00:00Z', updated_at: '2026-10-27T10:00:00Z', numero: 'COT-00002', monto: '18400.00', moneda: 'MXN', pdf_disponible: false,
      estado_trabajo_especial: null, trabajo_especial_id: null, trabajo_especial_numero: null, envios_externos: [],
    }
    let convertida = false
    const llamadas = await entrar('despachador', '/seguimiento?modulo=cotizaciones&registro=q1', {
      'GET /api/seguimiento/cotizaciones': () => ({ json: [convertida ? { ...cot, estado: 'convertida', trabajo_especial_id: TE, trabajo_especial_numero: 'TE-000005', estado_trabajo_especial: 'creado', destinos: [] } : cot] }),
      'GET /api/seguimiento/cotizaciones/q1': () => ({ json: { ...(convertida ? { ...cot, estado: 'convertida', trabajo_especial_id: TE, trabajo_especial_numero: 'TE-000005', estado_trabajo_especial: 'creado', destinos: [] } : cot), historial: [] } }),
      'POST /api/seguimiento/cotizaciones/q1/convertir': () => { convertida = true; return { json: { ...cot, estado: 'convertida', trabajo_especial: { id: TE, numero: 'TE-000005' } } } },
    }, { prestador_id: 'p1' })
    const panel = await screen.findByTestId('detalle-registro', {}, { timeout: 5000 })
    const user = userEvent.setup()
    await user.click(within(panel).getByRole('button', { name: 'Convertir en Trabajo Especial' }))
    await waitFor(() => expect(llamadas.some((l) => l.clave === 'POST /api/seguimiento/cotizaciones/q1/convertir')).toBe(true))
    expect(await screen.findByText('COT-00002 convertida en trabajo especial')).toBeInTheDocument()
    expect(await within(panel).findByRole('link', { name: 'TE-000005 · creado' })).toHaveAttribute('href', `/trabajos-especiales?registro=${TE}`)
    expect(within(panel).queryByRole('button', { name: 'Convertir en Trabajo Especial' })).not.toBeInTheDocument()
  })
})
