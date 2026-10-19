import { useState } from 'react'
import { NavLink, Outlet } from 'react-router'
import { modulosDe, NOMBRE_ROL, type GrupoModulo } from '../config/modulos'
import { useAuth } from '../contexts/AuthContext'

const ORDEN_GRUPOS: GrupoModulo[] = ['Administración', 'Operación', 'Seguimiento', 'Finanzas y activos', 'Análisis']

export function AppShell() {
  const { usuario, cerrarSesion } = useAuth()
  const [menuAbierto, setMenuAbierto] = useState(false)
  if (!usuario) return null
  const modulos = modulosDe(usuario.rol).filter((m) => m.ruta)

  const enlace = ({ isActive }: { isActive: boolean }) =>
    `block rounded-lg px-3 py-2 text-sm ${isActive ? 'bg-white/15 font-medium text-white' : 'text-white/80 hover:bg-white/10 hover:text-white'}`

  return (
    <div className="min-h-screen bg-fondo md:flex">
      <aside
        className={`${menuAbierto ? 'block' : 'hidden'} bg-primario px-3 py-5 md:sticky md:top-0 md:block md:h-screen md:w-64 md:shrink-0 md:overflow-y-auto`}
        aria-label="Navegación principal"
      >
        <div className="mb-6 flex items-center gap-2 px-3">
          <img src="/icono.svg" alt="" className="h-8 w-8" />
          <span className="text-lg font-semibold tracking-wide text-white">ACMA</span>
        </div>
        <nav className="space-y-1">
          <NavLink to="/" end className={enlace} onClick={() => setMenuAbierto(false)}>
            Inicio
          </NavLink>
          {ORDEN_GRUPOS.map((grupo) => {
            const delGrupo = modulos.filter((m) => m.grupo === grupo)
            if (delGrupo.length === 0) return null
            return (
              <div key={grupo} className="pt-4">
                <p className="px-3 pb-1 text-xs font-medium uppercase tracking-wider text-white/50">{grupo}</p>
                {delGrupo.map((m) => (
                  <NavLink key={m.id} to={m.ruta!} className={enlace} onClick={() => setMenuAbierto(false)}>
                    {m.nombre}
                  </NavLink>
                ))}
              </div>
            )
          })}
          <div className="pt-4">
            <NavLink to="/seguridad" className={enlace} onClick={() => setMenuAbierto(false)}>
              Mi seguridad
            </NavLink>
          </div>
        </nav>
      </aside>

      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-slate-200 bg-white/95 px-4 py-3 backdrop-blur md:px-8">
          <button className="rounded-lg p-2 text-slate-600 hover:bg-slate-100 md:hidden" aria-label="Abrir menú" onClick={() => setMenuAbierto((v) => !v)}>
            ☰
          </button>
          <div className="min-w-0 flex-1 truncate text-sm text-slate-500">{usuario.tema.prestador ?? 'Plataforma ACMA'}</div>
          <div className="flex items-center gap-3">
            <div className="text-right leading-tight">
              <p className="text-sm font-medium text-slate-900">{usuario.nombre}</p>
              <p className="text-xs text-slate-500">{NOMBRE_ROL[usuario.rol]}</p>
            </div>
            <span className="hidden h-9 w-9 items-center justify-center rounded-full bg-acento font-semibold text-slate-900 sm:flex">
              {usuario.nombre.charAt(0)}
            </span>
            <button className="rounded-lg px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100" onClick={() => void cerrarSesion()}>
              Salir
            </button>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-6 md:px-8 md:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
