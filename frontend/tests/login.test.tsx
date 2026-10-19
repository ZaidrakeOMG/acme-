import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

describe('Login', () => {
  it('valida el formulario antes de llamar a la API', async () => {
    const llamadas = simularApi({})
    renderApp()
    await userEvent.click(await screen.findByRole('button', { name: 'Entrar' }))
    expect(await screen.findByText('Ingresa un correo válido')).toBeInTheDocument()
    expect(screen.getByText('Ingresa tu contraseña')).toBeInTheDocument()
    expect(llamadas.filter((l) => l.clave === 'POST /api/auth/login')).toHaveLength(0)
  })

  it('muestra el mensaje del error estándar de la API', async () => {
    simularApi({
      'POST /api/auth/login': () => ({ estado: 401, json: { codigo: 'CREDENCIALES_INVALIDAS', mensaje: 'Correo o contraseña incorrectos', detalles: [] } }),
    })
    renderApp()
    await userEvent.type(await screen.findByLabelText('Correo electrónico'), 'operador@acma.dev')
    await userEvent.type(screen.getByLabelText('Contraseña'), 'mala')
    await userEvent.click(screen.getByRole('button', { name: 'Entrar' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Correo o contraseña incorrectos')
  })

  it('entra directo cuando el rol no requiere MFA', async () => {
    simularApi({
      'POST /api/auth/login': () => ({ json: { mfa_requerido: false, mfa_enrolamiento_requerido: false, token_mfa: null, tokens: TOKENS, usuario: null } }),
      'GET /api/auth/yo': () => ({ json: perfil('operador', { nombre: 'Olga Operadora' }) }),
    })
    renderApp()
    await userEvent.type(await screen.findByLabelText('Correo electrónico'), 'operador@acma.dev')
    await userEvent.type(screen.getByLabelText('Contraseña'), 'Demo#Acma2026')
    await userEvent.click(screen.getByRole('button', { name: 'Entrar' }))
    expect(await screen.findByRole('heading', { name: 'Hola, Olga' })).toBeInTheDocument()
    expect(localStorage.getItem('acma.refresh')).toBe(TOKENS.refresh_token)
  })

  it('pide el código en el segundo paso y acepta un código de recuperación', async () => {
    const llamadas = simularApi({
      'POST /api/auth/login': () => ({ json: { mfa_requerido: true, mfa_enrolamiento_requerido: false, token_mfa: 'tmp', tokens: null, usuario: null } }),
      'POST /api/auth/mfa/verify': () => ({ json: { tokens: TOKENS, usuario: null, codigos_recuperacion: null } }),
      'GET /api/auth/yo': () => ({ json: perfil('admin_empresa', { nombre: 'Elena Empresa', mfa_habilitado: true, mfa_obligatorio: true }) }),
    })
    renderApp()
    await userEvent.type(await screen.findByLabelText('Correo electrónico'), 'admin.empresa@acma.dev')
    await userEvent.type(screen.getByLabelText('Contraseña'), 'Demo#Acma2026')
    await userEvent.click(screen.getByRole('button', { name: 'Entrar' }))
    expect(await screen.findByRole('heading', { name: 'Verificación en dos pasos' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Usar un código de recuperación' }))
    await userEvent.type(screen.getByLabelText('Código de recuperación'), 'abcd1234-ef567890')
    await userEvent.click(screen.getByRole('button', { name: 'Verificar' }))
    expect(await screen.findByRole('heading', { name: 'Hola, Elena' })).toBeInTheDocument()
    expect(llamadas.find((l) => l.clave === 'POST /api/auth/mfa/verify')?.cuerpo).toEqual({ token_mfa: 'tmp', codigo: 'abcd1234-ef567890' })
  })

  it('renueva el token una sola vez aunque varias peticiones reciban 401', async () => {
    const { api, sesion } = await import('../src/services/api')
    let refrescos = 0
    let tokenVigente = false
    simularApi({
      'POST /api/auth/refresh': () => {
        refrescos += 1
        tokenVigente = true
        return { json: { ...TOKENS, access_token: 'nuevo' } }
      },
      'GET /api/salud': () => (tokenVigente ? { json: { estado: 'ok' } } : { estado: 401, json: { codigo: 'NO_AUTENTICADO', mensaje: 'x', detalles: [] } }),
    })
    sesion.guardar({ ...TOKENS, access_token: 'viejo' })
    const resultados = await Promise.all([api('/salud'), api('/salud'), api('/salud')])
    expect(resultados).toHaveLength(3)
    expect(refrescos).toBe(1)
  })
})
