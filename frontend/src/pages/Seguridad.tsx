import { useState } from 'react'
import { Aviso, Boton, Campo, Encabezado, Tarjeta } from '../components/ui'
import { useAuth } from '../contexts/AuthContext'
import { api, mensajeDeError } from '../services/api'
import type { MfaSetupSalida, MfaVerificarSalida } from '../types/api'

/** Enrolamiento MFA voluntario, regeneración de códigos y cambio de contraseña. */
export function Seguridad() {
  const { usuario, recargarPerfil } = useAuth()
  const [setup, setSetup] = useState<MfaSetupSalida | null>(null)
  const [codigo, setCodigo] = useState('')
  const [codigos, setCodigos] = useState<string[] | null>(null)
  const [mensaje, setMensaje] = useState<{ tipo: 'error' | 'exito'; texto: string } | null>(null)
  const [actual, setActual] = useState('')
  const [nueva, setNueva] = useState('')
  if (!usuario) return null

  async function ejecutar(accion: () => Promise<void>) {
    setMensaje(null)
    try {
      await accion()
    } catch (e) {
      setMensaje({ tipo: 'error', texto: mensajeDeError(e) })
    }
  }

  return (
    <div className="space-y-6">
      <Encabezado titulo="Mi seguridad" descripcion="Verificación en dos pasos y contraseña." />
      {mensaje && <Aviso tipo={mensaje.tipo}>{mensaje.texto}</Aviso>}

      <Tarjeta titulo="Verificación en dos pasos (TOTP)">
        {codigos ? (
          <div className="space-y-3">
            <Aviso tipo="info">Guarda estos códigos de recuperación; se muestran una sola vez.</Aviso>
            <ul aria-label="Códigos de recuperación" className="grid grid-cols-2 gap-2 rounded-lg bg-slate-50 p-4 font-mono text-sm sm:grid-cols-5">
              {codigos.map((c) => <li key={c}>{c}</li>)}
            </ul>
            <Boton variante="secundario" onClick={() => setCodigos(null)}>Listo</Boton>
          </div>
        ) : usuario.mfa_habilitado ? (
          <div className="space-y-3">
            <p className="text-sm text-slate-600">MFA activo{usuario.mfa_obligatorio ? ' (obligatorio para tu rol)' : ''}.</p>
            <div className="flex max-w-md items-end gap-2">
              <Campo etiqueta="Código actual de la app" inputMode="numeric" value={codigo} onChange={(e) => setCodigo(e.target.value)} />
              <Boton variante="secundario" onClick={() => void ejecutar(async () => {
                const r = await api<{ codigos_recuperacion: string[] }>('/auth/mfa/codigos-recuperacion', { metodo: 'POST', cuerpo: { codigo } })
                setCodigos(r.codigos_recuperacion)
                setCodigo('')
              })}>Nuevos códigos</Boton>
              {!usuario.mfa_obligatorio && (
                <Boton variante="peligro" onClick={() => void ejecutar(async () => {
                  await api('/auth/mfa/disable', { metodo: 'POST', cuerpo: { codigo } })
                  setCodigo('')
                  await recargarPerfil()
                  setMensaje({ tipo: 'exito', texto: 'MFA deshabilitado' })
                })}>Deshabilitar</Boton>
              )}
            </div>
          </div>
        ) : setup ? (
          <div className="space-y-3">
            <p className="text-sm text-slate-600">Escanea el código con tu app autenticadora y escribe el código generado.</p>
            <img src={setup.qr_svg} alt="Código QR para la app autenticadora" className="h-44 w-44" />
            <p className="text-xs text-slate-500">Clave manual: <code className="select-all font-mono">{setup.secreto}</code></p>
            <div className="flex max-w-sm items-end gap-2">
              <Campo etiqueta="Código" inputMode="numeric" value={codigo} onChange={(e) => setCodigo(e.target.value)} />
              <Boton onClick={() => void ejecutar(async () => {
                const r = await api<MfaVerificarSalida>('/auth/mfa/verify', { metodo: 'POST', cuerpo: { codigo } })
                setCodigos(r.codigos_recuperacion)
                setSetup(null)
                setCodigo('')
                await recargarPerfil()
              })}>Activar</Boton>
            </div>
          </div>
        ) : (
          <Boton onClick={() => void ejecutar(async () => setSetup(await api<MfaSetupSalida>('/auth/mfa/setup', { metodo: 'POST', cuerpo: {} })))}>
            Activar MFA
          </Boton>
        )}
      </Tarjeta>

      <Tarjeta titulo="Cambiar contraseña">
        <form
          className="grid max-w-md gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            void ejecutar(async () => {
              await api('/auth/cambiar-contrasena', { metodo: 'POST', cuerpo: { actual, nueva } })
              setActual('')
              setNueva('')
              setMensaje({ tipo: 'exito', texto: 'Contraseña actualizada' })
            })
          }}
        >
          <Campo etiqueta="Contraseña actual" type="password" autoComplete="current-password" value={actual} onChange={(e) => setActual(e.target.value)} />
          <Campo etiqueta="Nueva contraseña (10+ caracteres, mayúscula, minúscula, número y símbolo)" type="password" autoComplete="new-password" value={nueva} onChange={(e) => setNueva(e.target.value)} />
          <Boton type="submit">Actualizar</Boton>
        </form>
      </Tarjeta>
    </div>
  )
}
