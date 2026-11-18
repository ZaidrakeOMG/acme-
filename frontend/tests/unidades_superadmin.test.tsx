import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const CLIENTE = '11111111-1111-1111-1111-111111111111'
const OTRO = '22222222-2222-2222-2222-222222222222'
const clientes = [
  { id: CLIENTE, razon_social: 'EMPRESA DEMO ACMA SA DE CV', rfc: 'TST261117A01' },
  { id: OTRO, razon_social: 'OTRO CLIENTE DEMO SA DE CV', rfc: 'TST261117B01' },
]

function entrar() {
  localStorage.setItem('acma.sesion', '1')
  const llamadas = simularApi({
    'POST /api/auth/refresh': () => ({ json: TOKENS }),
    'GET /api/auth/yo': () => ({ json: perfil('superadmin') }),
    'GET /api/unidades-negocio': () => ({ json: [] }),
    'GET /api/grupos-un': () => ({ json: [
      { id: '33333333-3333-3333-3333-333333333333', tenant_id: CLIENTE, nombre: 'Grupo Cliente Demo', unidad_ids: [], supervisor_ids: [] },
      { id: '44444444-4444-4444-4444-444444444444', tenant_id: OTRO, nombre: 'Grupo Otro Cliente', unidad_ids: [], supervisor_ids: [] },
    ] }),
    'GET /api/tenants': () => ({ json: clientes }),
    'POST /api/unidades-negocio': () => ({ estado: 201, json: { id: '55555555-5555-5555-5555-555555555555', tenant_id: CLIENTE } }),
    'POST /api/grupos-un': () => ({ estado: 201, json: { id: '66666666-6666-6666-6666-666666666666', tenant_id: CLIENTE } }),
  })
  renderApp('/unidades')
  return llamadas
}

describe('Unidades de negocio del superadministrador', () => {
  it('exige cliente antes de registrar la unidad y envía el tenant seleccionado', async () => {
    const llamadas = entrar()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Nueva unidad' }))
    await user.type(screen.getByLabelText('Código'), 'SUC-DEMO-01')
    await user.type(screen.getByLabelText('Nombre'), 'Sucursal Centro DEMO')
    await user.click(screen.getByRole('button', { name: 'Guardar' }))
    expect(await screen.findByText('Selecciona el cliente al que pertenece la unidad')).toBeInTheDocument()
    expect(llamadas.filter(l => l.clave === 'POST /api/unidades-negocio')).toHaveLength(0)

    await user.selectOptions(screen.getByLabelText('Cliente'), CLIENTE)
    expect(screen.getByRole('option', { name: 'Grupo Cliente Demo' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Grupo Otro Cliente' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(llamadas.filter(l => l.clave === 'POST /api/unidades-negocio')).toHaveLength(1))
    expect(llamadas.find(l => l.clave === 'POST /api/unidades-negocio')?.cuerpo)
      .toMatchObject({ tenant_id: CLIENTE, codigo: 'SUC-DEMO-01', nombre: 'Sucursal Centro DEMO' })
  })

  it('exige cliente al crear grupos y lo envía en la solicitud', async () => {
    const llamadas = entrar()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Nuevo grupo' }))
    await user.type(screen.getByLabelText('Nombre'), 'Sucursales DEMO')
    await user.click(screen.getByRole('button', { name: 'Crear grupo' }))
    expect(await screen.findByText('Selecciona el cliente del grupo')).toBeInTheDocument()
    expect(llamadas.filter(l => l.clave === 'POST /api/grupos-un')).toHaveLength(0)

    await user.selectOptions(screen.getByLabelText('Cliente'), CLIENTE)
    await user.click(screen.getByRole('button', { name: 'Crear grupo' }))
    await waitFor(() => expect(llamadas.filter(l => l.clave === 'POST /api/grupos-un')).toHaveLength(1))
    expect(llamadas.find(l => l.clave === 'POST /api/grupos-un')?.cuerpo)
      .toMatchObject({ tenant_id: CLIENTE, nombre: 'Sucursales DEMO' })
  })
})
