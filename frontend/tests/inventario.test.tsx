import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { PerfilConTema, Rol } from '../src/types/api'
import type { Articulo, Existencia, Movimiento, OrdenCompra, Ubicacion } from '../src/types/inventario'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const ART = 'a1000000-0000-0000-0000-000000000001'
const ALM = 'ub000000-0000-0000-0000-000000000001'
const VEH = 'ub000000-0000-0000-0000-000000000002'

const articulo: Articulo = {
  id: ART, prestador_id: 'p1', codigo: 'REF-0001', numero_parte: 'TRM-220', descripcion: 'Termostato digital 220V', unidad: 'pieza', categoria: 'Refrigeración',
  costo_unitario_vigente: '480.00', stock_minimo_default: '4', activo: true, created_at: '2026-10-01T10:00:00Z', updated_at: '2026-10-01T10:00:00Z',
}
const ubicaciones: Ubicacion[] = [
  { id: ALM, prestador_id: 'p1', tipo: 'almacen', nombre: 'Almacén central', tecnico_id: null, placas: null, activo: true, created_at: '2026-10-01T10:00:00Z', updated_at: '2026-10-01T10:00:00Z' },
  { id: VEH, prestador_id: 'p1', tipo: 'vehiculo', nombre: 'Vehículo de Tomás Técnico', tecnico_id: 't1', placas: 'ABC-123', activo: true, created_at: '2026-10-01T10:00:00Z', updated_at: '2026-10-01T10:00:00Z' },
]

function existencia(extra: Partial<Existencia> = {}): Existencia {
  return {
    id: 'ex1', ubicacion_id: ALM, ubicacion: 'Almacén central', ubicacion_tipo: 'almacen', articulo_id: ART, codigo: 'REF-0001', descripcion: 'Termostato digital 220V',
    unidad: 'pieza', categoria: 'Refrigeración', cantidad: '10', stock_minimo: '4', costo_promedio: '480.00', bajo_minimo: false, updated_at: '2026-10-28T10:00:00Z', ...extra,
  }
}

async function entrar(rol: Rol, ruta: string, rutas: Parameters<typeof simularApi>[0] = {}, extra: Partial<PerfilConTema> = {}) {
  localStorage.setItem('acma.sesion', '1')  // P11a: solo la marca; el refresh va en cookie httpOnly
  const llamadas = simularApi({
    'POST /api/auth/refresh': () => ({ json: TOKENS }),
    'GET /api/auth/yo': () => ({ json: perfil(rol, { prestador_id: 'p1', ...extra }) }),
    'GET /api/notificaciones/no-leidas': () => ({ json: { no_leidas: 0 } }),
    'GET /api/inventario/ubicaciones': () => ({ json: ubicaciones }),
    'GET /api/inventario/articulos': () => ({ json: [articulo] }),
    ...rutas,
  })
  renderApp(ruta)
  return llamadas
}

describe('Inventario', () => {
  it('el Admin prestador traspasa del almacén al vehículo del técnico y la existencia aparece en el vehículo', async () => {
    let traspasado = false
    const llamadas = await entrar('admin_prestador', '/inventario', {
      'GET /api/inventario/existencias': () => ({ json: traspasado
        ? [existencia({ cantidad: '8' }), existencia({ id: 'ex2', ubicacion_id: VEH, ubicacion: 'Vehículo de Tomás Técnico', ubicacion_tipo: 'vehiculo', cantidad: '2', stock_minimo: '1' })]
        : [existencia()] }),
      'POST /api/inventario/movimientos/traspaso': () => {
        traspasado = true
        const m: Movimiento = {
          id: 'm1', timestamp: '2026-10-28T11:00:00Z', tipo: 'traspaso', origen: 'almacen', cantidad: '2', costo_unitario: '480.00', articulo_id: ART, codigo: 'REF-0001',
          descripcion: 'Termostato digital 220V', ubicacion_origen: 'Almacén central', ubicacion_destino: 'Vehículo de Tomás Técnico', folio_id: null, numero_folio: null,
          razon: 'Resurtido de la ruta', referencia_externa: null, registrado_por: 'Persona Prueba',
        }
        return { estado: 201, json: m }
      },
    })
    await screen.findByRole('heading', { name: 'Inventario' })
    expect(await screen.findByText('Termostato digital 220V')).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Traspaso' }))
    const form = await screen.findByTestId('form-traspaso')
    await user.selectOptions(await within(form).findByLabelText('Artículo'), ART)
    await user.selectOptions(within(form).getByLabelText('Origen'), ALM)
    await user.selectOptions(within(form).getByLabelText('Destino'), VEH)
    await user.clear(within(form).getByLabelText('Cantidad'))
    await user.type(within(form).getByLabelText('Cantidad'), '2')
    await user.type(within(form).getByLabelText('Razón o nota'), 'Resurtido de la ruta')
    await user.click(within(form).getByRole('button', { name: 'Registrar' }))
    await waitFor(() => expect(llamadas.find((l) => l.clave === 'POST /api/inventario/movimientos/traspaso')?.cuerpo).toEqual({
      articulo_id: ART, origen_id: ALM, destino_id: VEH, cantidad: '2', razon: 'Resurtido de la ruta' }))
    expect(await screen.findByText('Traspaso registrado')).toBeInTheDocument()
    expect(await screen.findByText('Vehículo de Tomás Técnico')).toBeInTheDocument()
  })

  it('marca las existencias bajo mínimo y el técnico solo ve su vehículo sin acciones de almacén', async () => {
    await entrar('tecnico', '/inventario', {
      'GET /api/inventario/existencias': () => ({ json: [existencia({ ubicacion_id: VEH, ubicacion: 'Vehículo de Tomás Técnico', ubicacion_tipo: 'vehiculo', cantidad: '1', stock_minimo: '3', bajo_minimo: true })] }),
    })
    expect(await screen.findByText('Bajo mínimo')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Mi vehículo' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.queryByRole('tab', { name: 'Órdenes de compra' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Traspaso' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Nuevo artículo' })).not.toBeInTheDocument()
  })

  it('la OC pasa de borrador a recibida y entonces ya no admite cancelación', async () => {
    const partida = { id: 'pa1', articulo_id: ART, codigo: 'REF-0001', descripcion: 'Termostato digital 220V', cantidad: '2', costo_unitario: '480.00', recibido: '0' }
    let oc: OrdenCompra = {
      id: 'oc1', prestador_id: 'p1', tenant_id: null, numero: 'OC-000012', folio_id: null, numero_folio: null, proveedor: 'Refaccionaria del Norte',
      estado: 'borrador', estado_desde: '2026-10-28T10:00:00Z', total: '960.00', moneda: 'MXN', ubicacion_destino_id: ALM, notas: '', aprobada_por: null,
      aprobada_at: null, recibida_at: null, razon_cancelacion: null, numero_oc_erp: null, created_by: 'd1', partidas: [partida],
      created_at: '2026-10-28T10:00:00Z', updated_at: '2026-10-28T10:00:00Z',
    }
    const llamadas = await entrar('admin_prestador', '/inventario?vista=ordenes&oc=oc1', {
      'GET /api/inventario/ordenes-compra': () => ({ json: [oc] }),
      'GET /api/inventario/ordenes-compra/oc1': () => ({ json: oc }),
      'POST /api/inventario/ordenes-compra/oc1/aprobar': () => { oc = { ...oc, estado: 'aprobada', aprobada_at: '2026-10-28T12:00:00Z', numero_oc_erp: 'ERP-77' }; return { json: oc } },
      'POST /api/inventario/ordenes-compra/oc1/recibir': () => {
        oc = { ...oc, estado: 'recibida', recibida_at: '2026-10-29T09:00:00Z', partidas: [{ ...partida, recibido: '2' }] }
        return { json: oc }
      },
    })
    const panel = await screen.findByTestId('detalle-oc', {}, { timeout: 5000 })
    expect(within(panel).getByText(/REF-0001 · Termostato digital 220V — 2 × \$480\.00/)).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(within(panel).getByRole('button', { name: 'Aprobar' }))
    await waitFor(() => expect(llamadas.some((l) => l.clave === 'POST /api/inventario/ordenes-compra/oc1/aprobar')).toBe(true))
    expect(await within(panel).findByText('ERP-77')).toBeInTheDocument()
    await user.click(within(panel).getByRole('button', { name: 'Marcar como recibida' }))
    await waitFor(() => expect(llamadas.some((l) => l.clave === 'POST /api/inventario/ordenes-compra/oc1/recibir')).toBe(true))
    expect(await screen.findByRole('dialog', { name: 'OC-000012 · Recibida' })).toBeInTheDocument()
    expect(within(panel).getByText(/· recibido 2/)).toBeInTheDocument()
    expect(within(panel).queryByRole('button', { name: 'Cancelar OC' })).not.toBeInTheDocument()
  })
})
