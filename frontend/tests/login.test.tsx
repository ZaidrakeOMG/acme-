import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
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
    // P11a: el refresh no se guarda aqui (cookie httpOnly); en localStorage solo queda la marca de sesion.
    expect(localStorage.getItem('acma.sesion')).toBe('1')
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

  it('restaura la sesión al reabrir la web o PWA sin mostrar login', async () => {
    const { sesion } = await import('../src/services/api')
    sesion.guardar(TOKENS) // Simula la marca no secreta que quedó tras cerrar Safari/Chrome.
    document.cookie = 'acma_csrf=csrf-de-prueba; path=/'
    const llamadas = simularApi({
      'POST /api/auth/refresh': () => ({ json: { ...TOKENS, access_token: 'renovado' } }),
      'GET /api/auth/yo': () => ({ json: perfil('tecnico', { nombre: 'Tomás Técnico' }) }),
    })

    renderApp()

    expect(await screen.findByRole('heading', { name: 'Hola, Tomás' })).toBeInTheDocument()
    expect(llamadas.filter((l) => l.clave === 'POST /api/auth/refresh')).toHaveLength(1)
    expect(localStorage.getItem('acma.sesion')).toBe('1')
  })

  it('no elimina la sesión cuando falta Internet y la reanuda al volver la red', async () => {
    const { sesion } = await import('../src/services/api')
    sesion.guardar(TOKENS)
    let sinRed = true
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (entrada) => {
      if (sinRed) throw new TypeError('Failed to fetch')
      const ruta = new URL(String(entrada), 'http://localhost').pathname
      const json = ruta === '/api/auth/refresh'
        ? { ...TOKENS, access_token: 'renovado' }
        : perfil('operador', { nombre: 'Olga Operadora' })
      return new Response(JSON.stringify(json), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      })
    })

    renderApp()
    expect(await screen.findByRole('heading', { name: 'Recuperando tu sesión' })).toBeInTheDocument()
    expect(localStorage.getItem('acma.sesion')).toBe('1')
    sinRed = false
    window.dispatchEvent(new Event('online'))
    expect(await screen.findByRole('heading', { name: 'Hola, Olga' })).toBeInTheDocument()
    expect(localStorage.getItem('acma.sesion')).toBe('1')
  })


  it('no vuelve a entrar después de cerrar sesión sin red aunque siga la cookie segura', async () => {
    const { sesion } = await import('../src/services/api')
    sesion.guardar(TOKENS)
    document.cookie = 'acma_csrf=csrf-de-prueba; path=/'
    // El servidor no pudo borrar el refresh httpOnly porque se perdió Internet.
    sesion.limpiar()
    const llamadas = simularApi({
      'POST /api/auth/refresh': () => ({ json: TOKENS }),
    })
    renderApp()

    expect(await screen.findByRole('button', { name: 'Entrar' })).toBeInTheDocument()
    expect(sesion.tieneRefresh()).toBe(false)
    expect(localStorage.getItem('acma.sesion')).toBe('0')
    expect(llamadas.filter((l) => l.clave === 'POST /api/auth/refresh')).toHaveLength(0)
  })

  it('renueva sin recargar formularios cuando iPhone o Android regresa a primer plano', async () => {
    const { sesion } = await import('../src/services/api')
    sesion.guardar(TOKENS)
    let renovaciones = 0
    const llamadas = simularApi({
      'POST /api/auth/refresh': () => {
        renovaciones += 1
        return { json: { ...TOKENS, access_token: `renovado-${renovaciones}` } }
      },
      'GET /api/auth/yo': () => ({ json: perfil('operador', { nombre: 'Olga Operadora' }) }),
    })
    renderApp()
    expect(await screen.findByRole('heading', { name: 'Hola, Olga' })).toBeInTheDocument()
    expect(renovaciones).toBe(1)

    // Simula 15 minutos transcurridos con la WebView suspendida.
    sesion.guardar({ ...TOKENS, access_token: 'caducado', expira_en: 1 })
    window.dispatchEvent(new Event('acma:resume'))

    await vi.waitFor(() => expect(renovaciones).toBe(2))
    expect(screen.getByRole('heading', { name: 'Hola, Olga' })).toBeInTheDocument()
    expect(llamadas.filter((l) => l.clave === 'GET /api/auth/yo')).toHaveLength(1)
  })

  it('cierra la sesión visible cuando otra pestaña cierra el acceso', async () => {
    const { sesion } = await import('../src/services/api')
    sesion.guardar(TOKENS)
    simularApi({
      'POST /api/auth/refresh': () => ({ json: TOKENS }),
      'GET /api/auth/yo': () => ({ json: perfil('operador', { nombre: 'Olga Operadora' }) }),
    })
    renderApp()
    expect(await screen.findByRole('heading', { name: 'Hola, Olga' })).toBeInTheDocument()
    localStorage.setItem('acma.sesion', '0')
    window.dispatchEvent(new StorageEvent('storage', { key: 'acma.sesion', newValue: '0' }))
    expect(await screen.findByRole('button', { name: 'Entrar' })).toBeInTheDocument()
    expect(sesion.tieneRefresh()).toBe(false)
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
