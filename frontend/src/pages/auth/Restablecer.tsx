import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useSearchParams } from 'react-router'
import { z } from 'zod'
import { Aviso, Boton, Campo } from '../../components/ui'
import { api, mensajeDeError } from '../../services/api'
import { MarcoAuth, REGLAS_CONTRASENA } from './Marco'

/**
 * §6.9.5 · P11a: pantalla del enlace que llega por correo (`/restablecer?token=…`). El token sirve una sola vez,
 * vence en 30 minutos y al usarse cierra todas las sesiones abiertas de esa cuenta.
 */
const esquema = z
  .object({
    nueva: z.string().min(10, 'La contraseña necesita al menos 10 caracteres'),
    confirmacion: z.string().min(1, 'Repite la contraseña'),
  })
  .refine((d) => d.nueva === d.confirmacion, { path: ['confirmacion'], message: 'Las dos contraseñas no coinciden' })
type Datos = z.infer<typeof esquema>

export function Restablecer() {
  const [parametros] = useSearchParams()
  const token = parametros.get('token') ?? ''
  const [error, setError] = useState<string | null>(null)
  const [listo, setListo] = useState(false)
  const { register, handleSubmit, formState } = useForm<Datos>({ resolver: zodResolver(esquema) })

  const enviar = handleSubmit(async ({ nueva }) => {
    setError(null)
    try {
      await api('/auth/restablecer/confirmar', { metodo: 'POST', cuerpo: { token, nueva }, sinAuth: true })
      setListo(true)
    } catch (e) {
      setError(mensajeDeError(e))
    }
  })

  if (!token) {
    return (
      <MarcoAuth>
        <div className="space-y-4">
          <h1 className="text-xl font-semibold text-slate-900">Enlace incompleto</h1>
          <Aviso>Este enlace no trae el código de restablecimiento. Pide uno nuevo desde la pantalla de acceso.</Aviso>
          <Link to="/" className="block text-center text-sm text-primario hover:underline">
            Ir a iniciar sesión
          </Link>
        </div>
      </MarcoAuth>
    )
  }

  if (listo) {
    return (
      <MarcoAuth>
        <div className="space-y-4">
          <h1 className="text-xl font-semibold text-slate-900">Contraseña restablecida</h1>
          <Aviso tipo="exito">Ya puedes entrar con tu contraseña nueva. Las sesiones que tenías abiertas se cerraron.</Aviso>
          <Link to="/" className="block text-center text-sm text-primario hover:underline">
            Iniciar sesión
          </Link>
        </div>
      </MarcoAuth>
    )
  }

  return (
    <MarcoAuth error={error}>
      <form onSubmit={enviar} className="space-y-4" noValidate>
        <h1 className="text-xl font-semibold text-slate-900">Elige tu contraseña nueva</h1>
        <p className="text-sm text-slate-600">El enlace sirve una sola vez y vence 30 minutos después de pedirlo.</p>
        <Campo etiqueta="Contraseña nueva" type="password" autoComplete="new-password" autoFocus error={formState.errors.nueva?.message} {...register('nueva')} />
        <Campo etiqueta="Repite la contraseña" type="password" autoComplete="new-password" error={formState.errors.confirmacion?.message} {...register('confirmacion')} />
        <p className="text-xs text-slate-500">{REGLAS_CONTRASENA}</p>
        <Boton type="submit" className="w-full" disabled={formState.isSubmitting}>
          {formState.isSubmitting ? 'Guardando…' : 'Restablecer contraseña'}
        </Boton>
        <Link to="/" className="block text-center text-sm text-slate-500 hover:underline">
          Volver a iniciar sesión
        </Link>
      </form>
    </MarcoAuth>
  )
}
