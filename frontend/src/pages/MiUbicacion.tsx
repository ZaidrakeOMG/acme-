/** Página del usuario, disponible en PC, Android e iPhone.
 * El proveedor del AppShell conserva GPS activo al navegar dentro de ACMA.
 */
import { Link } from 'react-router'
import { useAuth } from '../contexts/AuthContext'
import { usarMiUbicacion } from '../contexts/RastreoUsuarioContext'

export function MiUbicacion() {
  const { activo, gpsObligatorio, ocupado, mensaje, error, iniciar, detener } = usarMiUbicacion()
  const { cerrarSesion } = useAuth()
  async function retirarAutorizacion() {
    if (!window.confirm('¿Retirar la autorización y cerrar sesión? El GPS dejará de compartirse.')) return
    await detener()
    await cerrarSesion()
  }
  return (
    <div className="mx-auto max-w-2xl space-y-5" data-testid="mi-ubicacion">
      <header>
        <h1 className="text-2xl font-bold text-slate-900">Compartir mi ubicación</h1>
        <p className="mt-2 text-slate-600">Actívala desde computadora, Android o iPhone.
          No necesitas tener ningún folio asignado.</p>
      </header>
      <section className="rounded-2xl border border-sky-200 bg-white p-5 shadow-sm">
        <h2 className="font-semibold text-slate-900">Mi GPS en tiempo real</h2>
        <p className="mt-2 text-sm text-slate-600">
          Al activarlo, el personal autorizado de tu organización podrá ver tu última posición
          en Operaciones. Solo se guarda la ubicación más reciente; no se registra ningún recorrido.
          Puedes navegar por otras pantallas de ACMA y el rastreo continuará mientras esta pestaña
          permanezca visible. {gpsObligatorio ? 'Para usar los módulos de técnico, la ubicación debe estar activa.' : 'Puedes detener el envío desde esta pantalla.'}
          Si dejas de enviar GPS, tu posición desaparecerá del mapa después de 90 segundos.
        </p>
        <p role="status" className="mt-4 text-sm font-semibold text-slate-700">{mensaje}</p>
        {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
        {activo
          ? gpsObligatorio ? <div className="mt-4 space-y-3">
              <p className="rounded-xl bg-emerald-50 p-3 text-sm font-semibold text-emerald-800">GPS activo · autorización guardada</p>
              <button type="button" onClick={() => void retirarAutorizacion()} className="text-sm text-slate-600 underline">Retirar autorización y cerrar sesión</button>
            </div> : <button type="button" onClick={() => void detener()}
              className="mt-4 min-h-12 w-full rounded-xl bg-rose-700 px-4 py-2 font-semibold text-white">
              Dejar de compartir mi ubicación
            </button>
          : <button type="button" disabled={ocupado} onClick={() => void iniciar()}
              className="mt-4 min-h-12 w-full rounded-xl bg-sky-800 px-4 py-2 font-semibold text-white disabled:opacity-50">
              {ocupado ? 'Activando…' : 'Activar mi ubicación'}
            </button>}
      </section>
      <p className="text-sm text-slate-500">
        En PC la ubicación depende de Windows/macOS y del navegador: puede ser aproximada.
        En Android e iPhone también debes permitir la ubicación del sistema. No se garantiza
        rastreo al bloquear el teléfono, cerrar ACMA o dejar la pestaña en segundo plano.
      </p>
      <Link to="/" className="inline-block text-sm font-semibold text-primario underline">Volver al inicio</Link>
    </div>
  )
}
