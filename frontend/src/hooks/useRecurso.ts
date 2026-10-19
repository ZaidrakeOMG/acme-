import { useCallback, useEffect, useState } from 'react'
import { api, mensajeDeError } from '../services/api'

/** Carga un recurso GET y expone recargar(); el error ya viene como texto listo para mostrar. */
export function useRecurso<T>(ruta: string | null, params?: Record<string, string | undefined>) {
  const [datos, setDatos] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(false)
  const clave = JSON.stringify(params ?? {})

  const recargar = useCallback(async () => {
    if (!ruta) return
    setCargando(true)
    setError(null)
    try {
      setDatos(await api<T>(ruta, { params: JSON.parse(clave) as Record<string, string> }))
    } catch (e) {
      setError(mensajeDeError(e))
    } finally {
      setCargando(false)
    }
  }, [ruta, clave])

  useEffect(() => {
    void recargar()
  }, [recargar])

  return { datos, error, cargando, recargar }
}
