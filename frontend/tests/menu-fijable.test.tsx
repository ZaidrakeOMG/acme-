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

describe('Menú ACMA fijable y táctil en navegador / Flutter WebView', () => {
  it('desfija sin cerrar bruscamente; botón contraer y botón desplegar funcionan sin hover', () => {
    pantalla()
    const desfijar = screen.getByRole('button', { name: 'Desfijar menú lateral' })
    expect(desfijar).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(desfijar)
    expect(localStorage.getItem('acma.menu.fijado.v1')).toBe('false')
    expect(screen.getByRole('navigation', { name: 'Módulos de ACMA' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Contraer menú lateral' }))
    expect(screen.getByRole('navigation', { name: 'Menú contraído' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Módulos de ACMA' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Desplegar menú lateral' }))
    expect(screen.getByRole('navigation', { name: 'Módulos de ACMA' })).toBeInTheDocument()
    const fijar = screen.getByRole('button', { name: 'Fijar menú lateral' })
    fireEvent.click(fijar)
    expect(localStorage.getItem('acma.menu.fijado.v1')).toBe('true')
    expect(screen.queryByRole('navigation', { name: 'Menú contraído' })).not.toBeInTheDocument()
  })

  it('recuerda el estado compacto; un toque abre módulos y Escape vuelve a contraer', () => {
    localStorage.setItem('acma.menu.fijado.v1', 'false')
    pantalla()
    expect(screen.getByRole('navigation', { name: 'Menú contraído' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Desplegar menú lateral' }))
    expect(screen.getByRole('button', { name: 'Fijar menú lateral' })).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.getByRole('navigation', { name: 'Menú contraído' })).toBeInTheDocument()
  })

  it('permite desplegar mediante los accesos rápidos y cerrar con clic fuera', () => {
    localStorage.setItem('acma.menu.fijado.v1', 'false')
    pantalla()
    fireEvent.click(screen.getByRole('button', { name: 'Abrir Folios' }))
    expect(screen.getByRole('navigation', { name: 'Módulos de ACMA' })).toBeInTheDocument()
    fireEvent.pointerDown(screen.getByText('Inicio ACMA de prueba'))
    expect(screen.getByRole('navigation', { name: 'Menú contraído' })).toBeInTheDocument()
  })

  it('el panel fijo conserva sus módulos y no depende de pasar el cursor', () => {
    pantalla()
    const lateral = screen.getByRole('complementary', { name: 'Navegación principal' })
    fireEvent.mouseLeave(lateral)
    expect(screen.getByRole('link', { name: 'Folios' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Desfijar menú lateral' })).toBeInTheDocument()
  })
})
