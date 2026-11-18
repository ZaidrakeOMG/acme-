import 'fake-indexeddb/auto'
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// Node 25 expone un localStorage experimental (sin --localstorage-file no funciona) que tapa el de jsdom.
class AlmacenMemoria implements Storage {
  private datos = new Map<string, string>()
  get length() {
    return this.datos.size
  }
  clear() {
    this.datos.clear()
  }
  getItem(clave: string) {
    return this.datos.get(clave) ?? null
  }
  key(indice: number) {
    return [...this.datos.keys()][indice] ?? null
  }
  removeItem(clave: string) {
    this.datos.delete(clave)
  }
  setItem(clave: string, valor: string) {
    this.datos.set(clave, String(valor))
  }
}

for (const nombre of ['localStorage', 'sessionStorage'] as const) {
  Object.defineProperty(globalThis, nombre, { value: new AlmacenMemoria(), configurable: true, writable: true })
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  localStorage.clear()
  // Las cookies jsdom sobreviven entre pruebas; aislar la cookie CSRF de cada sesión.
  document.cookie = 'acma_csrf=; Max-Age=0; path=/'
})
