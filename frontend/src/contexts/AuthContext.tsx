import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, ErrorAPI, refrescar, sesion } from '../services/api'
import { registrarPush } from '../services/campo'
import { syncEngine } from '../services/syncEngine'
import type { PerfilConTema, Tema, Tokens } from '../types/api'

const ROLES_CAMPO = new Set(['operador', 'tecnico', 'admin_un'])

interface EstadoAuth {
  usuario: PerfilConTema | null
  cargando: boolean
  esperandoConexion: boolean
  reintentarSesion: () => Promise<void>
  iniciarSesionCon: (tokens: Tokens) => Promise<void>
  cerrarSesion: () => Promise<void>
  recargarPerfil: () => Promise<void>
}

const AuthContext = createContext<EstadoAuth | null>(null)

export function aplicarTema(tema: Pick<Tema, 'color_primario' | 'color_acento'>) {
  const raiz = document.documentElement.style
  raiz.setProperty('--color-primario', tema.color_primario)
  raiz.setProperty('--color-acento', tema.color_acento)
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [usuario, setUsuario] = useState<PerfilConTema | null>(null)
  const [cargando, setCargando] = useState(true)
  const [esperandoConexion, setEsperandoConexion] = useState(false)
  const usuarioRestaurado = useRef(false)

  const recargarPerfil = useCallback(async () => {
    const perfil = await api<PerfilConTema>('/auth/yo')
    aplicarTema(perfil.tema)
    setUsuario(perfil)
    usuarioRestaurado.current = true
    setEsperandoConexion(false)
    if (ROLES_CAMPO.has(perfil.rol)) {
      // P05: paquete de catálogos en segundo plano y suscripción push (sin bloquear el inicio de sesión).
      void syncEngine.refrescarCatalogos().catch(() => undefined)
      void registrarPush()
    }
  }, [])

  const iniciarSesionCon = useCallback(
    async (tokens: Tokens) => {
      sesion.guardar(tokens)
      setEsperandoConexion(false)
      await recargarPerfil()
    },
    [recargarPerfil],
  )

  const cerrarSesion = useCallback(async () => {
    try {
      await api('/auth/logout', { metodo: 'POST' })
    } catch {
      /* la sesión local se limpia de todos modos */
    }
    sesion.limpiar()
    usuarioRestaurado.current = false
    setEsperandoConexion(false)
    setUsuario(null)
  }, [])

  const reintentarSesion = useCallback(async () => {
    if (!sesion.tieneRefresh()) {
      usuarioRestaurado.current = false
      setUsuario(null)
      setEsperandoConexion(false)
      setCargando(false)
      return
    }
    setCargando(true)
    try {
      if (await refrescar()) {
        await recargarPerfil()
        setEsperandoConexion(false)
      } else if (sesion.tieneRefresh()) {
        // Offline, timeout o error 5xx: no mostrar login ni pedir contraseña.
        setEsperandoConexion(true)
      } else {
        usuarioRestaurado.current = false
        setUsuario(null)
        setEsperandoConexion(false)
      }
    } catch (error) {
      if (error instanceof ErrorAPI && (error.estado === 401 || error.estado === 403)) {
        sesion.limpiar()
        usuarioRestaurado.current = false
        setUsuario(null)
        setEsperandoConexion(false)
      } else {
        // Conserva la cookie httpOnly y la marca al perder Internet en iPhone/Android.
        setEsperandoConexion(true)
      }
    } finally {
      setCargando(false)
    }
  }, [recargarPerfil])

  useEffect(() => {
    sesion.alExpirar(() => {
      sesion.limpiar()
      usuarioRestaurado.current = false
      setEsperandoConexion(false)
      setUsuario(null)
    })
    void reintentarSesion()

    const alRecuperarConexion = () => {
      if (!sesion.tieneRefresh()) return
      if (usuarioRestaurado.current) {
        // iPhone/Android pueden reanudar después de horas en segundo plano.
        // Renueva el acceso vencido sin recargar la WebView ni perder formularios.
        if (sesion.accesoPorVencer()) void refrescar()
      } else {
        void reintentarSesion()
      }
    }
    const alVolverVisible = () => {
      if (document.visibilityState === 'visible') alRecuperarConexion()
    }
    const enOtraPestana = (evento: StorageEvent) => {
      if (evento.key === 'acma.sesion' && evento.newValue !== '1') {
        // Otra pestaña cerró sesión: no reabrir el perfil de forma accidental.
        sesion.limpiar(false)
        usuarioRestaurado.current = false
        setEsperandoConexion(false)
        setUsuario(null)
      }
    }
    window.addEventListener('pageshow', alRecuperarConexion)
    window.addEventListener('focus', alRecuperarConexion)
    window.addEventListener('online', alRecuperarConexion)
    window.addEventListener('acma:resume', alRecuperarConexion)
    window.addEventListener('storage', enOtraPestana)
    document.addEventListener('visibilitychange', alVolverVisible)
    return () => {
      window.removeEventListener('pageshow', alRecuperarConexion)
      window.removeEventListener('focus', alRecuperarConexion)
      window.removeEventListener('online', alRecuperarConexion)
      window.removeEventListener('acma:resume', alRecuperarConexion)
      window.removeEventListener('storage', enOtraPestana)
      document.removeEventListener('visibilitychange', alVolverVisible)
    }
  }, [reintentarSesion])

  const valor = useMemo(
    () => ({ usuario, cargando, esperandoConexion, reintentarSesion, iniciarSesionCon, cerrarSesion, recargarPerfil }),
    [usuario, cargando, esperandoConexion, reintentarSesion, iniciarSesionCon, cerrarSesion, recargarPerfil],
  )
  return <AuthContext.Provider value={valor}>{children}</AuthContext.Provider>
}

export function useAuth(): EstadoAuth {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth debe usarse dentro de AuthProvider')
  return ctx
}
