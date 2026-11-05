import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

/** §6.9.5 · P11a: olvidé mi contraseña, el enlace del correo y el cambio obligatorio al vencer los 90 días. */
describe('Contraseña', () => {
  it('pide el enlace de restablecimiento sin revelar si la cuenta existe', async () => {
    const llamadas = simularApi({ 'POST /api/auth/restablecer/solicitar': () => ({ json: { mensaje: 'ok' } }) })
    renderApp()
    await userEvent.click(await screen.findByRole('button', { name: '¿Olvidaste tu contraseña?' }))
    await userEvent.type(await screen.findByLabelText('Correo electrónico'), 'admin.empresa@acma.dev')
    await userEvent.click(screen.getByRole('button', { name: 'Enviarme el enlace' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Si el correo corresponde a una cuenta activa')
    const envio = llamadas.find((l) => l.clave === 'POST /api/auth/restablecer/solicitar')
    expect(envio?.cuerpo).toEqual({ email: 'admin.empresa@acma.dev' })
    await userEvent.click(screen.getByRole('button', { name: 'Volver a iniciar sesión' }))
    expect(await screen.findByRole('heading', { name: 'Iniciar sesión' })).toBeInTheDocument()
  })

  it('el enlace del correo fija la contraseña nueva con el token de un solo uso', async () => {
    const llamadas = simularApi({ 'POST /api/auth/restablecer/confirmar': () => ({ json: { mensaje: 'ok' } }) })
    renderApp('/restablecer?token=' + 'token-de-correo-de-un-solo-uso')
    await userEvent.type(await screen.findByLabelText('Contraseña nueva'), 'Nueva#Clave2026x')
    await userEvent.type(screen.getByLabelText('Repite la contraseña'), 'Nueva#Clave2026x')
    await userEvent.click(screen.getByRole('button', { name: 'Restablecer contraseña' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Ya puedes entrar con tu contraseña nueva')
    expect(llamadas.find((l) => l.clave === 'POST /api/auth/restablecer/confirmar')?.cuerpo).toEqual({
      token: 'token-de-correo-de-un-solo-uso',
      nueva: 'Nueva#Clave2026x',
    })
  })

  it('no acepta dos contraseñas distintas ni un enlace sin token', async () => {
    const llamadas = simularApi({})
    renderApp('/restablecer?token=token-de-correo-de-un-solo-uso')
    await userEvent.type(await screen.findByLabelText('Contraseña nueva'), 'Nueva#Clave2026x')
    await userEvent.type(screen.getByLabelText('Repite la contraseña'), 'Otra#Clave2026xy')
    await userEvent.click(screen.getByRole('button', { name: 'Restablecer contraseña' }))
    expect(await screen.findByText('Las dos contraseñas no coinciden')).toBeInTheDocument()
    expect(llamadas.filter((l) => l.clave === 'POST /api/auth/restablecer/confirmar')).toHaveLength(0)

    renderApp('/restablecer')
    expect(await screen.findByRole('heading', { name: 'Enlace incompleto' })).toBeInTheDocument()
  })

  it('con la contraseña vencida solo se puede cambiarla, y al cambiarla se abre la app', async () => {
    localStorage.setItem('acma.sesion', '1')
    let vencida = true
    const llamadas = simularApi({
      'POST /api/auth/refresh': () => ({ json: TOKENS }),
      'GET /api/auth/yo': () => ({ json: perfil('admin_empresa', { nombre: 'Elena Empresa', contrasena_vencida: vencida }) }),
      'POST /api/auth/cambiar-contrasena': () => {
        vencida = false
        return { json: { mensaje: 'Contraseña actualizada' } }
      },
    })
    renderApp('/folios')  // cualquier ruta cae en la pantalla de cambio mientras la contraseña esté vencida
    expect(await screen.findByRole('heading', { name: 'Tu contraseña venció' })).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Contraseña actual'), 'Demo#Acma2026')
    await userEvent.type(screen.getByLabelText('Contraseña nueva'), 'Nueva#Clave2026x')
    await userEvent.type(screen.getByLabelText('Repite la contraseña nueva'), 'Nueva#Clave2026x')
    await userEvent.click(screen.getByRole('button', { name: 'Cambiar y continuar' }))

    // La puerta se levanta: el perfil se vuelve a pedir y la ruta pedida (/folios) ya se renderiza.
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Tu contraseña venció' })).toBeNull())
    expect(llamadas.find((l) => l.clave === 'POST /api/auth/cambiar-contrasena')?.cuerpo).toEqual({
      actual: 'Demo#Acma2026',
      nueva: 'Nueva#Clave2026x',
    })
    expect(llamadas.filter((l) => l.clave === 'GET /api/auth/yo').length).toBeGreaterThanOrEqual(2)
  })

  it('rechaza una contraseña nueva igual a la actual antes de llamar al servidor', async () => {
    localStorage.setItem('acma.sesion', '1')
    const llamadas = simularApi({
      'POST /api/auth/refresh': () => ({ json: TOKENS }),
      'GET /api/auth/yo': () => ({ json: perfil('admin_prestador', { contrasena_vencida: true }) }),
    })
    renderApp()
    await userEvent.type(await screen.findByLabelText('Contraseña actual'), 'Demo#Acma2026')
    await userEvent.type(screen.getByLabelText('Contraseña nueva'), 'Demo#Acma2026')
    await userEvent.type(screen.getByLabelText('Repite la contraseña nueva'), 'Demo#Acma2026')
    await userEvent.click(screen.getByRole('button', { name: 'Cambiar y continuar' }))
    expect(await screen.findByText('La contraseña nueva debe ser distinta de la actual')).toBeInTheDocument()
    expect(llamadas.filter((l) => l.clave === 'POST /api/auth/cambiar-contrasena')).toHaveLength(0)
  })
})
