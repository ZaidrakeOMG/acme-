import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const P = 'aaaaaaaa-0000-0000-0000-000000000001'
const prestador = {
  id: P, razon_social: 'MANTENIMIENTO DEMO ACMA SA DE CV',
  rfc: 'TST261117B02', pais: 'MX', color_primario: '#1C3D8F', color_acento: '#A2C62B',
  estado: 'activo', logo_key: null, datos_fiscales: null, version_hash: null,
  created_at: '', updated_at: '',
}

describe('Prestadores', () => {
  it('no duplica el prestador si falla la subida del logotipo y se reintenta', async () => {
    localStorage.setItem('acma.sesion', '1')
    let subidas = 0
    const llamadas = simularApi({
      'POST /api/auth/refresh': () => ({ json: TOKENS }),
      'GET /api/auth/yo': () => ({ json: perfil('superadmin') }),
      'GET /api/prestadores': () => ({ json: [] }),
      'POST /api/prestadores': () => ({ estado: 201, json: prestador }),
      [`PATCH /api/prestadores/${P}`]: () => ({ json: prestador }),
      [`POST /api/prestadores/${P}/logo`]: () => {
        subidas += 1
        return subidas === 1
          ? { estado: 413, json: { codigo: 'ARCHIVO_DEMASIADO_GRANDE', mensaje: 'El logo no puede exceder 1 MB', detalles: [] } }
          : { json: { ...prestador, logo_key: 'prestadores/logo.png' } }
      },
    })

    renderApp('/prestadores')
    await screen.findByRole('heading', { name: 'Prestadores' })
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Nuevo prestador' }))
    await user.type(screen.getByLabelText('Razón social'), prestador.razon_social)
    await user.type(screen.getByLabelText('RFC'), prestador.rfc)
    await user.upload(screen.getByLabelText(/Logo \(PNG/), new File(['logo'], 'logo.png', { type: 'image/png' }))
    await user.click(screen.getByRole('button', { name: 'Guardar' }))

    expect(await screen.findByText(/El prestador ya quedó registrado, pero no se completó el proceso/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(subidas).toBe(2))
    expect(llamadas.filter(l => l.clave === 'POST /api/prestadores')).toHaveLength(1)
    expect(llamadas.filter(l => l.clave === `PATCH /api/prestadores/${P}`)).toHaveLength(1)
  })
})
