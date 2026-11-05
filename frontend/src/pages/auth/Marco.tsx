import type { ReactNode } from 'react'
import { Aviso } from '../../components/ui'

/** Tarjeta centrada con la marca que comparten las pantallas de acceso (entrar, cambiar y restablecer). P11a. */
export function MarcoAuth({ error, children }: { error?: string | null; children: ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-fondo px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-8 flex items-center justify-center gap-3">
          <img src="/icono.svg" alt="" className="h-12 w-12" />
          <div>
            <p className="text-2xl font-semibold text-primario">ACMA</p>
            <p className="text-sm text-slate-500">Gestión de mantenimiento</p>
          </div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
          {error && (
            <div className="mb-4">
              <Aviso>{error}</Aviso>
            </div>
          )}
          {children}
        </div>
      </div>
    </div>
  )
}

/** Las reglas de §6.9.5, redactadas igual que las valida el servidor, para que nadie adivine qué le falta. */
export const REGLAS_CONTRASENA =
  'Al menos 10 caracteres, con mayúscula, minúscula, número y símbolo. No puede repetir ninguna de tus últimas 10 contraseñas.'
