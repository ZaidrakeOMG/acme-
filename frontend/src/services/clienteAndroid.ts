import { useEffect, useState } from 'react'

declare global {
  interface Window { __ACMA_ANDROID__?: boolean }
}

/**
 * Solo el contenedor Flutter/Android avisa al frontend que está embebido.
 * Es una marca de interfaz, NO un mecanismo de autorización.
 * Todas las operaciones con GPS requieren permisos de backend.
 */
export function esAppAndroid(): boolean {
  return typeof window !== 'undefined' && window.__ACMA_ANDROID__ === true
}

export function useAppAndroid(): boolean {
  const [android, setAndroid] = useState(esAppAndroid)
  useEffect(() => {
    const actualizar = () => setAndroid(esAppAndroid())
    window.addEventListener('acma-android-ready', actualizar)
    actualizar()
    return () => window.removeEventListener('acma-android-ready', actualizar)
  }, [])
  return android
}
