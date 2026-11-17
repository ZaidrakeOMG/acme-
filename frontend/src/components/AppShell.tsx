import { useEffect, useState, type ReactNode } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'
import { modulosDe, NOMBRE_ROL, type GrupoModulo, type Modulo } from '../config/modulos'
import { useAuth } from '../contexts/AuthContext'
import { CampanaNotificaciones } from './CampanaNotificaciones'
import { IndicadorConectividad } from './IndicadorConectividad'

const ORDEN_GRUPOS: GrupoModulo[] = ['Administración', 'Operación', 'Seguimiento', 'Finanzas y activos', 'Análisis']

function Icono({ tipo }: { tipo: 'menu' | 'cerrar' | 'inicio' | 'modulos' | 'seguridad' | 'salir' }) {
  const trazo: Record<typeof tipo, ReactNode> = {
    menu: <><path d="M4 7h16M4 12h16M4 17h16" /></>,
    cerrar: <><path d="M6 6l12 12M18 6 6 18" /></>,
    inicio: <><path d="m3 10 9-7 9 7v10H3z" /><path d="M9 20v-7h6v7" /></>,
    modulos: <><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></>,
    seguridad: <><path d="M12 2 4 6v6c0 5 3.5 8 8 10 4.5-2 8-5 8-10V6z" /><path d="m9 12 2 2 4-4" /></>,
    salir: <><path d="M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h5" /><path d="M14 8l4 4-4 4M18 12H8" /></>,
  }
  return (
    <svg aria-hidden="true" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round"
      strokeWidth="1.8" viewBox="0 0 24 24" className="h-5 w-5 shrink-0">
      {trazo[tipo]}
    </svg>
  )
}

function Navegacion({ modulos, alNavegar }: { modulos: Modulo[]; alNavegar: () => void }) {
  const enlace = ({ isActive }: { isActive: boolean }) =>
    `block rounded-lg px-3 py-2.5 text-sm transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-white ${isActive ? 'bg-white/15 font-semibold text-white' : 'text-white/85 hover:bg-white/10 hover:text-white'}`
  return (
    <nav aria-label="Módulos de ACMA" className="space-y-1 pb-6">
      <NavLink to="/" end className={enlace} onClick={alNavegar}>Inicio</NavLink>
      {ORDEN_GRUPOS.map((grupo) => {
        const delGrupo = modulos.filter((m) => m.grupo === grupo)
        if (!delGrupo.length) return null
        return (
          <div key={grupo} className="pt-4">
            <p className="px-3 pb-1 text-xs font-medium uppercase tracking-wider text-white/60">{grupo}</p>
            {delGrupo.map((m) => (
              <NavLink key={m.id} to={m.ruta!} className={enlace} onClick={alNavegar}>
                {m.nombre}
              </NavLink>
            ))}
          </div>
        )
      })}
      <div className="pt-4">
        <NavLink to="/seguridad" className={enlace} onClick={alNavegar}>Mi seguridad</NavLink>
      </div>
    </nav>
  )
}

/** Navegación móvil tipo aplicación: menú lateral con fondo y barra inferior.
 *  En escritorio permanece el menú tradicional, sin alterar las rutas o permisos. */
export function AppShell() {
  const { usuario, cerrarSesion } = useAuth()
  const [menuAbierto, setMenuAbierto] = useState(false)
  const ubicacion = useLocation()
  const [anchoMovil, setAnchoMovil] = useState(() =>
    typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 767px)').matches)

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const consulta = window.matchMedia('(max-width: 767px)')
    const alCambiar = (e: MediaQueryListEvent) => setAnchoMovil(e.matches)
    consulta.addEventListener('change', alCambiar)
    return () => consulta.removeEventListener('change', alCambiar)
  }, [])

  useEffect(() => {
    setMenuAbierto(false)
  }, [ubicacion.pathname, ubicacion.search])

  useEffect(() => {
    if (!menuAbierto || !anchoMovil) return
    const overflowAnterior = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const alTeclado = (evento: KeyboardEvent) => {
      if (evento.key === 'Escape') setMenuAbierto(false)
    }
    document.addEventListener('keydown', alTeclado)
    return () => {
      document.body.style.overflow = overflowAnterior
      document.removeEventListener('keydown', alTeclado)
    }
  }, [menuAbierto, anchoMovil])

  if (!usuario) return null
  const modulos = modulosDe(usuario.rol).filter((m) => m.ruta)

  return (
    <div className="min-h-dvh min-w-0 bg-fondo md:flex">
      {/* Fondo tocable para cerrar el menú móvil, sin desplazar el contenido. */}
      {menuAbierto && anchoMovil && (
        <button type="button" aria-label="Cerrar navegación" onClick={() => setMenuAbierto(false)}
          className="fixed inset-0 z-40 bg-slate-950/60 backdrop-blur-[2px] md:hidden" />
      )}
      <aside
        id="acma-menu"
        aria-label="Navegación principal"
        aria-hidden={anchoMovil && !menuAbierto}
        inert={anchoMovil && !menuAbierto}
        className={`fixed inset-y-0 left-0 z-50 w-[min(19.5rem,88vw)] overflow-y-auto overscroll-contain bg-primario px-3 pb-5 pt-4 shadow-xl transition-transform duration-200 ease-out md:sticky md:top-0 md:z-auto md:h-screen md:w-64 md:shrink-0 md:translate-x-0 md:shadow-none ${menuAbierto ? 'translate-x-0' : '-translate-x-full'}`}
      >
        <div className="mb-5 flex items-center justify-between gap-2 px-3">
          <div className="flex items-center gap-2">
            <img src="/icono.svg" alt="" className="h-9 w-9" />
            <span className="text-lg font-semibold tracking-wide text-white">ACMA</span>
          </div>
          <button type="button" onClick={() => setMenuAbierto(false)}
            aria-label="Cerrar menú" className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg text-white hover:bg-white/10 md:hidden">
            <Icono tipo="cerrar" />
          </button>
        </div>
        {(!anchoMovil || menuAbierto) && <Navegacion modulos={modulos} alNavegar={() => setMenuAbierto(false)} />}
      </aside>

      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-30 flex min-h-14 items-center justify-between gap-2 border-b border-slate-200 bg-white/95 px-3 py-2 backdrop-blur sm:px-4 md:px-8">
          <button type="button" aria-label="Abrir menú" aria-controls="acma-menu" aria-expanded={menuAbierto}
            className="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-lg text-primario hover:bg-slate-100 md:hidden"
            onClick={() => setMenuAbierto(true)}>
            <Icono tipo="menu" />
          </button>
          <div className="flex min-w-0 flex-1 flex-col items-start justify-center gap-1 sm:flex-row sm:items-center sm:gap-3">
            <span className="max-w-full truncate text-xs font-medium text-slate-600 sm:text-sm">{usuario.tema.prestador ?? 'Plataforma ACMA'}</span>
            <IndicadorConectividad />
          </div>
          <div className="flex shrink-0 items-center gap-1 sm:gap-2">
            <CampanaNotificaciones />
            <div className="hidden max-w-36 text-right leading-tight sm:block">
              <p className="truncate text-sm font-medium text-slate-900">{usuario.nombre}</p>
              <p className="truncate text-xs text-slate-500">{NOMBRE_ROL[usuario.rol]}</p>
            </div>
            <button type="button" className="hidden min-h-11 items-center gap-1 rounded-lg px-3 text-sm text-slate-600 hover:bg-slate-100 md:inline-flex"
              onClick={() => void cerrarSesion()}>
              <Icono tipo="salir" /> Salir
            </button>
          </div>
        </header>

        <main id="contenido-acma" className="acma-contenido mx-auto w-full min-w-0 max-w-6xl px-3 pb-24 pt-4 sm:px-4 sm:pt-6 md:px-8 md:pb-10 md:pt-8">
          <Outlet />
        </main>
      </div>

      {/* Accesos rápidos permanentes para teléfonos, sin duplicar las pantallas. */}
      <nav aria-label="Accesos rápidos" className="acma-barra-movil fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-slate-200 bg-white/95 shadow-[0_-4px_20px_rgba(15,23,42,.06)] backdrop-blur md:hidden">
        <NavLink to="/" end className={({ isActive }) => `acma-acceso-rapido ${isActive ? 'text-primario' : 'text-slate-500'}`}>
          <Icono tipo="inicio" /><span>Inicio</span>
        </NavLink>
        <button type="button" onClick={() => setMenuAbierto(true)}
          aria-label="Mostrar módulos" className="acma-acceso-rapido text-slate-500">
          <Icono tipo="modulos" /><span>Módulos</span>
        </button>
        <NavLink to="/notificaciones" className={({ isActive }) => `acma-acceso-rapido ${isActive ? 'text-primario' : 'text-slate-500'}`}>
          <svg aria-hidden="true" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" viewBox="0 0 24 24" className="h-5 w-5">
            <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9ZM10 21h4" />
          </svg><span>Avisos</span>
        </NavLink>
        <NavLink to="/seguridad" className={({ isActive }) => `acma-acceso-rapido ${isActive ? 'text-primario' : 'text-slate-500'}`}>
          <Icono tipo="seguridad" /><span>Seguridad</span>
        </NavLink>
      </nav>
    </div>
  )
}
