import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { PerfilConTema, Rol } from '../src/types/api'
import type { Consolidado, ConsumoPresupuesto, NivelConsolidado, Presupuesto } from '../src/types/inventario'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const T = '11111111-1111-1111-1111-111111111111'
const UN1 = 'u0000000-0000-0000-0000-000000000001'
const UN2 = 'u0000000-0000-0000-0000-000000000002'
const P_CERCA = 'pr000000-0000-0000-0000-000000000001'
const P_EXCEDIDO = 'pr000000-0000-0000-0000-000000000002'

function presupuesto(extra: Partial<Presupuesto> = {}): Presupuesto {
  return {
    id: P_CERCA, tenant_id: T, un_id: UN1, grupo_id: null, nombre: 'Correctivos Centro 4T', un_codigo: 'SUC-001', un_nombre: 'Sucursal Centro',
    grupo_nombre: null, tipo_actividad: 'correctivo', periodo_inicio: '2026-10-01', periodo_fin: '2026-12-31', monto: '100000.00', moneda: 'MXN',
    umbrales_alerta_json: [50, 80, 100], activo: true, consumido: '85000.00', comprometido: '5000.00', disponible: '10000.00', porcentaje: '85',
    desviacion: '-15000.00', semaforo: 'amarillo', created_at: '2026-10-01T10:00:00Z', updated_at: '2026-10-28T10:00:00Z', ...extra,
  }
}
const excedido = presupuesto({
  id: P_EXCEDIDO, un_id: UN2, nombre: 'Correctivos Polanco 4T', un_codigo: 'SUC-002', un_nombre: 'Sucursal Polanco', monto: '40000.00',
  consumido: '50000.00', comprometido: '0.00', disponible: '-10000.00', porcentaje: '125', desviacion: '10000.00', semaforo: 'rojo',
})

function nivel(nombre: string, p: Presupuesto): NivelConsolidado {
  return { id: p.un_id, nombre, monto: p.monto, consumido: p.consumido, comprometido: p.comprometido, disponible: p.disponible,
           porcentaje: p.porcentaje, desviacion: p.desviacion, semaforo: p.semaforo, presupuestos: [p] }
}
const consolidado: Consolidado = {
  tenant: { id: T, nombre: 'Cliente Demo', monto: '140000.00', consumido: '135000.00', comprometido: '5000.00', disponible: '0.00',
            porcentaje: '96.43', desviacion: '-5000.00', semaforo: 'amarillo', presupuestos: [] },
  grupos: [{ id: 'gr1', nombre: 'Zona Metropolitana', monto: '140000.00', consumido: '126000.00', comprometido: '5000.00', disponible: '9000.00',
             porcentaje: '90', desviacion: '-14000.00', semaforo: 'amarillo', presupuestos: [presupuesto()] }],
  unidades: [nivel('SUC-001 · Sucursal Centro', presupuesto()), nivel('SUC-002 · Sucursal Polanco', excedido)],
  presupuestos: [presupuesto(), excedido],
}

const consumos: ConsumoPresupuesto[] = [
  { id: 'c1', folio_id: '0f000000-0000-0000-0000-000000000001', numero_folio: 'CD-000011', descripcion: null, un_id: UN1, un_codigo: 'SUC-001', monto: '45000.00', fecha: '2026-10-20', tipo: 'correctivo', created_at: '2026-10-20T10:00:00Z' },
  { id: 'c2', folio_id: '0f000000-0000-0000-0000-000000000002', numero_folio: 'CD-000012', descripcion: null, un_id: UN1, un_codigo: 'SUC-001', monto: '40000.00', fecha: '2026-10-25', tipo: 'correctivo', created_at: '2026-10-25T10:00:00Z' },
]

async function entrar(rol: Rol, ruta: string, rutas: Parameters<typeof simularApi>[0] = {}, extra: Partial<PerfilConTema> = {}) {
  localStorage.setItem('acma.sesion', '1')  // P11a: solo la marca; el refresh va en cookie httpOnly
  const llamadas = simularApi({
    'POST /api/auth/refresh': () => ({ json: TOKENS }),
    'GET /api/auth/yo': () => ({ json: perfil(rol, { tenant_id: T, ...extra }) }),
    'GET /api/notificaciones/no-leidas': () => ({ json: { no_leidas: 0 } }),
    'GET /api/presupuestos/consolidado': () => ({ json: consolidado }),
    ...rutas,
  })
  renderApp(ruta)
  return llamadas
}

describe('Presupuestos', () => {
  it('el tablero consolidado muestra el semáforo por nivel y distingue el excedido del que está cerca del límite', async () => {
    await entrar('admin_empresa', '/presupuestos')
    const tablero = await screen.findByTestId('tablero-presupuestos', {}, { timeout: 5000 })
    expect(within(tablero).getByText('96.4% · Cerca del límite')).toBeInTheDocument()
    expect(within(tablero).getByText(/Presupuesto \$140,000\.00 · consumido \$135,000\.00 · comprometido \$5,000\.00 · disponible/)).toBeInTheDocument()
    const grupos = within(tablero).getByTestId('nivel-grupos')
    expect(within(grupos).getByText('Zona Metropolitana')).toBeInTheDocument()
    expect(within(grupos).getByText('90.0% · Cerca del límite')).toBeInTheDocument()
    const unidades = within(tablero).getByTestId('nivel-unidades')
    const centro = within(unidades).getByText('SUC-001 · Sucursal Centro').closest('li')!
    expect(within(centro).getByText('85.0% · Cerca del límite')).toBeInTheDocument()
    const polanco = within(unidades).getByText('SUC-002 · Sucursal Polanco').closest('li')!
    expect(within(polanco).getByText('125.0% · Excedido')).toBeInTheDocument()
    expect(within(polanco).getByText(/disponible \$-10,000\.00 · desviación \$10,000\.00/)).toBeInTheDocument()
  })

  it('el detalle lista los folios cargados y el Admin empresa puede subir el monto', async () => {
    let monto = '100000.00'
    const llamadas = await entrar('admin_empresa', `/presupuestos?presupuesto=${P_CERCA}`, {
      'GET /api/presupuestos': () => ({ json: [presupuesto({ monto }), excedido] }),
      [`GET /api/presupuestos/${P_CERCA}/consumos`]: () => ({ json: consumos }),
      [`PUT /api/presupuestos/${P_CERCA}`]: (cuerpo) => { monto = (cuerpo as { monto: string }).monto; return { json: presupuesto({ monto, porcentaje: '70.83', semaforo: 'verde' }) } },
    })
    const panel = await screen.findByTestId('detalle-presupuesto', {}, { timeout: 5000 })
    expect(within(panel).getByText('SUC-001 · Sucursal Centro · Correctivos · 2026-10-01 a 2026-12-31')).toBeInTheDocument()
    expect(within(panel).getByText('50% · 80% · 100%')).toBeInTheDocument()
    expect(within(panel).getByText('Folios cargados (2)')).toBeInTheDocument()
    const lista = within(panel).getByTestId('consumos-presupuesto')
    expect(within(lista).getByRole('link', { name: 'CD-000011' })).toHaveAttribute('href', '/folios/0f000000-0000-0000-0000-000000000001')
    expect(within(lista).getByText(/\$40,000\.00/)).toBeInTheDocument()
    const user = userEvent.setup()
    await user.clear(within(panel).getByLabelText('Nuevo monto'))
    await user.type(within(panel).getByLabelText('Nuevo monto'), '120000')
    await user.click(within(panel).getByRole('button', { name: 'Guardar monto' }))
    await waitFor(() => expect(llamadas.find((l) => l.clave === `PUT /api/presupuestos/${P_CERCA}`)?.cuerpo).toEqual({ monto: '120000' }))
    expect(await screen.findByText('Presupuesto actualizado')).toBeInTheDocument()
  })

  it('el Admin UN consulta en solo lectura: sin alta ni edición de montos', async () => {
    await entrar('admin_un', `/presupuestos?vista=listado&presupuesto=${P_CERCA}`, {
      'GET /api/presupuestos': () => ({ json: [presupuesto()] }),
      [`GET /api/presupuestos/${P_CERCA}/consumos`]: () => ({ json: [] }),
    })
    const panel = await screen.findByTestId('detalle-presupuesto', {}, { timeout: 5000 })
    expect(screen.getByText('Solo lectura de tus UNs')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Nuevo presupuesto' })).not.toBeInTheDocument()
    expect(within(panel).queryByLabelText('Nuevo monto')).not.toBeInTheDocument()
    expect(within(panel).getByText('Todavía no hay folios con costo validado en este período.')).toBeInTheDocument()
  })
})
