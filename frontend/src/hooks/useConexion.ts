import { useEffect, useState } from 'react'
import { syncEngine, type EstadoSync } from '../services/syncEngine'

/** Estado de conectividad y de la cola de sincronización (en línea / sin conexión / sincronizando N / N con error). */
export function useConexion(): EstadoSync & { procesar: () => Promise<EstadoSync> } {
  const [estado, setEstado] = useState<EstadoSync>({ enLinea: syncEngine.enLinea(), sincronizando: false, pendientes: 0, errores: 0, ultimoSync: null })
  useEffect(() => syncEngine.suscribir(setEstado), [])
  return { ...estado, procesar: () => syncEngine.procesar() }
}
