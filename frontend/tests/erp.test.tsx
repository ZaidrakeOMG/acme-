import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { PerfilConTema, Rol } from '../src/types/api'
import type { ErpConfig, EventoERP, Exportacion } from '../src/types/inventario'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const config: ErpConfig = {
  id: 'cf1', prestador_id: 'p1', adaptador: 'ninguno', columnas_excel_json: ['fecha', 'tipo', 'referencia', 'concepto', 'total'],
  cuentas_contables_json: { registrar_gasto: '5101-001' }, centros_costos_json: { registrar_gasto: 'MANTENIMIENTO' }, exportacion_automatica: false,
  adaptadores_disponibles: [{ clave: 'ninguno', nombre: 'Sin adaptador (exportación universal)', fase: 1 }, { clave: 'contpaqi', nombre: 'CONTPAQi', fase: 2 }, { clave: 'microsip', nombre: 'Microsip', fase: 2 }],
  created_at: '2026-10-01T10:00:00Z', updated_at: '2026-10-01T10:00:00Z',
}

function evento(extra: Partial<EventoERP> = {}): EventoERP {
  return {
    id: 'ev1', prestador_id: 'p1', tenant_id: null, operacion: 'registrar_gasto', entidad: 'folio_costo', entidad_id: 'co1',
    payload_json: { numero_folio: 'CD-000071', total: '10200.00', centro_costos: 'MANTENIMIENTO' }, estado: 'pendiente', intentos: 0,
    ultimo_error: null, adaptador: null, respuesta_json: {}, exportacion_id: null, procesado_at: null, created_at: '2026-10-29T12:00:00Z', ...extra,
  }
}

const exportacion: Exportacion = {
  id: 'ex1', prestador_id: 'p1', periodo_inicio: '2026-10-01', periodo_fin: '2026-10-31', eventos_incluidos: 4, total: '28400.00',
  generado_por: 'ap', archivo_disponible: true, xml_disponible: true, created_at: '2026-10-31T10:00:00Z', updated_at: '2026-10-31T10:00:00Z',
}

async function entrar(rol: Rol, ruta: string, rutas: Parameters<typeof simularApi>[0] = {}, extra: Partial<PerfilConTema> = {}) {
  localStorage.setItem('acma.refresh', TOKENS.refresh_token)
  const llamadas = simularApi({
    'POST /api/auth/refresh': () => ({ json: TOKENS }),
    'GET /api/auth/yo': () => ({ json: perfil(rol, { prestador_id: 'p1', ...extra }) }),
    'GET /api/notificaciones/no-leidas': () => ({ json: { no_leidas: 0 } }),
    'GET /api/erp/configuracion': () => ({ json: config }),
    ...rutas,
  })
  renderApp(ruta)
  return llamadas
}

describe('Integración ERP', () => {
  it('la bandeja procesa el evento del gasto con el adaptador configurado', async () => {
    let procesado = false
    const llamadas = await entrar('admin_prestador', '/erp', {
      'GET /api/erp/eventos': () => ({ json: [procesado
        ? evento({ estado: 'procesado', adaptador: 'ninguno', intentos: 1, procesado_at: '2026-10-29T12:05:00Z', respuesta_json: { detalle: 'Incluido en la exportación universal' } })
        : evento()] }),
      'POST /api/erp/eventos/ev1/procesar': () => { procesado = true; return { json: evento({ estado: 'procesado', adaptador: 'ninguno' }) } },
    })
    const tabla = await screen.findByTestId('eventos-erp', {}, { timeout: 5000 })
    expect(await within(tabla).findByText('Registrar gasto en centro de costos')).toBeInTheDocument()
    expect(within(tabla).getByText('CD-000071')).toBeInTheDocument()
    expect(within(tabla).getByText('$10,200.00')).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(within(tabla).getByRole('button', { name: 'Procesar' }))
    await waitFor(() => expect(llamadas.some((l) => l.clave === 'POST /api/erp/eventos/ev1/procesar')).toBe(true))
    expect(await within(tabla).findByText('Procesado')).toBeInTheDocument()
    expect(within(tabla).getByText('Incluido en la exportación universal')).toBeInTheDocument()
    expect(within(tabla).queryByRole('button', { name: 'Procesar' })).not.toBeInTheDocument()
  })

  it('genera la exportación universal del período y ofrece el Excel y el XML', async () => {
    let lista: Exportacion[] = []
    const llamadas = await entrar('admin_prestador', '/erp?vista=exportaciones', {
      'GET /api/erp/exportaciones': () => ({ json: lista }),
      'POST /api/erp/exportaciones': () => { lista = [exportacion]; return { estado: 201, json: exportacion } },
    })
    expect(await screen.findByText('Sin exportaciones generadas', {}, { timeout: 5000 })).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Generar exportación' }))
    await waitFor(() => expect(llamadas.some((l) => l.clave === 'POST /api/erp/exportaciones')).toBe(true))
    expect(await screen.findByText('2026-10-01 a 2026-10-31')).toBeInTheDocument()
    expect(screen.getByText('$28,400.00')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Excel' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'XML' })).toBeInTheDocument()
  })

  it('los adaptadores de Fase 2 se muestran etiquetados y Mesa de control no guarda la configuración', async () => {
    await entrar('mesa_control', '/erp?vista=configuracion')
    const panel = await screen.findByTestId('config-erp', {}, { timeout: 5000 })
    expect(within(panel).getByRole('option', { name: 'CONTPAQi — Fase 2' })).toBeInTheDocument()
    expect(within(panel).getByRole('option', { name: 'Microsip — Fase 2' })).toBeInTheDocument()
    expect(within(panel).getByLabelText('Columnas (separadas por coma)')).toHaveValue('fecha, tipo, referencia, concepto, total')
    expect(within(panel).getByLabelText('Cuentas contables')).toHaveValue('registrar_gasto=5101-001')
    expect(within(panel).queryByRole('button', { name: 'Guardar configuración' })).not.toBeInTheDocument()
  })
})
