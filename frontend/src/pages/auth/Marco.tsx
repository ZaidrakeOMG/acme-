import type { ReactNode } from 'react'
import { IconoAcma } from '../../components/IconosAcma'
import { Aviso } from '../../components/ui'

/** Marco coherente en web y Android para login, MFA y recuperación. Sin tocar el flujo de sesión. */
export function MarcoAuth({ error, children }: { error?: string | null; children: ReactNode }) {
  return (
    <div className="relative flex min-h-dvh items-center justify-center overflow-hidden bg-[#faf7f9] px-4 py-7 sm:px-6 lg:px-12">
      <div aria-hidden="true" className="pointer-events-none absolute -left-40 -top-40 h-80 w-80 rounded-full bg-[#f4e0e6] blur-3xl" />
      <div aria-hidden="true" className="pointer-events-none absolute -bottom-36 -right-36 h-80 w-80 rounded-full bg-[#f8e5eb] blur-3xl" />
      <div className="relative grid w-full max-w-5xl overflow-hidden rounded-[1.75rem] border border-slate-200/80 bg-white shadow-[0_24px_75px_rgba(25,50,85,.1)] lg:min-h-[640px] lg:grid-cols-[.92fr_1fr]">
        <aside className="relative hidden flex-col justify-between overflow-hidden bg-[linear-gradient(143deg,#24242c,#5c2238_65%,#972c4c)] p-10 text-white lg:flex">
          <div aria-hidden="true" className="pointer-events-none absolute -bottom-20 -right-20 h-80 w-80 rounded-full border-[60px] border-white/5" />
          <div className="relative flex items-center gap-3">
            <span className="grid h-14 w-14 place-items-center rounded-2xl border border-white/20 bg-white/10">
              <img src="/icono.svg" alt="" className="h-10 w-10 object-contain" />
            </span>
            <div>
              <p className="text-2xl font-extrabold tracking-[.15em]">ACMA</p>
              <p className="text-xs font-semibold uppercase tracking-[.12em] text-blue-100/60">Gestión empresarial</p>
            </div>
          </div>
          <div className="relative space-y-5">
            <span className="inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-3 py-1.5 text-xs font-semibold text-white/85">
              <IconoAcma nombre="escudo" className="h-4 w-4 text-[#ffc5d2]" /> Entorno de trabajo protegido
            </span>
            <h2 className="text-[2.6rem] font-extrabold leading-[1.14] tracking-tight">
              Todo tu mantenimiento, en un solo lugar.
            </h2>
            <p className="max-w-sm text-base leading-7 text-blue-100/80">
              Organiza folios, equipos y operaciones con herramientas adaptadas a tu equipo.
            </p>
          </div>
          <p className="relative text-xs text-blue-100/55">ACMA · Plataforma de gestión de mantenimiento</p>
        </aside>
        <div className="flex flex-col justify-center px-5 py-8 sm:px-10 sm:py-12 lg:px-12">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <span className="grid h-12 w-12 place-items-center rounded-[.9rem] bg-[#f9e9ed]">
              <img src="/icono.svg" alt="" className="h-9 w-9 object-contain" />
            </span>
            <div>
              <p className="text-xl font-extrabold tracking-[.13em] text-[#96233f]">ACMA</p>
              <p className="text-xs font-semibold text-slate-500">Gestión de mantenimiento</p>
            </div>
          </div>
          <div className="mb-6 hidden items-center gap-2 text-xs font-bold uppercase tracking-[.13em] text-[#aa3655] lg:flex">
            <span className="h-1.5 w-1.5 rounded-full bg-[#cb3c5d]" /> ACCESO A LA PLATAFORMA
          </div>
          <div className="w-full max-w-md">
            {error && <div className="mb-5"><Aviso>{error}</Aviso></div>}
            {children}
          </div>
          <p className="mt-8 flex items-center justify-center gap-2 text-center text-xs text-slate-400">
            <IconoAcma nombre="seguridad" className="h-4 w-4" />
            Acceso privado · Conexión segura
          </p>
        </div>
      </div>
    </div>
  )
}

/** Mismas reglas que el servidor. */
export const REGLAS_CONTRASENA =
  'Al menos 10 caracteres, con mayúscula, minúscula, número y símbolo. No puede repetir ninguna de tus últimas 10 contraseñas.'
