import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const CODIGOS = Array.from({ length: 10 }, (_, i) => `codigo${i}-recuperacion`)

async function iniciarLogin(email: string) {
  await userEvent.type(await screen.findByLabelText('Correo electrónico'), email)
  await userEvent.type(screen.getByLabelText('Contraseña'), 'Demo#Acma2026')
  await userEvent.click(screen.getByRole('button', { name: 'Entrar' }))
}

describe('Enrolamiento MFA', () => {
  it('muestra QR, activa con el primer código y obliga a confirmar los códigos de recuperación', async () => {
    const llamadas = simularApi({
      'POST /api/auth/login': () => ({ json: { mfa_requerido: true, mfa_enrolamiento_requerido: true, token_mfa: 'tmp-enrolar', tokens: null, usuario: null } }),
      'POST /api/auth/mfa/setup': () => ({ json: { secreto: 'JBSWY3DPEHPK3PXP', uri: 'otpauth://totp/ACMA:x', qr_svg: 'data:image/svg+xml;base64,PHN2Zy8+' } }),
      'POST /api/auth/mfa/verify': () => ({ json: { tokens: TOKENS, usuario: null, codigos_recuperacion: CODIGOS } }),
      'GET /api/auth/yo': () => ({ json: perfil('superadmin', { nombre: 'Sofía Plataforma', mfa_habilitado: true, mfa_obligatorio: true }) }),
    })
    renderApp()
    await iniciarLogin('superadmin@acma.dev')

    expect(await screen.findByRole('heading', { name: 'Activa la verificación en dos pasos' })).toBeInTheDocument()
    expect(screen.getByAltText('Código QR para la app autenticadora')).toHaveAttribute('src', expect.stringContaining('data:image/svg+xml'))
    expect(screen.getByText('JBSWY3DPEHPK3PXP')).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Código de verificación'), '123456')
    await userEvent.click(screen.getByRole('button', { name: 'Activar y entrar' }))

    const lista = await screen.findByRole('list', { name: 'Códigos de recuperación' })
    expect(lista.querySelectorAll('li')).toHaveLength(10)
    const continuar = screen.getByRole('button', { name: 'Continuar' })
    expect(continuar).toBeDisabled()
    await userEvent.click(screen.getByLabelText('Ya guardé mis códigos en un lugar seguro'))
    await userEvent.click(continuar)
    expect(await screen.findByRole('heading', { name: 'Hola, Sofía' })).toBeInTheDocument()
    expect(llamadas.find((l) => l.clave === 'POST /api/auth/mfa/setup')?.cuerpo).toEqual({ token_mfa: 'tmp-enrolar' })
  })

  it('rechaza un código inválido y deja reintentar', async () => {
    simularApi({
      'POST /api/auth/login': () => ({ json: { mfa_requerido: true, mfa_enrolamiento_requerido: true, token_mfa: 't', tokens: null, usuario: null } }),
      'POST /api/auth/mfa/setup': () => ({ json: { secreto: 'S', uri: 'u', qr_svg: 'data:image/svg+xml;base64,' } }),
      'POST /api/auth/mfa/verify': () => ({ estado: 401, json: { codigo: 'CODIGO_MFA_INVALIDO', mensaje: 'Código de verificación incorrecto', detalles: [] } }),
    })
    renderApp()
    await iniciarLogin('admin.prestador@acma.dev')
    await userEvent.type(await screen.findByLabelText('Código de verificación'), '000000')
    await userEvent.click(screen.getByRole('button', { name: 'Activar y entrar' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Código de verificación incorrecto')
    expect(screen.getByRole('button', { name: 'Activar y entrar' })).toBeEnabled()
  })
})
