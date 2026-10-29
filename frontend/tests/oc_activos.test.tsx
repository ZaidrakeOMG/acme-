import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { PerfilConTema, Rol } from '../src/types/api'
import type { FolioResumen } from '../src/types/folios'
import type { AutorizacionActivoDetalle, PendienteOC } from '../src/types/trabajos_especiales'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const T = '11111111-1111-1111-1111-111111111111'
const FOLIO = '0f000000-0000-0000-0000-000000000041'

const folio: FolioResumen = {
  id: FOLIO, created_at: '2026-10-27T10:00:00Z', updated_at: '2026-10-27T10:00:00Z', version_hash: null, numero_folio: 'CD-000041', tenant_id: T, prestador_id: 'p1', un_id: 'u1', un_nombre: 'Sucursal Centro',
  un_codigo: 'SUC-001', equipo_id: 'e1', equipo_codigo: 'EQ-0001', equipo_nombre: 'Refrigerador', tipo_falla_id: 'tf', tipo_falla: 'No enciende', tipo_folio: 'correctivo', estado: 'en_revision', prioridad: 0,
  descripcion: 'Instalación de refrigerador vertical adicional', tecnico_id: null, tecnico_nombre: null, severidad: null, severidad_origen: 'automatica_matriz', confirmacion_un: true, monto_estimado: null,
  criticidad: 'A', capturado_por: 'op', capturado_por_nombre: 'Olga', capturado_at: '2026-10-27T10:00:00Z', fecha_falla: '2026-10-27T10:00:00Z', fecha_inicio_atencion: null, fecha_cierre: null,
  razon_cancelacion: null, flujo: null, triggers_pendientes: 1, antiguedad_horas: 30, es_instalacion_activo: true,
}

function pendiente(extra: Partial<PendienteOC> = {}): PendienteOC {
  return {
    id: 'a1', folio_id: FOLIO, tenant_id: T, prestador_id: 'p1', un_id: 'u1', estatus_multinivel: 'pendiente_iniciar_tramite', estatus_nombre: 'Pendiente de iniciar trámite', estatus_desde: '2026-10-27T10:00:00Z',
    dias_en_estatus: 1, numero_oc_provisional: null, numero_oc_definitivo: null, fecha_autorizacion_erp: null, registrado_por: null, notas: '', decision_rechazo: null, periodo_presupuestal_destino: null,
    origen: 'captura', datos_equipo: { tipo_equipo: 'Refrigerador vertical', marca: 'Imbera', modelo: 'VR-12', numero_serie: 'IMB-0451', valor_reposicion: '28500' }, hallazgo_presupuesto_id: null,
    destinos: ['oc_en_tramite', 'oc_autorizada', 'oc_rechazada'], created_at: '2026-10-27T10:00:00Z', updated_at: '2026-10-27T10:00:00Z', folio, ...extra,
  }
}

function detalle(extra: Partial<AutorizacionActivoDetalle> = {}): AutorizacionActivoDetalle {
  return { ...pendiente(), historial: [{ id: 'h1', estatus_anterior: null, estatus_nuevo: 'pendiente_iniciar_tramite', actor_id: 'op', actor_nombre: 'Olga', actor_rol: 'operador', timestamp: '2026-10-27T10:00:00Z', notas: 'Clasificado en el formulario' }], equipo_instalado: null, ...extra }
}

async function entrar(rol: Rol, ruta: string, rutas: Parameters<typeof simularApi>[0] = {}, extra: Partial<PerfilConTema> = {}) {
  localStorage.setItem('acma.refresh', TOKENS.refresh_token)
  const llamadas = simularApi({
    'POST /api/auth/refresh': () => ({ json: TOKENS }),
    'GET /api/auth/yo': () => ({ json: perfil(rol, { tenant_id: T, ...extra }) }),
    'GET /api/notificaciones/no-leidas': () => ({ json: { no_leidas: 0 } }),
    ...rutas,
  })
  renderApp(ruta)
  return llamadas
}

describe('OC de activos', () => {
  it('el Admin empresa ve los pendientes, registra la OC autorizada y el folio queda listo para asignar', async () => {
    let autorizada = false
    const llamadas = await entrar('admin_empresa', '/oc-activos', {
      'GET /api/oc-activos/pendientes': () => ({ json: [autorizada ? pendiente({ estatus_multinivel: 'listo_para_asignar', estatus_nombre: 'Folio listo para asignar', numero_oc_definitivo: '4500123987', destinos: [], folio: { ...folio, estado: 'autorizado' } }) : pendiente()] }),
      [`GET /api/oc-activos/${FOLIO}`]: () => ({ json: autorizada
        ? detalle({ estatus_multinivel: 'listo_para_asignar', estatus_nombre: 'Folio listo para asignar', numero_oc_definitivo: '4500123987', fecha_autorizacion_erp: '2026-10-28', destinos: [], folio: { ...folio, estado: 'autorizado' },
                    historial: [...detalle().historial, { id: 'h2', estatus_anterior: 'pendiente_iniciar_tramite', estatus_nuevo: 'oc_autorizada', actor_id: 'ae', actor_nombre: 'Elena', actor_rol: 'admin_empresa', timestamp: '2026-10-28T10:00:00Z', notas: 'OC liberada' },
                                { id: 'h3', estatus_anterior: 'oc_autorizada', estatus_nuevo: 'listo_para_asignar', actor_id: null, actor_nombre: null, actor_rol: 'sistema', timestamp: '2026-10-28T10:00:01Z', notas: '' }] })
        : detalle() }),
      [`POST /api/oc-activos/${FOLIO}/estatus`]: () => { autorizada = true; return { json: detalle({ estatus_multinivel: 'listo_para_asignar', destinos: [] }) } },
    })
    await screen.findByRole('heading', { name: 'OC de activos' })
    expect(await screen.findByText('Pendiente de iniciar trámite', {}, { timeout: 5000 })).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByTestId('oc-CD-000041'))
    const panel = await screen.findByTestId('detalle-oc', {}, { timeout: 5000 })
    expect(within(panel).getByText(/Refrigerador vertical · Imbera · VR-12 · IMB-0451/)).toBeInTheDocument()
    const registrar = within(panel).getByTestId('registrar-oc')
    expect(within(registrar).getByRole('button', { name: 'Registrar' })).toBeDisabled()
    await user.selectOptions(within(registrar).getByLabelText('Nuevo estatus'), 'oc_autorizada')
    expect(within(registrar).getByRole('button', { name: 'Registrar' })).toBeDisabled()  // faltan número definitivo y fecha
    await user.type(within(registrar).getByLabelText('Número de OC definitivo'), '4500123987')
    await user.type(within(registrar).getByLabelText('Fecha de autorización en el ERP'), '2026-10-28')
    await user.type(within(registrar).getByLabelText('Notas'), 'OC liberada')
    await user.click(within(registrar).getByRole('button', { name: 'Registrar' }))
    await waitFor(() => expect(llamadas.find((l) => l.clave === `POST /api/oc-activos/${FOLIO}/estatus`)?.cuerpo).toEqual({
      estatus: 'oc_autorizada', numero_oc_provisional: null, numero_oc_definitivo: '4500123987', fecha_autorizacion_erp: '2026-10-28', notas: 'OC liberada', decision_rechazo: null, periodo_presupuestal_destino: null }))
    expect(await screen.findByText('CD-000041: OC autorizada')).toBeInTheDocument()
    expect(await within(panel).findByText(/OC autorizada → Folio listo para asignar · sistema/)).toBeInTheDocument()
    expect(within(panel).queryByTestId('registrar-oc')).not.toBeInTheDocument()
  })

  it('el rechazo exige la decisión y el período cuando se reprograma; el Admin UN solo consulta', async () => {
    let rechazada = false
    const rechazo = () => detalle({ estatus_multinivel: 'oc_rechazada', decision_rechazo: 'reprogramar_periodo', periodo_presupuestal_destino: '2027-T1', destinos: [], folio: { ...folio, estado: 'cancelado' } })
    const llamadas = await entrar('admin_empresa', `/oc-activos?folio=${FOLIO}`, {
      'GET /api/oc-activos/pendientes': () => ({ json: [pendiente()] }),
      [`GET /api/oc-activos/${FOLIO}`]: () => ({ json: rechazada ? rechazo() : detalle() }),
      [`POST /api/oc-activos/${FOLIO}/estatus`]: () => { rechazada = true; return { json: rechazo() } },
    })
    const panel = await screen.findByTestId('detalle-oc', {}, { timeout: 5000 })
    const registrar = within(panel).getByTestId('registrar-oc')
    const user = userEvent.setup()
    await user.selectOptions(within(registrar).getByLabelText('Nuevo estatus'), 'oc_rechazada')
    expect(within(registrar).getByRole('button', { name: 'Registrar' })).toBeDisabled()
    await user.selectOptions(within(registrar).getByLabelText('Decisión'), 'reprogramar_periodo')
    expect(within(registrar).getByRole('button', { name: 'Registrar' })).toBeDisabled()
    await user.type(within(registrar).getByLabelText('Período destino (p. ej. 2027-T1)'), '2027-T1')
    await user.click(within(registrar).getByRole('button', { name: 'Registrar' }))
    await waitFor(() => expect(llamadas.find((l) => l.clave === `POST /api/oc-activos/${FOLIO}/estatus`)?.cuerpo).toMatchObject({ estatus: 'oc_rechazada', decision_rechazo: 'reprogramar_periodo', periodo_presupuestal_destino: '2027-T1' }))
    expect(await within(panel).findByText('Reprogramado al período 2027-T1')).toBeInTheDocument()
  })

  it('el Admin UN ve la vista sin el formulario de registro', async () => {
    await entrar('admin_un', `/oc-activos?folio=${FOLIO}`, {
      'GET /api/oc-activos/pendientes': () => ({ json: [pendiente()] }),
      [`GET /api/oc-activos/${FOLIO}`]: () => ({ json: detalle() }),
    })
    const panel = await screen.findByTestId('detalle-oc', {}, { timeout: 5000 })
    expect(within(panel).queryByTestId('registrar-oc')).not.toBeInTheDocument()
    expect(within(panel).getByTestId('historial-oc')).toHaveTextContent('Clasificado en el formulario')
  })
})
