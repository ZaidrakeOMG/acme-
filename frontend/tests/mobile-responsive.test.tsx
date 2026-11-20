import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AppShell } from '../src/components/AppShell'
import { Tabla } from '../src/components/ui'

vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: () => ({
    usuario: {
      nombre: 'Usuario Prueba',
      rol: 'superadmin',
      tema: { prestador: 'Plataforma ACMA' },
    },
    cerrarSesion: vi.fn(),
  }),
}))
vi.mock('../src/components/CampanaNotificaciones', () => ({
  CampanaNotificaciones: () => <span data-testid="campana">Avisos</span>,
}))
vi.mock('../src/components/IndicadorConectividad', () => ({
  IndicadorConectividad: () => <span>En línea</span>,
}))

const matchMediaMovil = vi.fn().mockImplementation((query: string) => ({
  matches: query.includes('1023px') || query.includes('767px'),
  media: query,
  onchange: null,
  addListener: vi.fn(),
  removeListener: vi.fn(),
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
  dispatchEvent: vi.fn(),
}))

beforeEach(() => {
  Object.defineProperty(window, 'matchMedia', { value: matchMediaMovil, writable: true, configurable: true })
})

describe('ACMA en pantallas pequeñas', () => {
  it('muestra barra inferior, abre menú sobrepuesto y conserva módulos originales', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<div>Bienvenido ACMA</div>} />
            <Route path="folios" element={<div>Listado de folios</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
    expect(screen.getByText('Bienvenido ACMA')).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Accesos rápidos' })).toBeInTheDocument()
    const abrir = screen.getByRole('button', { name: 'Abrir menú' })
    expect(abrir).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(abrir)
    expect(abrir).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('navigation', { name: 'Módulos de ACMA' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('link', { name: 'Folios' }))
    expect(screen.getByText('Listado de folios')).toBeInTheDocument()
    expect(abrir).toHaveAttribute('aria-expanded', 'false')
  })

  it('en WebView móvil ignora la preferencia compacta de PC y siempre abre un menú táctil completo', () => {
    localStorage.setItem('acma.menu.fijado.v1', 'false')
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<div>Inicio móvil</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
    expect(screen.queryByRole('navigation', { name: 'Menú contraído' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Abrir menú' }))
    expect(screen.getByRole('navigation', { name: 'Módulos de ACMA' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Folios' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cerrar menú' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Cerrar menú' }))
    expect(screen.queryByRole('navigation', { name: 'Módulos de ACMA' })).not.toBeInTheDocument()
    expect(localStorage.getItem('acma.menu.fijado.v1')).toBe('false')
  })

  it('permite buscar módulos y abrir o cerrar secciones desde el menú móvil', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<div>Inicio ACMA</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Abrir menú' }))
    const buscador = screen.getByPlaceholderText('Buscar módulo')
    expect(screen.getByRole('link', { name: 'Folios' })).toBeInTheDocument()
    fireEvent.change(buscador, { target: { value: 'inventario' } })
    expect(screen.getByRole('link', { name: 'Inventario' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Folios' })).not.toBeInTheDocument()
    fireEvent.change(buscador, { target: { value: '' } })
    const administracion = screen.getByRole('button', { name: /Administración/ })
    expect(administracion).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(administracion)
    expect(administracion).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('link', { name: 'Usuarios' })).toBeInTheDocument()
  })

  it('separa los módulos desplazables del bloque Mi cuenta sin empalmarlo', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<div>Inicio ACMA</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Abrir menú' }))
    const lateral = screen.getByRole('complementary', { name: 'Navegación principal' })
    const navegacion = screen.getByRole('navigation', { name: 'Módulos de ACMA' })
    const cuenta = screen.getByText('Mi cuenta')
    expect(lateral).toHaveClass('overflow-hidden')
    expect(navegacion).toHaveClass('overflow-y-auto')
    expect(navegacion).toHaveClass('min-h-0')
    expect(cuenta.closest('.acma-sidebar-cuenta')).not.toBeNull()
    expect(cuenta.closest('.acma-sidebar-cuenta')).toHaveClass('shrink-0')
    expect(navegacion.contains(cuenta)).toBe(false)
  })

  it('etiqueta todas las celdas para mostrarlas como fichas en móvil', () => {
    render(
      <Tabla
        columnas={[{ titulo: 'Folio', celda: (f) => f.numero }, { titulo: 'Estado', celda: (f) => f.estado }]}
        filas={[{ id: '1', numero: 'ACMA-010', estado: 'Abierto' }]}
      />,
    )
    expect(screen.getByRole('table')).toHaveClass('acma-tabla')
    expect(screen.getByText('ACMA-010')).toHaveAttribute('data-label', 'Folio')
    expect(screen.getByText('Abierto')).toHaveAttribute('data-label', 'Estado')
  })
})
