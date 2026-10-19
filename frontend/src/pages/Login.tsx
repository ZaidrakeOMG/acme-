import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { Aviso, Boton, Campo } from '../components/ui'
import { useAuth } from '../contexts/AuthContext'
import { api, mensajeDeError } from '../services/api'
import type { LoginSalida, MfaSetupSalida, MfaVerificarSalida, Tokens } from '../types/api'

const esquemaCredenciales = z.object({
  email: z.string().trim().email('Ingresa un correo válido'),
  contrasena: z.string().min(1, 'Ingresa tu contraseña'),
})
type Credenciales = z.infer<typeof esquemaCredenciales>

const esquemaCodigo = z.object({
  codigo: z.string().trim().min(6, 'El código tiene al menos 6 caracteres').max(20),
})
type Codigo = z.infer<typeof esquemaCodigo>

type Paso =
  | { tipo: 'credenciales' }
  | { tipo: 'mfa'; tokenMfa: string }
  | { tipo: 'enrolar'; tokenMfa: string; setup: MfaSetupSalida }
  | { tipo: 'codigos'; codigos: string[]; tokens: Tokens }

export function Login() {
  const { iniciarSesionCon } = useAuth()
  const [paso, setPaso] = useState<Paso>({ tipo: 'credenciales' })
  const [error, setError] = useState<string | null>(null)

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
          {paso.tipo === 'credenciales' && <PasoCredenciales setPaso={setPaso} setError={setError} iniciar={iniciarSesionCon} />}
          {paso.tipo === 'mfa' && <PasoVerificar tokenMfa={paso.tokenMfa} setPaso={setPaso} setError={setError} iniciar={iniciarSesionCon} />}
          {paso.tipo === 'enrolar' && <PasoEnrolar paso={paso} setPaso={setPaso} setError={setError} />}
          {paso.tipo === 'codigos' && <PasoCodigos codigos={paso.codigos} alContinuar={() => iniciarSesionCon(paso.tokens)} />}
        </div>
      </div>
    </div>
  )
}

interface PropsPaso {
  setPaso: (p: Paso) => void
  setError: (e: string | null) => void
}

function PasoCredenciales({ setPaso, setError, iniciar }: PropsPaso & { iniciar: (t: Tokens) => Promise<void> }) {
  const { register, handleSubmit, formState } = useForm<Credenciales>({ resolver: zodResolver(esquemaCredenciales) })

  const enviar = handleSubmit(async (datos) => {
    setError(null)
    try {
      const r = await api<LoginSalida>('/auth/login', { metodo: 'POST', cuerpo: { ...datos, dispositivo: navigator.userAgent.slice(0, 200) }, sinAuth: true })
      if (r.tokens) return await iniciar(r.tokens)
      if (r.token_mfa && r.mfa_enrolamiento_requerido) {
        const setup = await api<MfaSetupSalida>('/auth/mfa/setup', { metodo: 'POST', cuerpo: { token_mfa: r.token_mfa }, sinAuth: true })
        return setPaso({ tipo: 'enrolar', tokenMfa: r.token_mfa, setup })
      }
      if (r.token_mfa) setPaso({ tipo: 'mfa', tokenMfa: r.token_mfa })
    } catch (e) {
      setError(mensajeDeError(e))
    }
  })

  return (
    <form onSubmit={enviar} className="space-y-4" noValidate>
      <h1 className="text-xl font-semibold text-slate-900">Iniciar sesión</h1>
      <Campo etiqueta="Correo electrónico" type="email" autoComplete="username" error={formState.errors.email?.message} {...register('email')} />
      <Campo etiqueta="Contraseña" type="password" autoComplete="current-password" error={formState.errors.contrasena?.message} {...register('contrasena')} />
      <Boton type="submit" className="w-full" disabled={formState.isSubmitting}>
        {formState.isSubmitting ? 'Verificando…' : 'Entrar'}
      </Boton>
    </form>
  )
}

function PasoVerificar({ tokenMfa, setPaso, setError, iniciar }: PropsPaso & { tokenMfa: string; iniciar: (t: Tokens) => Promise<void> }) {
  const { register, handleSubmit, formState } = useForm<Codigo>({ resolver: zodResolver(esquemaCodigo) })
  const [recuperacion, setRecuperacion] = useState(false)

  const enviar = handleSubmit(async ({ codigo }) => {
    setError(null)
    try {
      const r = await api<MfaVerificarSalida>('/auth/mfa/verify', { metodo: 'POST', cuerpo: { token_mfa: tokenMfa, codigo }, sinAuth: true })
      if (r.tokens) await iniciar(r.tokens)
    } catch (e) {
      setError(mensajeDeError(e))
    }
  })

  return (
    <form onSubmit={enviar} className="space-y-4" noValidate>
      <h1 className="text-xl font-semibold text-slate-900">Verificación en dos pasos</h1>
      <p className="text-sm text-slate-600">
        {recuperacion ? 'Escribe uno de tus códigos de recuperación. Cada código sirve una sola vez.' : 'Escribe el código de 6 dígitos de tu app autenticadora.'}
      </p>
      <Campo
        etiqueta={recuperacion ? 'Código de recuperación' : 'Código de verificación'}
        inputMode={recuperacion ? 'text' : 'numeric'}
        autoComplete="one-time-code"
        autoFocus
        error={formState.errors.codigo?.message}
        {...register('codigo')}
      />
      <Boton type="submit" className="w-full" disabled={formState.isSubmitting}>
        Verificar
      </Boton>
      <div className="flex justify-between text-sm">
        <button type="button" className="text-primario hover:underline" onClick={() => setRecuperacion((v) => !v)}>
          {recuperacion ? 'Usar código de la app' : 'Usar un código de recuperación'}
        </button>
        <button type="button" className="text-slate-500 hover:underline" onClick={() => setPaso({ tipo: 'credenciales' })}>
          Volver
        </button>
      </div>
    </form>
  )
}

function PasoEnrolar({ paso, setPaso, setError }: PropsPaso & { paso: Extract<Paso, { tipo: 'enrolar' }> }) {
  const { register, handleSubmit, formState } = useForm<Codigo>({ resolver: zodResolver(esquemaCodigo) })

  const enviar = handleSubmit(async ({ codigo }) => {
    setError(null)
    try {
      const r = await api<MfaVerificarSalida>('/auth/mfa/verify', { metodo: 'POST', cuerpo: { token_mfa: paso.tokenMfa, codigo }, sinAuth: true })
      if (r.tokens) setPaso({ tipo: 'codigos', codigos: r.codigos_recuperacion ?? [], tokens: r.tokens })
    } catch (e) {
      setError(mensajeDeError(e))
    }
  })

  return (
    <form onSubmit={enviar} className="space-y-4" noValidate>
      <h1 className="text-xl font-semibold text-slate-900">Activa la verificación en dos pasos</h1>
      <p className="text-sm text-slate-600">
        Tu rol requiere MFA. Escanea el código QR con Google Authenticator, Microsoft Authenticator u otra app TOTP y escribe el código que
        te muestre.
      </p>
      <div className="flex justify-center">
        <img src={paso.setup.qr_svg} alt="Código QR para la app autenticadora" className="h-48 w-48" />
      </div>
      <p className="text-center text-xs text-slate-500">
        ¿No puedes escanear? Clave manual: <code className="select-all break-all font-mono text-slate-800">{paso.setup.secreto}</code>
      </p>
      <Campo etiqueta="Código de verificación" inputMode="numeric" autoComplete="one-time-code" error={formState.errors.codigo?.message} {...register('codigo')} />
      <Boton type="submit" className="w-full" disabled={formState.isSubmitting}>
        Activar y entrar
      </Boton>
    </form>
  )
}

export function PasoCodigos({ codigos, alContinuar }: { codigos: string[]; alContinuar: () => void | Promise<void> }) {
  const [confirmado, setConfirmado] = useState(false)
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-slate-900">Guarda tus códigos de recuperación</h1>
      <Aviso tipo="info">Se muestran una sola vez. Cada código sirve para entrar si pierdes tu teléfono, y solo puede usarse una vez.</Aviso>
      <ul aria-label="Códigos de recuperación" className="grid grid-cols-2 gap-2 rounded-lg bg-slate-50 p-4 font-mono text-sm text-slate-800">
        {codigos.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
      <label className="flex items-center gap-2 text-sm text-slate-700">
        <input type="checkbox" checked={confirmado} onChange={(e) => setConfirmado(e.target.checked)} />
        Ya guardé mis códigos en un lugar seguro
      </label>
      <Boton className="w-full" disabled={!confirmado} onClick={() => void alContinuar()}>
        Continuar
      </Boton>
    </div>
  )
}
