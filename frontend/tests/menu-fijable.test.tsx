import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AppShell } from '../src/components/AppShell'

vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: () => ({
    usuario: { id: 'super-menu', nombre: 'Usuario Prueba', rol: 'superadmin',
      tema: { prestador: 'Plataforma ACMA' } },
    cerrarSesion: vi.fn(),
  }),
}))
vi.mock('../src/components/TestBotAcma', () => ({ TestBotAcma: () => null }))
vi.mock('../src/components/CampanaNotificaciones', () => ({
  CampanaNotificaciones: () => <span>Avisos</span>,
}))
vi.mock('../src/components/IndicadorConectividad', () => ({
  IndicadorConectividad: () => <span>En línea</span>,
}))

beforeEach(() => {
  localStorage.clear()
  Object.defineProperty(window, 'matchMedia', { configurable: true, writable: true,
    value: vi.fn((query: string) => ({
      matches: false, media: query, onchange: null, addListener: vi.fn(),
      removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  })
})

function pantalla() {
  render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<div>Inicio ACMA de prueba</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

describe('Menú ACMA fijable / desplegable en escritorio', () => {
  it('desfija y abre el carril temporal al pasar el cursor; puede fijarse de nuevo', () => {
    pantalla()
    const barra = screen.getByRole('complementary', { name: 'Navegación principal' })
    const desfijar = screen.getByRole('button', { name: 'Desfijar menú lateral' })
    expect(desfijar).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(desfijar)
    expect(localStorage.getItem('acma.menu.fijado.v1')).toBe('false')
    expect(screen.getByRole('navigation', { name: 'Menú contraído' })).toBeInTheDocument()
    fireEvent.mouseEnter(barra)
    expect(screen.getByRole('navigation', { name: 'Módulos de ACMA' })).toBeInTheDocument()
    const fijar = screen.getByRole('button', { name: 'Fijar menú lateral' })
    expect(fijar).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(fijar)
    expect(localStorage.getItem('acma.menu.fijado.v1')).toBe('true')
    expect(screen.queryByRole('navigation', { name: 'Menú contraído' })).not.toBeInTheDocument()
  })

  it('recuerda que el menú estaba desfijado al entrar de nuevo', () => {
    localStorage.setItem('acma.menu.fijado.v1', 'false')
    pantalla()
    const lateral = screen.getByRole('complementary', { name: 'Navegación principal' })
    expect(screen.getByRole('navigation', { name: 'Menú contraído' })).toBeInTheDocument()
    fireEvent.mouseEnter(lateral)
    expect(screen.getByRole('button', { name: 'Fijar menú lateral' })).toBeInTheDocument()
    fireEvent.mouseLeave(lateral)
    expect(screen.getByRole('navigation', { name: 'Menú contraído' })).toBeInTheDocument()
  })
})
