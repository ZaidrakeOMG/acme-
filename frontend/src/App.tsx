import type { ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router'
import { AppShell } from './components/AppShell'
import { MODULOS } from './config/modulos'
import { useAuth } from './contexts/AuthContext'
import { Alertas } from './pages/admin/Alertas'
import { Auditoria } from './pages/admin/Auditoria'
import { Contratos } from './pages/admin/Contratos'
import { Prestadores, Tenants } from './pages/admin/Organizaciones'
import { Unidades } from './pages/admin/Unidades'
import { Usuarios } from './pages/admin/Usuarios'
import { Catalogos } from './pages/catalogos/Catalogos'
import { Login } from './pages/Login'
import { RoleHub } from './pages/RoleHub'
import { Seguridad } from './pages/Seguridad'

const PAGINAS: Record<string, ReactNode> = {
  usuarios: <Usuarios />,
  tenants: <Tenants />,
  prestadores: <Prestadores />,
  unidades: <Unidades />,
  contratos: <Contratos />,
  alertas: <Alertas />,
  auditoria: <Auditoria />,
  catalogos: <Catalogos />,
}

function SinPermiso() {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-8 text-center">
      <h1 className="text-lg font-semibold text-slate-900">Sin acceso</h1>
      <p className="mt-2 text-sm text-slate-600">Tu rol no tiene acceso a este módulo.</p>
    </div>
  )
}

export function App() {
  const { usuario, cargando } = useAuth()
  if (cargando) {
    return <div className="flex min-h-screen items-center justify-center text-slate-500">Cargando…</div>
  }
  if (!usuario) {
    return (
      <Routes>
        <Route path="*" element={<Login />} />
      </Routes>
    )
  }
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<RoleHub />} />
        <Route path="seguridad" element={<Seguridad />} />
        {MODULOS.filter((m) => m.ruta).map((m) => (
          <Route
            key={m.id}
            path={m.ruta!.slice(1)}
            element={usuario.rol === 'superadmin' || m.roles.includes(usuario.rol) ? PAGINAS[m.id] : <SinPermiso />}
          />
        ))}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
