import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { PerfilConTema, Rol } from '../src/types/api'
import type { RegistroSeguimiento } from '../src/types/minutas'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const T = '11111111-1111-1111-1111-111111111111'
const UN1 = 'u0000000-0000-0000-0000-000000000001'

function registro(extra: Partial<RegistroSeguimiento> = {}): RegistroSeguimiento {
  return {
    id: 'q0000000-0000-0000-0000-000000000001', hallazgo_id: null, folio_id: null, numero_folio: null, tenant_id: T, prestador_id: 'p1', un_id: UN1, un_codigo: 'SUC-001', un_nombre: 'Sucursal Centro',
    equipo_id: null, equipo_codigo: 'EQ-0001', descripcion: 'Cambio de empaque', origen: 'minuta', estado: 'solicitada', estado_desde: '2026-10-20T10:00:00Z', dias_en_estado: 8,
    alertas_activas: ['COTIZACION_SIN_PREPARAR'], proxima_alerta: 'COTIZACION_SIN_PREPARAR', urgencia_hallazgo: 'alta', destinos: ['en_preparacion', 'enviada'], created_at: '2026-10-20T10:00:00Z', updated_at: '2026-10-20T10:00:00Z',
    numero: 'COT-00001', monto: null, moneda: 'MXN', pdf_disponible: false, hash_pdf: null, estado_trabajo_especial: null, envios_externos: [], ...extra,
  }
}

async function entrar(rol: Rol, ruta: string, rutas: Parameters<typeof simularApi>[0] = {}, extra: Partial<PerfilConTema> = {}) {
  localStorage.setItem('acma.refresh', TOKENS.refresh_token)
  const llamadas = simularApi({
    'POST /api/auth/refresh': () => ({ json: TOKENS }),
    'GET /api/auth/yo': () => ({ json: perfil(rol, { prestador_id: 'p1', ...extra }) }),
    'GET /api/notificaciones/no-leidas': () => ({ json: { no_leidas: 2 } }),
    'GET /api/unidades-negocio': () => ({ json: [] }),
    'GET /api/tenants': () => ({ json: [] }),
    ...rutas,
  })
  renderApp(ruta)
  return llamadas
}

describe('Módulos de seguimiento', () => {
  it('el Kanban pinta en rojo las tarjetas con alertas y mover de columna cambia el estado con historial', async () => {
    let estado = 'solicitada'
    const llamadas = await entrar('despachador', '/seguimiento?modulo=cotizaciones&vista=kanban', {
      'GET /api/seguimiento/cotizaciones': () => ({ json: [registro({ estado, alertas_activas: estado === 'solicitada' ? ['COTIZACION_SIN_PREPARAR'] : [], destinos: estado === 'solicitada' ? ['en_preparacion', 'enviada'] : ['enviada'] })] }),
      'POST /api/seguimiento/cotizaciones/q0000000-0000-0000-0000-000000000001/estado': (cuerpo) => { estado = (cuerpo as { estado: string }).estado; return { json: registro({ estado }) } },
    })
    const kanban = await screen.findByTestId('kanban')
    const columnas = within(kanban).getAllByRole('region')
    expect(columnas.map((c) => c.getAttribute('aria-label'))).toEqual(['Solicitada por admin UN', 'En preparación', 'Enviada al cliente', 'Autorizada', 'Rechazada', 'Convertida en TE'])
    const tarjeta = await within(kanban).findByTestId('tarjeta-q0000000-0000-0000-0000-000000000001', {}, { timeout: 5000 })
    expect(tarjeta.className).toContain('red')
    expect(within(tarjeta).getByText(/8 d · COTIZACION_SIN_PREPARAR/)).toBeInTheDocument()
    const user = userEvent.setup()
    await user.selectOptions(within(tarjeta).getByLabelText('Mover COT-00001'), 'en_preparacion')
    await waitFor(() => expect(llamadas.some((l) => l.clave === 'POST /api/seguimiento/cotizaciones/q0000000-0000-0000-0000-000000000001/estado')).toBe(true))
    expect(llamadas.find((l) => l.clave.endsWith('/estado'))!.cuerpo).toEqual({ estado: 'en_preparacion' })
    expect(await screen.findByText('COT-00001 → En preparación')).toBeInTheDocument()
    await waitFor(() => expect(within(within(kanban).getByRole('region', { name: 'En preparación' })).getByText('COT-00001')).toBeInTheDocument())
    expect(within(kanban).getByTestId('tarjeta-q0000000-0000-0000-0000-000000000001').className).not.toContain('red')
  })

  it('el listado muestra días en el estado, próxima alerta y la columna del trabajo especial; el Admin UN no ve el Kanban', async () => {
    const enviada = registro({ estado: 'enviada', alertas_activas: [], proxima_alerta: 'COTIZACION_SIN_RESPUESTA', monto: '1850.00', destinos: ['autorizada', 'rechazada'], pdf_disponible: true })
    await entrar('admin_un', '/seguimiento?modulo=cotizaciones', {
      'GET /api/seguimiento/cotizaciones': () => ({ json: [enviada] }),
      'GET /api/seguimiento/cotizaciones/q0000000-0000-0000-0000-000000000001': () => ({ json: { ...enviada, historial: [{ id: 'h1', estado_anterior: null, estado_nuevo: 'solicitada', usuario_nombre: 'Úrsula', actor_rol: 'admin_un', timestamp: '2026-10-20T10:00:00Z', notas: 'Solicitada (minuta)', datos_json: {} }] } }),
    }, { tenant_id: T, prestador_id: null })
    await screen.findByRole('heading', { name: 'Módulos de seguimiento' })
    expect(await screen.findByText('COT-00001', {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByText('COTIZACION_SIN_RESPUESTA')).toBeInTheDocument()
    expect(screen.getByText('Estado del trabajo especial')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Tablero Kanban' })).not.toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'COT-00001' }))
    const detalle = await screen.findByTestId('detalle-registro', {}, { timeout: 5000 })
    expect(within(detalle).getByRole('button', { name: 'Autorizar' })).toBeInTheDocument()
    expect(within(detalle).getByRole('button', { name: 'Rechazar' })).toBeInTheDocument()
  })

  it('el reporte ejecutivo muestra métricas y permite exportar', async () => {
    await entrar('admin_prestador', '/seguimiento?vista=reporte', {
      'GET /api/seguimiento/reporte/ejecutivo': () => ({ json: { desde: '2026-09-28', hasta: '2026-10-28', tiempo_promedio_resolucion_dias: { cotizaciones: 4.5, por_presupuesto: null, seguimiento_interno: 10, reprogramacion: null },
        totales: { cotizaciones: 3, por_presupuesto: 2, seguimiento_interno: 2, reprogramacion: 2 }, tasa_conversion_cotizaciones: 50, cotizaciones: { solicitada: 1, en_preparacion: 0, enviada: 1, autorizada: 1, rechazada: 0, convertida: 0 },
        hallazgos_recurrentes: [{ tipo_equipo: 'Refrigerador vertical', total: 4 }], monto_potencial: [{ un_id: UN1, un_codigo: 'SUC-003', diferidos: 1, monto_potencial: '9500.00' }] } }),
    })
    const reporte = await screen.findByTestId('reporte-ejecutivo')
    expect(await within(reporte).findByText('50%', {}, { timeout: 5000 })).toBeInTheDocument()
    expect(within(reporte).getByText('Refrigerador vertical: 4')).toBeInTheDocument()
    expect(within(reporte).getByText(/SUC-003: 1 diferidos/)).toBeInTheDocument()
    expect(within(reporte).getByRole('button', { name: 'Exportar Excel' })).toBeInTheDocument()
    expect(within(reporte).getByRole('button', { name: 'Exportar PDF' })).toBeInTheDocument()
  })
})
