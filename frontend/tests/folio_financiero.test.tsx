import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { PerfilConTema, Rol } from '../src/types/api'
import type { FolioDetalle, FolioResumen } from '../src/types/folios'
import type { Financiero } from '../src/types/inventario'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const T = '11111111-1111-1111-1111-111111111111'
const UN1 = 'u0000000-0000-0000-0000-000000000001'
const EQ1 = 'e0000000-0000-0000-0000-000000000001'
const FOLIO = '0f000000-0000-0000-0000-000000000071'

function folio(extra: Partial<FolioResumen> = {}): FolioResumen {
  return {
    id: FOLIO, created_at: '2026-10-28T10:00:00Z', updated_at: '2026-10-29T10:00:00Z', version_hash: null, numero_folio: 'CD-000071', tenant_id: T, prestador_id: 'p1',
    un_id: UN1, un_nombre: 'Sucursal Centro', un_codigo: 'SUC-001', equipo_id: EQ1, equipo_codigo: 'EQ-0001', equipo_nombre: 'Refrigerador vertical', tipo_falla_id: 'tf1',
    tipo_falla: 'No enfría', tipo_folio: 'correctivo', estado: 'cerrado', prioridad: 0, descripcion: 'El refrigerador no enfría', tecnico_id: 't1', tecnico_nombre: 'Tomás Técnico',
    severidad: null, severidad_origen: 'automatica_matriz', confirmacion_un: true, monto_estimado: null, criticidad: 'B', capturado_por: 'op', capturado_por_nombre: 'Olga Operadora',
    capturado_at: '2026-10-28T10:00:00Z', fecha_falla: '2026-10-28T09:00:00Z', fecha_inicio_atencion: '2026-10-28T10:30:00Z', fecha_cierre: '2026-10-28T15:00:00Z',
    razon_cancelacion: null, flujo: null, triggers_pendientes: 0, antiguedad_horas: 29, ...extra,
  }
}

function detalle(f: FolioResumen, extra: Partial<FolioDetalle> = {}): FolioDetalle {
  return {
    folio: f,
    captura: { capturado_por: 'op', capturado_por_nombre: 'Olga Operadora', capturado_at: f.capturado_at, un: { id: UN1, codigo: 'SUC-001', nombre: 'Sucursal Centro', direccion: 'Av. Juárez 100' },
      equipo: { id: EQ1, codigo: 'EQ-0001', nombre: 'Refrigerador vertical', criticidad: 'B' }, tipo_falla: 'No enfría', descripcion: f.descripcion, geolat_captura: null, geolng_captura: null,
      confirmacion_un: true, confirmacion_un_timestamp: f.capturado_at, confirmacion_un_geolat: null, confirmacion_un_geolng: null, folio_duplicado_justificacion: null,
      folio_duplicado_ref_id: null, folio_duplicado_ref_numero: null },
    formulario_captura: null, asignacion: { tecnico_id: 't1', tecnico_nombre: 'Tomás Técnico', asignado_at: '2026-10-28T10:10:00Z', vehiculo: null, orden_en_ruta: 1, ventana_inicio: null, ventana_fin: null },
    historial: [], reasignaciones: [], hallazgos: [], derivaciones: [], clasificacion: null, evidencias: [], formulario_atencion: null, refacciones: [],
    sla: { nivel_severidad_id: 's3', tiempo_respuesta_prometido_horas: 4, tiempo_resolucion_prometido_horas: 24, tiempo_respuesta_real_min: null, tiempo_resolucion_real_min: null, cumplimiento_respuesta: null, cumplimiento_resolucion: null },
    encuesta: null, triggers_revision: [], aprobacion: null, decisiones: [], chat: [], financiero: {}, acciones: [], puede_aprobar: false, ...extra,
  }
}

function financiero(extra: Partial<Financiero> = {}): Financiero {
  return {
    visible: true,
    costo: {
      id: 'co1', costo_refacciones: '8200.00', costo_mano_obra: '1750.00', costo_otros: '0.00', costo_total: '9950.00', moneda: 'MXN',
      horas_mano_obra: '3.5', tarifa_hora: '500.00', origen_horas: 'formulario', ajuste: '0.00', razon_ajuste: '', centro_costos: '',
      validado_por: null, validado_por_nombre: null, validado_at: null, documento_erp_ref: null,
    },
    refacciones: [{ id: 'rf1', descripcion: 'Compresor 1/3 HP', cantidad: '1', costo_unitario: '8200.00', origen: 'oc', articulo_id: 'a1', importe: '8200.00' }],
    gastos_caja_chica: [],
    puede_validar: true,
    ...extra,
  }
}

async function entrar(rol: Rol, ruta: string, rutas: Parameters<typeof simularApi>[0] = {}, extra: Partial<PerfilConTema> = {}) {
  localStorage.setItem('acma.sesion', '1')  // P11a: solo la marca; el refresh va en cookie httpOnly
  const esTenant = ['admin_empresa', 'admin_un', 'supervisor_operadores', 'operador'].includes(rol)
  const llamadas = simularApi({
    'POST /api/auth/refresh': () => ({ json: TOKENS }),
    'GET /api/auth/yo': () => ({ json: perfil(rol, { tenant_id: esTenant ? T : null, prestador_id: esTenant ? null : 'p1', ...extra }) }),
    'GET /api/notificaciones/no-leidas': () => ({ json: { no_leidas: 0 } }),
    'GET /api/unidades-negocio': () => ({ json: [] }),
    'GET /api/catalogos/severidades': () => ({ json: [] }),
    'GET /api/folios/transiciones': () => ({ json: [] }),
    [`GET /api/folios/${FOLIO}/chats`]: () => ({ json: [] }),
    ...rutas,
  })
  renderApp(ruta)
  return llamadas
}

describe('Sección financiera del folio', () => {
  it('Mesa de control ve el desglose del costo y al validarlo se carga al presupuesto y al ERP', async () => {
    let validado = false
    const yaValidado = financiero({
      costo: { ...financiero().costo!, costo_otros: '250.00', costo_total: '10200.00', centro_costos: 'MANTENIMIENTO',
               validado_por: 'mc', validado_por_nombre: 'Persona Prueba', validado_at: '2026-10-29T12:00:00Z', documento_erp_ref: 'PZ-0099' },
      puede_validar: false,
    })
    const llamadas = await entrar('mesa_control', `/folios/${FOLIO}`, {
      [`GET /api/folios/${FOLIO}`]: () => ({ json: detalle(folio()) }),
      [`GET /api/folios/${FOLIO}/costos`]: () => ({ json: validado ? yaValidado : financiero() }),
      [`POST /api/folios/${FOLIO}/costos/validar`]: () => { validado = true; return { json: yaValidado } },
    })
    const panel = await screen.findByTestId('financiero-folio', {}, { timeout: 5000 })
    expect(within(panel).getByTestId('costo-total')).toHaveTextContent('$9,950.00')
    expect(within(panel).getByText('Pendiente de validar')).toBeInTheDocument()
    expect(within(panel).getByText(/\(3\.5 h × \$500\.00, horas formulario\)/)).toBeInTheDocument()
    expect(within(panel).getByText('Compresor 1/3 HP')).toBeInTheDocument()
    expect(within(panel).getByText('Orden de compra')).toBeInTheDocument()
    const user = userEvent.setup()
    const validar = within(panel).getByTestId('validar-costo')
    await user.type(within(validar).getByLabelText('Otros costos'), '250')
    await user.type(within(validar).getByLabelText('Centro de costos'), 'MANTENIMIENTO')
    await user.click(within(validar).getByRole('button', { name: 'Validar costo' }))
    await waitFor(() => expect(llamadas.find((l) => l.clave === `POST /api/folios/${FOLIO}/costos/validar`)?.cuerpo).toEqual({
      ajuste: null, razon_ajuste: '', costo_otros: '250', centro_costos: 'MANTENIMIENTO' }))
    expect(await within(panel).findByText('Costo validado: se registró el gasto en el ERP y se cargó a los presupuestos aplicables')).toBeInTheDocument()
    expect(await within(panel).findByText('ERP PZ-0099')).toBeInTheDocument()
    expect(within(panel).getByTestId('costo-total')).toHaveTextContent('$10,200.00')
    expect(within(panel).queryByTestId('validar-costo')).not.toBeInTheDocument()
  })

  it('el ajuste exige razón escrita antes de poder validar', async () => {
    await entrar('mesa_control', `/folios/${FOLIO}`, {
      [`GET /api/folios/${FOLIO}`]: () => ({ json: detalle(folio()) }),
      [`GET /api/folios/${FOLIO}/costos`]: () => ({ json: financiero() }),
    })
    const validar = await screen.findByTestId('validar-costo', {}, { timeout: 5000 })
    const user = userEvent.setup()
    await user.type(within(validar).getByLabelText('Ajuste (+ o −)'), '-500')
    expect(within(validar).getByRole('button', { name: 'Validar costo' })).toBeDisabled()
    await user.type(within(validar).getByLabelText('Razón del ajuste'), 'Descuento acordado con el cliente')
    expect(within(validar).getByRole('button', { name: 'Validar costo' })).toBeEnabled()
  })

  it('al operador sin visibilidad de costos se le explica por qué no los ve', async () => {
    await entrar('operador', `/folios/${FOLIO}`, {
      [`GET /api/folios/${FOLIO}`]: () => ({ json: detalle(folio()) }),
      [`GET /api/folios/${FOLIO}/costos`]: () => ({ json: { visible: false, motivo: 'Tu rol no tiene habilitada la visibilidad de costos del contrato.', costo: null, refacciones: [], gastos_caja_chica: [], puede_validar: false } }),
    })
    expect(await screen.findByTestId('financiero-oculto', {}, { timeout: 5000 })).toHaveTextContent('Tu rol no tiene habilitada la visibilidad de costos del contrato.')
    expect(screen.queryByTestId('validar-costo')).not.toBeInTheDocument()
  })

  it('el folio pendiente de refacción ofrece generar la orden de compra', async () => {
    await entrar('despachador', `/folios/${FOLIO}`, {
      [`GET /api/folios/${FOLIO}`]: () => ({ json: detalle(folio({ estado: 'pendiente_refaccion', fecha_cierre: null })) }),
      [`GET /api/folios/${FOLIO}/costos`]: () => ({ json: financiero({ costo: null, puede_validar: false }) }),
    })
    expect(await screen.findByRole('link', { name: 'Generar orden de compra' }, { timeout: 5000 })).toHaveAttribute('href', '/inventario?vista=ordenes')
    const panel = await screen.findByTestId('financiero-folio')
    expect(within(panel).getByText('El costo se calcula al cerrar el folio: refacciones consumidas más mano de obra por la tarifa vigente.')).toBeInTheDocument()
  })
})
