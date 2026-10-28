import { Link } from 'react-router'
import { useConexion } from '../hooks/useConexion'

/** Indicador global: en línea / sin conexión / sincronizando N pendientes / N con error (enlaza a la pantalla de pendientes). */
export function IndicadorConectividad() {
  const { enLinea, sincronizando, pendientes, errores } = useConexion()
  let texto = 'En línea'
  let tono = 'bg-green-100 text-green-800'
  if (!enLinea) {
    texto = pendientes ? `Sin conexión · ${pendientes} pendiente(s)` : 'Sin conexión'
    tono = 'bg-amber-100 text-amber-900'
  } else if (sincronizando) {
    texto = `Sincronizando ${pendientes} pendiente(s)…`
    tono = 'bg-sky-100 text-sky-900'
  } else if (errores) {
    texto = `${errores} con error`
    tono = 'bg-red-100 text-red-900'
  } else if (pendientes) {
    texto = `${pendientes} pendiente(s)`
    tono = 'bg-amber-100 text-amber-900'
  }
  return (
    <Link to="/sincronizacion" data-testid="indicador-conectividad" aria-live="polite" className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ${tono}`}>
      <span className={`h-2 w-2 rounded-full ${enLinea ? 'bg-current' : 'bg-amber-500'}`} aria-hidden />
      {texto}
    </Link>
  )
}
