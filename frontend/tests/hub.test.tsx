import { screen } from '@testing-library/react'
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
  it('superadmin ve los 27 módulos de Fase 1 y todos son enlaces construidos', async () => {
    await entrarComo('superadmin')
    await screen.findByRole('heading', { name: /Hola/ })
    for (const m of MODULOS) expect(screen.getByTestId(`modulo-${m.id}`)).toBeInTheDocument()
    // P10 cierra el desarrollo funcional de Fase 1: ya no quedan módulos pendientes de construir.
    for (const m of MODULOS) {
      const tarjeta = screen.getByTestId(`modulo-${m.id}`)
      expect(tarjeta.tagName).toBe('A')
      expect(tarjeta).toHaveAttribute('href', m.ruta!)
    }
    expect(screen.queryByText(/Disponible en el prompt/)).not.toBeInTheDocument()
    expect(screen.getByTestId('modulo-bi')).toHaveAttribute('href', '/bi')
    expect(screen.getByTestId('modulo-sla')).toHaveAttribute('href', '/contratos?vista=cumplimiento')
    expect(screen.getByTestId('modulo-inventario')).toHaveAttribute('href', '/inventario')
    expect(screen.getByTestId('modulo-presupuestos')).toHaveAttribute('href', '/presupuestos')
    expect(screen.getByTestId('modulo-activos')).toHaveAttribute('href', '/activos')
    expect(screen.getByTestId('modulo-trabajos_especiales')).toHaveAttribute('href', '/trabajos-especiales')
    expect(screen.getByTestId('modulo-oc_activos')).toHaveAttribute('href', '/oc-activos')
    expect(screen.getByTestId('modulo-minuta')).toHaveAttribute('href', '/minutas')
    expect(screen.getByTestId('modulo-preventivos')).toHaveAttribute('href', '/preventivos/calendario')
    expect(screen.getByTestId('modulo-folios')).toHaveAttribute('href', '/folios')
    expect(screen.getByTestId('modulo-app_campo')).toHaveAttribute('href', '/campo')
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

  it('técnico: ve sus módulos construidos como enlaces y no los de otros roles', async () => {
    await entrarComo('tecnico')
    const tarjeta = await screen.findByTestId('modulo-inventario')
    expect(tarjeta.tagName).toBe('A')
    expect(tarjeta).toHaveAttribute('href', '/inventario')
    expect(screen.getByTestId('modulo-app_campo')).toHaveAttribute('href', '/campo')
    expect(screen.getByTestId('modulo-caja_chica')).toHaveAttribute('href', '/caja-chica')
    expect(screen.queryByTestId('modulo-usuarios')).not.toBeInTheDocument()
    expect(screen.queryByTestId('modulo-presupuestos')).not.toBeInTheDocument()
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
