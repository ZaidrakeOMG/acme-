import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'
import { App } from '../src/App'
import { AuthProvider } from '../src/contexts/AuthContext'
import type { PerfilConTema, Rol } from '../src/types/api'

type Manejador = (cuerpo: unknown, url: URL) => { estado?: number; json: unknown }

/** Simula la API: { 'POST /api/auth/login': (cuerpo) => ({ json }) }. Devuelve las llamadas registradas. */
export function simularApi(rutas: Record<string, Manejador>) {
  const llamadas: { clave: string; cuerpo: unknown }[] = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (entrada, init) => {
    const url = new URL(String(entrada), 'http://localhost')
    const clave = `${init?.method ?? 'GET'} ${url.pathname}`
    const cuerpo: unknown = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined
    llamadas.push({ clave, cuerpo })
    const manejador = rutas[clave]
    if (!manejador) {
      return new Response(JSON.stringify({ codigo: 'NO_ENCONTRADO', mensaje: `Sin simulación para ${clave}`, detalles: [] }), { status: 404 })
    }
    const { estado = 200, json } = manejador(cuerpo, url)
    return new Response(JSON.stringify(json), { status: estado, headers: { 'Content-Type': 'application/json' } })
  })
  return llamadas
}

export const TOKENS = { access_token: 'acceso', refresh_token: 'refresh-de-prueba-suficientemente-largo', token_type: 'bearer', expira_en: 900 }

const ROLES_TENANT: Rol[] = ['admin_empresa', 'admin_un', 'supervisor_operadores', 'operador']

export function perfil(rol: Rol, extra: Partial<PerfilConTema> = {}): PerfilConTema {
  return {
    id: '00000000-0000-0000-0000-000000000001',
    email: `${rol}@acma.dev`,
    nombre: 'Persona Prueba',
    telefono: null,
    rol,
    dominio: rol === 'superadmin' ? 'plataforma' : ROLES_TENANT.includes(rol) ? 'tenant' : 'prestador',
    tenant_id: null,
    prestador_id: null,
    mfa_habilitado: false,
    mfa_obligatorio: false,
    tema: { color_primario: '#1C3D8F', color_acento: '#A2C62B', prestador: 'Prestador Demo' },
    ...extra,
  }
}

export function renderApp(ruta = '/') {
  return render(
    <MemoryRouter initialEntries={[ruta]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}
