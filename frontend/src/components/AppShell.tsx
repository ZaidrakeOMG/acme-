import { useEffect, useMemo, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'
import { modulosDe, NOMBRE_ROL, type GrupoModulo, type Modulo } from '../config/modulos'
import { useAuth } from '../contexts/AuthContext'
import { CampanaNotificaciones } from './CampanaNotificaciones'
import { IndicadorConectividad } from './IndicadorConectividad'
import { IndicadorEstadoTestBot } from './IndicadorEstadoTestBot'
import { useIndicadoresTestBot, type IndicadoresTestBot } from '../services/testbotEstadoVisual'
import { IconoAcma } from './IconosAcma'
import { TestBotAcma } from './TestBotAcma'

const GRUPOS: GrupoModulo[] = ['Operación', 'Seguimiento', 'Administración', 'Finanzas y activos', 'Análisis']

function nombreActual(modulos: Modulo[], pathname: string): string {
  if (pathname === '/') return 'Centro de operaciones'
  if (pathname === '/seguridad') return 'Seguridad de la cuenta'
  const encontrados = modulos.filter(m => {
    const ruta = m.ruta.split('?')[0]
    return pathname === ruta || pathname.startsWith(ruta + '/')
  }).sort((a, b) => b.ruta.length - a.ruta.length)
  return encontrados[0]?.nombre ?? 'Espacio de trabajo'
}

function Navegacion({ modulos, alNavegar, rutaActual, indicadores, mostrarEstados }: {
  modulos: Modulo[]
  alNavegar: () => void
  rutaActual: string
  indicadores: IndicadoresTestBot
  mostrarEstados: boolean
}) {
  const [busqueda, setBusqueda] = useState('')
  const [gruposAbiertos, setGruposAbiertos] = useState<GrupoModulo[]>(['Operación'])
  const texto = busqueda.trim().toLocaleLowerCase('es-MX')

  useEffect(() => {
    const grupo = modulos.find(m => {
      const ruta = m.ruta.split('?')[0]
      return ruta === rutaActual || rutaActual.startsWith(ruta + '/')
    })?.grupo
    if (grupo) setGruposAbiertos(prev => prev.includes(grupo) ? prev : [...prev, grupo])
  }, [rutaActual, modulos])

  const alternarGrupo = (grupo: GrupoModulo) =>
    setGruposAbiertos(prev => prev.includes(grupo) ? prev.filter(g => g !== grupo) : [...prev, grupo])

  const filtrados = texto
    ? modulos.filter(m => `${m.nombre} ${m.descripcion} ${m.grupo}`.toLocaleLowerCase('es-MX').includes(texto))
    : modulos

  const estiloEnlace = ({ isActive }: { isActive: boolean }) =>
    `acma-nav-enlace ${isActive ? 'acma-nav-enlace-activo' : ''}`

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="mb-3 shrink-0 px-2">
        <label htmlFor="acma-buscar-modulo" className="sr-only">Buscar módulo</label>
        <div className="acma-nav-buscador">
          <IconoAcma nombre="buscar" className="h-[18px] w-[18px]" />
          <input
            id="acma-buscar-modulo"
            type="search"
            value={busqueda}
            onChange={e => setBusqueda(e.target.value)}
            placeholder="Buscar módulo"
            className="min-w-0 flex-1 bg-transparent text-sm text-white placeholder:text-white/50 outline-none"
          />
        </div>
      </div>
      {mostrarEstados && (
        <details className="mb-2 shrink-0 px-3 text-[11px] text-white/65">
          <summary className="cursor-pointer select-none hover:text-white">
            Indicadores de la última prueba DEMO
          </summary>
          <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1">
            <span><span className="text-emerald-300">●</span> Alta y edición</span>
            <span><span className="text-teal-300">●</span> Alta</span>
            <span><span className="text-sky-300">●</span> Solo consulta</span>
            <span><span className="text-amber-300">●</span> Pendiente</span>
            <span><span className="text-rose-300">●</span> Error</span>
            <span><span className="text-slate-300">●</span> Sin probar</span>
          </div>
          <p className="mt-1 text-white/50">No representan salud en tiempo real ni aprobación total.</p>
        </details>
      )}
      <nav aria-label="Módulos de ACMA" className="acma-menu-scroll min-h-0 flex-1 space-y-1 overflow-y-auto overscroll-contain pb-5 pr-1">
        <NavLink to="/" end className={estiloEnlace} onClick={alNavegar}>
          <span className="acma-nav-icono"><IconoAcma nombre="inicio" /></span>
          <span className="min-w-0 flex-1 truncate">Inicio</span>
        </NavLink>
        {GRUPOS.map(grupo => {
          const delGrupo = filtrados.filter(m => m.grupo === grupo)
          if (!delGrupo.length) return null
          const abierto = Boolean(texto) || gruposAbiertos.includes(grupo)
          const id = `acma-seccion-${GRUPOS.indexOf(grupo)}`
          return (
            <div key={grupo} className="pt-3">
              <button
                type="button"
                onClick={() => alternarGrupo(grupo)}
                aria-expanded={abierto}
                aria-controls={id}
                className="acma-nav-grupo"
              >
                <span className="min-w-0 flex-1 truncate">{grupo}</span>
                <span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] tabular-nums text-white/60">{delGrupo.length}</span>
                <IconoAcma nombre="chevron" className={`h-4 w-4 transition-transform duration-200 ${abierto ? 'rotate-180' : ''}`} />
              </button>
              {abierto && (
                <div id={id} className="acma-nav-opciones">
                  {delGrupo.map(m => (
                    <NavLink key={m.id} to={m.ruta} aria-label={m.nombre} className={estiloEnlace} onClick={alNavegar}>
                      <span className="acma-nav-icono"><IconoAcma nombre={m.id} /></span>
                      <span className="min-w-0 flex-1 truncate">{m.nombre}</span>
                      {mostrarEstados && (
                        <IndicadorEstadoTestBot compacto
                          estado={m.id === 'formularios' ? indicadores.formularios : indicadores.modulos[m.id]} />
                      )}
                    </NavLink>
                  ))}
                </div>
              )}
            </div>
          )
        })}
        {filtrados.length === 0 && (
          <p role="status" className="px-3 py-5 text-center text-sm text-white/65">
            No encontramos módulos con ese nombre.
          </p>
        )}
        <div className="mt-4 border-t border-white/10 pt-4">
          <NavLink to="/seguridad" className={estiloEnlace} onClick={alNavegar}>
            <span className="acma-nav-icono"><IconoAcma nombre="seguridad" /></span>
            <span className="min-w-0 flex-1 truncate">Mi seguridad</span>
          </NavLink>
        </div>
      </nav>
    </div>
  )
}

/** Shell compartido por React Web y la WebView Android. Mantiene rutas, permisos y estados existentes. */
export function AppShell() {
  const { usuario, cerrarSesion } = useAuth()
  const indicadoresTestBot = useIndicadoresTestBot(usuario?.id ?? '', usuario?.rol === 'superadmin')
  const [menuAbierto, setMenuAbierto] = useState(false)
  // Fijado: ancho permanente. Desfijado: barra compacta; clic para abrir en Web o Flutter.
  const [menuFijado, setMenuFijado] = useState(() => {
    try { return localStorage.getItem('acma.menu.fijado.v1') !== 'false' } catch { return true }
  })
  const [menuDesplegado, setMenuDesplegado] = useState(false)
  const menuVisibleEscritorio = menuFijado || menuDesplegado
  function alternarMenuFijado() {
    const fijado = !menuFijado
    setMenuFijado(fijado)
    setMenuDesplegado(!fijado)
    try { localStorage.setItem('acma.menu.fijado.v1', String(fijado)) } catch { /* opcional */ }
  }
  const [perfilAbierto, setPerfilAbierto] = useState(false)
  const ubicacion = useLocation()
  const [anchoMovil, setAnchoMovil] = useState(() =>
    typeof window !== 'undefined' && typeof window.matchMedia === 'function' &&
    window.matchMedia('(max-width: 1023px)').matches)

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const consulta = window.matchMedia('(max-width: 1023px)')
    const alCambiar = (e: MediaQueryListEvent) => setAnchoMovil(e.matches)
    // Safari antiguos usan addListener; sin esto la navegación puede romperse al montar.
    if (typeof consulta.addEventListener === 'function') {
      consulta.addEventListener('change', alCambiar)
      return () => consulta.removeEventListener('change', alCambiar)
    }
    consulta.addListener(alCambiar)
    return () => consulta.removeListener(alCambiar)
  }, [])

  useEffect(() => {
    setMenuAbierto(false)
    setMenuDesplegado(false)
    setPerfilAbierto(false)
  }, [ubicacion.pathname, ubicacion.search])

  // Tanto en navegador como en WebView: clic exterior o Escape contrae panel temporal.
  useEffect(() => {
    if (anchoMovil || menuFijado || !menuDesplegado) return
    const alExterior = (e: PointerEvent) => {
      if (e.target instanceof Node && !document.getElementById('acma-menu')?.contains(e.target))
        setMenuDesplegado(false)
    }
    const alTeclado = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenuDesplegado(false)
    }
    document.addEventListener('pointerdown', alExterior)
    document.addEventListener('keydown', alTeclado)
    return () => {
      document.removeEventListener('pointerdown', alExterior)
      document.removeEventListener('keydown', alTeclado)
    }
  }, [anchoMovil, menuFijado, menuDesplegado])

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

  const modulos = useMemo(() => usuario ? modulosDe(usuario.rol).filter(m => m.ruta) : [], [usuario?.rol])
  if (!usuario) return null
  const titulo = nombreActual(modulos, ubicacion.pathname)
  const iniciales = usuario.nombre.split(/\s+/).filter(Boolean).slice(0, 2).map(p => p[0]?.toUpperCase()).join('')
  const volverAlInicio = () => {
    setMenuAbierto(false)
    if (!menuFijado) setMenuDesplegado(false)
  }

  return (
    <div className="acma-shell flex min-h-dvh min-w-0 bg-fondo lg:flex">
      {menuAbierto && anchoMovil && (
        <button type="button" aria-label="Cerrar navegación" onClick={() => setMenuAbierto(false)}
          className="fixed inset-0 z-40 bg-[#08162b]/70 backdrop-blur-[3px] lg:hidden" />
      )}
      <div className={'lg:sticky lg:top-0 lg:h-[100dvh] lg:shrink-0 lg:self-start lg:transition-[width] lg:duration-200 ' +
        (menuFijado ? 'lg:w-[17.5rem]' : 'lg:w-[4.75rem]')}>
      <aside
        onMouseEnter={() => { if (!menuFijado && !anchoMovil) setMenuDesplegado(true) }}
        onMouseLeave={() => { if (!menuFijado && !anchoMovil) setMenuDesplegado(false) }}
        onFocusCapture={() => { if (!menuFijado && !anchoMovil) setMenuDesplegado(true) }}
        onBlurCapture={event => {
          if (!menuFijado && !anchoMovil && !event.currentTarget.contains(event.relatedTarget as Node | null))
            setMenuDesplegado(false)
        }}
        id="acma-menu"
        aria-label="Navegación principal"
        aria-hidden={anchoMovil && !menuAbierto}
        inert={anchoMovil && !menuAbierto}
        className={'acma-sidebar fixed inset-y-0 left-0 z-50 flex h-[100dvh] w-[min(19rem,88vw)] flex-col overflow-hidden px-3 pb-[max(1rem,env(safe-area-inset-bottom))] pt-5 shadow-2xl transition-[transform,width] duration-200 ease-out lg:absolute lg:inset-y-0 lg:left-0 lg:z-40 lg:h-full lg:translate-x-0 ' +
          (menuVisibleEscritorio ? 'lg:w-[17.5rem] ' : 'lg:w-[4.75rem] ') +
          (menuFijado ? 'lg:shadow-none ' : 'lg:shadow-xl ') +
          (menuAbierto ? 'translate-x-0' : '-translate-x-full')}
      >
        <div className={'mb-5 flex shrink-0 items-center gap-2 px-2 ' +
          (menuVisibleEscritorio ? 'justify-between' : 'justify-center')}>
          <NavLink to="/" className="flex min-w-0 items-center gap-3" aria-label="Inicio ACMA" onClick={volverAlInicio}>
            <div className="acma-logo-caja">
              <img src="/icono.svg" alt="Identidad ACMA" className="h-10 w-10 object-contain" />
            </div>
            {(anchoMovil || menuVisibleEscritorio) && (
              <div className="min-w-0">
                <strong className="block text-xl font-extrabold tracking-[.13em] text-white">ACMA</strong>
                <span className="block text-[10px] font-medium tracking-wide text-white/55">PLATAFORMA EMPRESARIAL</span>
              </div>
            )}
          </NavLink>
          {(anchoMovil || menuVisibleEscritorio) && (
            <button type="button" onClick={alternarMenuFijado}
              aria-label={menuFijado ? 'Desfijar menú lateral' : 'Fijar menú lateral'}
              title={menuFijado ? 'Desfijar: desplegar al pasar el cursor' : 'Fijar: mantener el menú abierto'}
              aria-pressed={menuFijado}
              className="hidden h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-white/15 bg-white/10 text-white hover:bg-white/20 lg:inline-flex">
              <IconoAcma nombre={menuFijado ? 'desfijar' : 'fijar'} className="h-5 w-5" />
            </button>
          )}
          <button type="button" onClick={() => setMenuAbierto(false)}
            aria-label="Cerrar menú" className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-xl text-white hover:bg-white/10 lg:hidden">
            <IconoAcma nombre="cerrar" />
          </button>
        </div>

        {(anchoMovil || menuVisibleEscritorio) && (
        <div className="acma-sidebar-etiqueta mb-4 flex shrink-0 items-center gap-3 rounded-xl px-3 py-3">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/10 text-white"><IconoAcma nombre="cuadrícula" className="h-4 w-4" /></span>
          <span className="min-w-0">
            <span className="block text-[10px] uppercase tracking-[.14em] text-white/55">Espacio de trabajo</span>
            <span className="block truncate text-sm font-semibold text-white">{usuario.tema?.prestador ?? 'ACMA'}</span>
          </span>
        </div>

        )}
        {!anchoMovil && !menuVisibleEscritorio && (
          <nav aria-label="Menú contraído" className="flex min-h-0 flex-1 flex-col items-center gap-3 pt-2">
            <button type="button" aria-label="Desplegar menú lateral"
              title="Desplegar menú lateral"
              onClick={() => setMenuDesplegado(true)}
              className="flex h-11 w-11 items-center justify-center rounded-xl bg-white/10 text-white hover:bg-white/20">
              <IconoAcma nombre="menu" />
            </button>
            <NavLink to="/" aria-label="Inicio" title="Inicio"
              className="flex h-11 w-11 items-center justify-center rounded-xl bg-white/10 text-white hover:bg-white/20">
              <IconoAcma nombre="inicio" />
            </NavLink>
          </nav>
        )}
        {(menuVisibleEscritorio || anchoMovil && menuAbierto) && (
          <Navegacion modulos={modulos} rutaActual={ubicacion.pathname} alNavegar={volverAlInicio}
            indicadores={indicadoresTestBot} mostrarEstados={usuario.rol === 'superadmin'} />
        )}
        <div className="acma-sidebar-cuenta relative z-10 mt-3 shrink-0 border-t border-white/10 pt-3">
          <div className="flex items-center gap-3 rounded-xl px-2 py-2">
            <span className="acma-avatar bg-white/15 text-white">{iniciales || 'AC'}</span>
            {(anchoMovil || menuVisibleEscritorio) && (
              <div className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold text-white">Mi cuenta</span>
                <span className="block truncate text-xs text-white/60">{NOMBRE_ROL[usuario.rol]}</span>
              </div>
            )}
            {(anchoMovil || menuVisibleEscritorio) && (
            <button type="button" aria-label="Cerrar sesión" title="Cerrar sesión" onClick={() => void cerrarSesion()}
              className="flex h-10 w-10 items-center justify-center rounded-lg text-white/65 hover:bg-white/10 hover:text-white">
              <IconoAcma nombre="salir" className="h-[18px] w-[18px]" />
            </button>
            )}
          </div>
        </div>
      </aside>
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="acma-header sticky top-0 z-30 flex min-h-[4.5rem] items-center justify-between gap-2 px-3 sm:px-5 lg:px-7 xl:px-9">
          <div className="flex min-w-0 items-center gap-3">
            <button type="button" aria-label="Abrir menú" aria-controls="acma-menu" aria-expanded={menuAbierto}
              className="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-xl border border-slate-200 bg-white text-primario shadow-sm hover:bg-slate-50 lg:hidden"
              onClick={() => setMenuAbierto(true)}>
              <IconoAcma nombre="menu" />
            </button>
            <div className="min-w-0">
              <p className="hidden text-[11px] font-semibold uppercase tracking-[.14em] text-slate-400 sm:block">Plataforma de mantenimiento</p>
              <p className="truncate text-[15px] font-bold text-[#28262b] sm:text-lg">{titulo}</p>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-2 sm:gap-3">
            <div className="hidden rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 xl:flex"><IndicadorConectividad /></div>
            <CampanaNotificaciones />
            <div className="relative">
              <button type="button" aria-label="Opciones de usuario" aria-expanded={perfilAbierto}
                onClick={() => setPerfilAbierto(v => !v)}
                className="flex min-h-11 items-center gap-2 rounded-xl border border-slate-200 bg-white px-2 py-1.5 shadow-sm transition hover:border-slate-300 hover:bg-slate-50">
                <span className="acma-avatar bg-[#f8e7eb] text-[#92203b]">{iniciales || 'AC'}</span>
                <span className="hidden max-w-40 min-w-0 text-left xl:block">
                  <span className="block truncate text-xs font-bold text-slate-800">{usuario.nombre}</span>
                  <span className="block truncate text-[11px] text-slate-500">{NOMBRE_ROL[usuario.rol]}</span>
                </span>
                <IconoAcma nombre="chevron" className="hidden h-4 w-4 text-slate-400 sm:block" />
              </button>
              {perfilAbierto && (
                <div className="absolute right-0 top-[calc(100%+10px)] z-40 w-56 rounded-2xl border border-slate-200 bg-white p-2 shadow-[0_22px_50px_rgba(15,23,42,.16)]">
                  <div className="border-b border-slate-100 px-3 py-2">
                    <p className="truncate text-sm font-semibold text-slate-900">{usuario.nombre}</p>
                    <p className="truncate text-xs text-slate-500">{NOMBRE_ROL[usuario.rol]}</p>
                  </div>
                  <NavLink to="/seguridad" className="acma-perfil-opcion" onClick={() => setPerfilAbierto(false)}>
                    <IconoAcma nombre="seguridad" className="h-[18px] w-[18px]" /> Mi seguridad
                  </NavLink>
                  <button type="button" onClick={() => { setPerfilAbierto(false); void cerrarSesion() }}
                    className="acma-perfil-opcion w-full text-left text-red-700">
                    <IconoAcma nombre="salir" className="h-[18px] w-[18px]" /> Cerrar sesión
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>
        <main id="contenido-acma" className="acma-contenido mx-auto w-full min-w-0 max-w-[1480px] flex-1 px-3 pb-24 pt-5 sm:px-5 sm:pt-7 lg:px-7 xl:px-9 lg:pb-10">
          <Outlet />
        </main>
      </div>

      <TestBotAcma />

      <nav aria-label="Accesos rápidos" className="acma-barra-movil fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 lg:hidden">
        <NavLink to="/" end className={({ isActive }) => `acma-acceso-rapido ${isActive ? 'acma-acceso-activo' : ''}`}>
          <IconoAcma nombre="inicio" /><span>Inicio</span>
        </NavLink>
        <button type="button" onClick={() => setMenuAbierto(true)}
          aria-label="Mostrar módulos" className={`acma-acceso-rapido ${menuAbierto ? 'acma-acceso-activo' : ''}`}>
          <IconoAcma nombre="cuadrícula" /><span>Módulos</span>
        </button>
        <NavLink to="/notificaciones" className={({ isActive }) => `acma-acceso-rapido ${isActive ? 'acma-acceso-activo' : ''}`}>
          <IconoAcma nombre="campana" /><span>Avisos</span>
        </NavLink>
        <NavLink to="/seguridad" className={({ isActive }) => `acma-acceso-rapido ${isActive ? 'acma-acceso-activo' : ''}`}>
          <IconoAcma nombre="seguridad" /><span>Seguridad</span>
        </NavLink>
      </nav>
    </div>
  )
}
