import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const T = '11111111-1111-1111-1111-111111111111'
const P = '22222222-2222-2222-2222-222222222222'

function entrar() {
  localStorage.setItem('acma.sesion', '1')
  const llamadas = simularApi({
    'POST /api/auth/refresh': () => ({ json: TOKENS }),
    'GET /api/auth/yo': () => ({ json: perfil('superadmin') }),
    'GET /api/notificaciones/no-leidas': () => ({ json: { no_leidas: 0 } }),
    'GET /api/contratos': () => ({ json: [] }),
    'GET /api/tenants': () => ({ json: [{
      id: T, razon_social: 'EMPRESA DEMO ACMA SA DE CV', estado: 'activo',
      pais: 'MX', moneda: 'MXN', zona_horaria: 'America/Mexico_City',
    }] }),
    'GET /api/prestadores': () => ({ json: [{
      id: P, razon_social: 'MANTENIMIENTO DEMO ACMA SA DE CV', estado: 'activo', pais: 'MX',
    }] }),
    'POST /api/contratos': () => ({ estado: 201, json: { id: '33333333-3333-3333-3333-333333333333' } }),
  })
  renderApp('/contratos')
  return llamadas
}

describe('Contratos — alta de superadmin', () => {
  it('requiere prestador y envía tenant_id y prestador_id con los 5 SLA', async () => {
    const llamadas = entrar()
    const usuario = userEvent.setup()
    await screen.findByRole('heading', { name: 'Contratos y SLAs' })
    await waitFor(() => expect(llamadas.some(l => l.clave === 'GET /api/prestadores')).toBe(true))
    await usuario.click(screen.getByRole('button', { name: 'Nuevo contrato' }))
    const form = screen.getByTestId('form-contrato')
    await usuario.selectOptions(within(form).getByLabelText('Cliente'), T)
    fireEvent.change(within(form).getByLabelText('Nombre del contrato'), { target: { value: 'Contrato Demo 2026-27' } })
    fireEvent.change(within(form).getByLabelText('Inicio'), { target: { value: '2026-11-18' } })
    fireEvent.change(within(form).getByLabelText('Fin'), { target: { value: '2027-11-17' } })
    await usuario.click(within(form).getByRole('button', { name: 'Guardar contrato' }))
    expect(await screen.findByText('Selecciona el prestador que atenderá el contrato')).toBeInTheDocument()
    expect(llamadas.some(l => l.clave === 'POST /api/contratos')).toBe(false)
    await usuario.selectOptions(within(form).getByLabelText('Prestador'), P)
    await usuario.click(within(form).getByRole('button', { name: 'Guardar contrato' }))
    await waitFor(() => expect(llamadas.filter(l => l.clave === 'POST /api/contratos')).toHaveLength(1))
    const cuerpo = llamadas.find(l => l.clave === 'POST /api/contratos')?.cuerpo as {
      tenant_id: string; prestador_id: string; vincular_prestador: boolean; nombre: string; slas: unknown[]
    }
    expect(cuerpo.tenant_id).toBe(T)
    expect(cuerpo.prestador_id).toBe(P)
    expect(cuerpo.vincular_prestador).toBe(true)
    expect(cuerpo.nombre).toBe('Contrato Demo 2026-27')
    expect(cuerpo.slas).toHaveLength(5)
  })
})
