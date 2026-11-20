import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TestBotAcma } from '../src/components/TestBotAcma'

vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: () => ({
    usuario: { id: 'usuario-burbuja-demo', nombre: 'Usuario DEMO', rol: 'superadmin' },
  }),
}))

beforeEach(() => {
  localStorage.clear()
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1080 })
  Object.defineProperty(window, 'innerHeight', { configurable: true, value: 810 })
})
afterEach(() => {
  vi.restoreAllMocks()
})

function pantalla() {
  render(
    <MemoryRouter initialEntries={['/folios']}>
      <Routes>
        <Route path="/folios" element={
          <>
            <main id="contenido-acma">
              <form>
                <label htmlFor="descripcion">Descripción</label>
                <textarea id="descripcion" required />
              </form>
            </main>
            <TestBotAcma />
          </>
        } />
      </Routes>
    </MemoryRouter>,
  )
}

describe('Burbuja móvil del Asistente ACMA', () => {
  it('un toque abre la ayuda y una pregunta sobre campos responde sin leer su contenido', async () => {
    pantalla()
    const burbuja = screen.getByTestId('acma-asistente-burbuja')
    fireEvent.click(burbuja)
    expect(screen.getByRole('dialog', { name: /Asistente de ayuda ACMA/ })).toBeInTheDocument()
    const campo = screen.getByLabelText('Descripción') as HTMLTextAreaElement
    campo.value = 'información privada 987654'
    // En jsdom no hay layout; simular los controles del formulario visibles.
    const getRects = vi.spyOn(HTMLElement.prototype, 'getClientRects').mockImplementation(() =>
      ({ length: 1 }) as DOMRectList)
    try {
      fireEvent.click(screen.getByRole('button', { name: '¿Cómo lleno estos campos?' }))
      expect(await screen.findByText(/Cómo llenar Folios campo por campo/)).toBeInTheDocument()
      expect(screen.getByText(/Descripción \(obligatorio\)/)).toBeInTheDocument()
      expect(screen.queryByText(/información privada/)).not.toBeInTheDocument()
    } finally {
      getRects.mockRestore()
    }
  })

  it('permite mover con flechas y guarda posición por usuario', async () => {
    pantalla()
    const burbuja = screen.getByTestId('acma-asistente-burbuja')
    const anterior = Number(burbuja.style.left.replace('px', ''))
    fireEvent.keyDown(burbuja, { key: 'ArrowLeft' })
    expect(Number(burbuja.style.left.replace('px', ''))).toBe(anterior - 18)
    expect(localStorage.getItem('acma.asistente.burbuja.v1.usuario-burbuja-demo')).toContain('"x":')
    fireEvent.click(burbuja)
    expect(screen.getByRole('dialog', { name: /Asistente de ayuda ACMA/ })).toBeInTheDocument()
  })

  it('el arrastre táctil cambia posición sin abrir accidentalmente el panel', async () => {
    pantalla()
    const burbuja = screen.getByTestId('acma-asistente-burbuja')
    const anterior = Number(burbuja.style.left.replace('px', ''))
    fireEvent.pointerDown(burbuja, { pointerId: 4, pointerType: 'touch', button: 0, clientX: 500, clientY: 500 })
    fireEvent.pointerMove(burbuja, { pointerId: 4, pointerType: 'touch', button: 0, clientX: 455, clientY: 440 })
    fireEvent.pointerUp(burbuja, { pointerId: 4, pointerType: 'touch', button: 0, clientX: 455, clientY: 440 })
    await waitFor(() => expect(Number(burbuja.style.left.replace('px', ''))).toBe(anterior - 45))
    expect(screen.queryByRole('dialog', { name: /Asistente de ayuda ACMA/ })).not.toBeInTheDocument()
    expect(localStorage.getItem('acma.asistente.burbuja.v1.usuario-burbuja-demo')).toContain('"x":')
    // Un toque posterior, ya independiente del arrastre, debe poder abrir el panel.
    // El propio arrastre no debe abrirlo; eso se verifica arriba.
  })
})
