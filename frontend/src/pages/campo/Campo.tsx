import { useAuth } from '../../contexts/AuthContext'
import { InicioOperador } from './operador/InicioOperador'
import { MisFolios } from './tecnico/MisFolios'

/** Entrada de la app de campo (mismo bundle PWA): operador y Admin UN → app del operador; técnico → app del técnico. */
export function Campo() {
  const { usuario } = useAuth()
  if (!usuario) return null
  if (usuario.rol === 'tecnico') return <MisFolios />
  if (usuario.rol === 'operador' || usuario.rol === 'admin_un' || usuario.rol === 'superadmin') return <InicioOperador />
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-8 text-center">
      <h1 className="text-lg font-semibold text-slate-900">App de campo</h1>
      <p className="mt-2 text-sm text-slate-600">Está pensada para operadores, administradores de UN y técnicos. Tu rol opera los folios desde el módulo Folios.</p>
    </div>
  )
}
