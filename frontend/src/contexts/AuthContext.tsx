import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, refrescar, sesion } from '../services/api'
import type { PerfilConTema, Tema, Tokens } from '../types/api'

interface EstadoAuth {
  usuario: PerfilConTema | null
  cargando: boolean
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

  const recargarPerfil = useCallback(async () => {
    const perfil = await api<PerfilConTema>('/auth/yo')
    aplicarTema(perfil.tema)
    setUsuario(perfil)
  }, [])

  const iniciarSesionCon = useCallback(
    async (tokens: Tokens) => {
      sesion.guardar(tokens)
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
    setUsuario(null)
  }, [])

  useEffect(() => {
    sesion.alExpirar(() => {
      sesion.limpiar()
      setUsuario(null)
    })
    // Restaurar sesión con el refresh token guardado.
    ;(async () => {
      try {
        if (sesion.tieneRefresh() && (await refrescar())) await recargarPerfil()
      } catch {
        sesion.limpiar()
      } finally {
        setCargando(false)
      }
    })()
  }, [recargarPerfil])

  const valor = useMemo(
    () => ({ usuario, cargando, iniciarSesionCon, cerrarSesion, recargarPerfil }),
    [usuario, cargando, iniciarSesionCon, cerrarSesion, recargarPerfil],
  )
  return <AuthContext.Provider value={valor}>{children}</AuthContext.Provider>
}

export function useAuth(): EstadoAuth {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth debe usarse dentro de AuthProvider')
  return ctx
}
