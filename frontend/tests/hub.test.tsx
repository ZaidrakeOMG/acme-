import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MODULOS, modulosDe } from '../src/config/modulos'
import type { PerfilConTema, Rol } from '../src/types/api'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

async function entrarComo(rol: Rol, extra: Partial<PerfilConTema> = {}, ruta = '/') {
  localStorage.setItem('acma.refresh', TOKENS.refresh_token)
  simularApi({
    'POST /api/auth/refresh': () => ({ json: TOKENS }),
    'GET /api/auth/yo': () => ({ json: perfil(rol, extra) }),
  })
  renderApp(ruta)
}

describe('RoleHub', () => {
  it('superadmin ve todos los módulos y los pendientes indican su prompt', async () => {
    await entrarComo('superadmin')
    await screen.findByRole('heading', { name: /Hola/ })
    for (const m of MODULOS) expect(screen.getByTestId(`modulo-${m.id}`)).toBeInTheDocument()
    expect(within(screen.getByTestId('modulo-app_campo')).getByText('Disponible en el prompt P05')).toBeInTheDocument()
    expect(screen.getByTestId('modulo-folios')).toHaveAttribute('href', '/folios')
    expect(screen.getByTestId('modulo-usuarios')).toHaveAttribute('href', '/usuarios')
  })

  it.each<Rol>(['operador', 'tecnico', 'admin_un', 'supervisor_operadores', 'despachador', 'direccion_prestador'])(
    '%s ve exactamente los módulos de su rol',
    async (rol) => {
      await entrarComo(rol)
      await screen.findByRole('heading', { name: /Hola/ })
      const propios = new Set(modulosDe(rol).map((m) => m.id))
      for (const m of MODULOS) {
        if (propios.has(m.id)) expect(screen.getByTestId(`modulo-${m.id}`)).toBeInTheDocument()
        else expect(screen.queryByTestId(`modulo-${m.id}`)).not.toBeInTheDocument()
      }
      expect(screen.queryByTestId('modulo-auditoria')).not.toBeInTheDocument()
    },
  )

  it('operador: sus módulos futuros no son enlaces y muestran el prompt', async () => {
    await entrarComo('operador')
    const tarjeta = await screen.findByTestId('modulo-app_campo')
    expect(tarjeta.tagName).toBe('ARTICLE')
    expect(within(tarjeta).getByText('Disponible en el prompt P05')).toBeInTheDocument()
    expect(screen.queryByTestId('modulo-usuarios')).not.toBeInTheDocument()
  })

  it('admin empresa ve administración de su tenant pero no prestadores ni auditoría', async () => {
    await entrarComo('admin_empresa')
    await screen.findByRole('heading', { name: /Hola/ })
    for (const id of ['usuarios', 'unidades', 'contratos', 'alertas']) expect(screen.getByTestId(`modulo-${id}`)).toBeInTheDocument()
    for (const id of ['prestadores', 'tenants', 'auditoria', 'formularios']) expect(screen.queryByTestId(`modulo-${id}`)).not.toBeInTheDocument()
  })

  it('cabecera con nombre y rol, y aviso si falta MFA obligatorio', async () => {
    await entrarComo('admin_prestador', { nombre: 'Arturo Prestador', mfa_obligatorio: true, mfa_habilitado: false })
    await screen.findByRole('heading', { name: 'Hola, Arturo' })
    expect(screen.getByText('Arturo Prestador')).toBeInTheDocument()
    expect(screen.getAllByText('Admin prestador').length).toBeGreaterThan(0)
    expect(screen.getByText(/Tu rol requiere verificación en dos pasos/)).toBeInTheDocument()
  })

  it('aplica el color primario del prestador', async () => {
    await entrarComo('despachador', { tema: { color_primario: '#123456', color_acento: '#ABCDEF', prestador: 'Otro' } })
    await screen.findByRole('heading', { name: /Hola/ })
    expect(document.documentElement.style.getPropertyValue('--color-primario')).toBe('#123456')
  })

  it('una ruta sin permiso muestra aviso en lugar de la pantalla', async () => {
    await entrarComo('tecnico', {}, '/auditoria')
    expect(await screen.findByText('Tu rol no tiene acceso a este módulo.')).toBeInTheDocument()
  })
})
