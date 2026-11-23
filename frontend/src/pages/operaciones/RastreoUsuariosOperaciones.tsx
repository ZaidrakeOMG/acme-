import { Component, lazy, Suspense, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { Encabezado } from '../../components/ui'
import { NOMBRE_ROL } from '../../config/modulos'
import { mensajeDeError } from '../../services/api'
import { listarUsuariosRastreo, type UsuarioRastreable } from '../../services/rastreoUsuarios'
import type { Rol } from '../../types/api'

const MapaUsuarios = lazy(() => import('./MapaRastreoUsuarios'))
const CADA_MS = 10000

/** Si el proveedor de mapas falla, el listado de usuarios debe seguir funcionando. */
class ProteccionMapa extends Component<{ children: ReactNode }, { error: boolean }> {
  state = { error: false }
  static getDerivedStateFromError() { return { error: true } }
  render() {
    if (this.state.error) return (
      <p role="status" className="rounded-xl bg-slate-50 p-5 text-sm text-slate-600">
        El mapa no está disponible. Puedes seguir consultando usuarios y estados GPS en la lista.
      </p>
    )
    return this.props.children
  }
}

/** Operaciones: SOLAMENTE rastreo de personas, independientemente de otros módulos. */
export function RastreoUsuariosOperaciones() {
  const [usuarios, setUsuarios] = useState<UsuarioRastreable[]>([])
  const [seleccionado, setSeleccionado] = useState<string | null>(null)
  const [busqueda, setBusqueda] = useState('')
  const [filtro, setFiltro] = useState<'todos' | 'con_gps' | 'sin_gps'>('todos')
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actualizado, setActualizado] = useState<Date | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)

  const actualizar = useCallback(async () => {
    try {
      const r = await listarUsuariosRastreo()
      setUsuarios(r)
      setActualizado(new Date())
      setError(null)
    } catch (e) {
      setError('No se pudo actualizar el listado de usuarios: ' + mensajeDeError(e))
    } finally { setCargando(false) }
  }, [])

  useEffect(() => {
    void actualizar()
    const intervalo = setInterval(() => { if (!document.hidden) void actualizar() }, CADA_MS)
    const alVolver = () => { if (!document.hidden) void actualizar() }
    document.addEventListener('visibilitychange', alVolver)
    return () => {
      clearInterval(intervalo)
      document.removeEventListener('visibilitychange', alVolver)
    }
  }, [actualizar])

  const visibles = useMemo(() => usuarios.filter(u => {
    if (filtro === 'con_gps' && !u.gps_activo) return false
    if (filtro === 'sin_gps' && u.gps_activo) return false
    const q = busqueda.trim().toLocaleLowerCase('es-MX')
    return !q || (u.usuario_nombre + ' ' + u.correo + ' ' + u.rol).toLocaleLowerCase('es-MX').includes(q)
  }), [usuarios, filtro, busqueda])

  const compartiendo = usuarios.filter(u => u.gps_activo).length
  const elegido = usuarios.find(u => u.usuario_id === seleccionado) ?? null

  function rastrear(id: string) {
    setSeleccionado(id)
    const u = usuarios.find(p => p.usuario_id === id)
    if (!u) return
    setAviso(u.gps_activo
      ? 'Siguiendo la última ubicación GPS compartida por ' + u.usuario_nombre + '. Se actualiza automáticamente.'
      : u.usuario_nombre + ' tiene su cuenta activa, pero todavía no comparte su GPS. Debe abrir ACMA en su dispositivo y aceptar el permiso de ubicación.')
  }

  return (
    <div className="space-y-5" data-testid="rastreo-operaciones-usuarios">
      <Encabezado titulo="Rastreo de usuarios en tiempo real"
        descripcion="Visualiza las cuentas activas de tu organización. La ubicación solo aparece cuando la persona la comparte desde su dispositivo." />

      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <p className="text-sm text-slate-500">Usuarios activos</p>
          <p className="mt-1 text-3xl font-bold tabular-nums text-slate-900">{usuarios.length}</p>
          <p className="mt-1 text-xs text-slate-500">Cuenta habilitada, no necesariamente conectada</p>
        </div>
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4">
          <p className="text-sm text-emerald-900">Compartiendo GPS</p>
          <p className="mt-1 text-3xl font-bold tabular-nums text-emerald-800">{compartiendo}</p>
          <p className="mt-1 text-xs text-emerald-800">Posición recibida hace menos de 90 segundos</p>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <p className="text-sm text-slate-500">Sin ubicación disponible</p>
          <p className="mt-1 text-3xl font-bold tabular-nums text-slate-700">{usuarios.length - compartiendo}</p>
          <p className="mt-1 text-xs text-slate-500">Permiso sin activar, sin señal o aplicación cerrada</p>
        </div>
      </div>

      {error && (
        <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
          {error} <button type="button" className="ml-2 underline" onClick={() => void actualizar()}>Reintentar</button>
        </div>
      )}

      <section className="grid gap-4 xl:grid-cols-[minmax(18rem,25rem)_minmax(0,1fr)]" data-testid="panel-rastreo-usuarios">
        <div className="min-w-0 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="space-y-3 border-b border-slate-100 p-4">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-lg font-bold text-slate-900">Seleccionar usuario</h2>
              <button className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700"
                type="button" onClick={() => void actualizar()}>Actualizar</button>
            </div>
            <label className="block">
              <span className="sr-only">Buscar usuario</span>
              <input type="search" value={busqueda} onChange={e => setBusqueda(e.target.value)}
                placeholder="Buscar nombre o correo…"
                className="w-full rounded-xl border border-slate-300 px-3 py-3 text-sm outline-none focus:border-emerald-700"
                aria-label="Buscar usuario" />
            </label>
            <div className="flex flex-wrap gap-2" aria-label="Filtrar ubicación">
              {([
                ['todos', 'Todos'],
                ['con_gps', 'Con GPS'],
                ['sin_gps', 'Sin GPS'],
              ] as const).map(([valor, etiqueta]) => (
                <button key={valor} type="button" onClick={() => setFiltro(valor)}
                  aria-pressed={filtro === valor}
                  className={'rounded-full px-3 py-2 text-xs font-semibold ' +
                    (filtro === valor ? 'bg-emerald-800 text-white' : 'bg-slate-100 text-slate-700')}>
                  {etiqueta}
                </button>
              ))}
            </div>
          </div>
          <div className="max-h-[560px] space-y-2 overflow-y-auto p-3" role="list">
            {cargando && <p role="status" className="p-4 text-sm text-slate-500">Cargando usuarios…</p>}
            {!cargando && visibles.length === 0 && (
              <p role="status" className="p-4 text-sm text-slate-500">
                {usuarios.length === 0 ? 'No hay cuentas activas visibles para tu organización.' : 'No hay usuarios que coincidan con el filtro.'}
              </p>
            )}
            {visibles.map(u => (
              <article role="listitem" key={u.usuario_id}
                className={'rounded-xl border p-3 transition-colors ' +
                  (seleccionado === u.usuario_id ? 'border-emerald-600 bg-emerald-50' : 'border-slate-200 bg-white')}>
                <div className="flex min-w-0 items-start justify-between gap-2">
                  <div className="min-w-0">
                    <strong className="block truncate text-sm text-slate-900">{u.usuario_nombre}</strong>
                    <p className="truncate text-xs text-slate-500">{u.correo}</p>
                    <p className="mt-1 text-xs text-slate-600">{NOMBRE_ROL[u.rol as Rol] ?? u.rol}</p>
                  </div>
                  <span className={'shrink-0 rounded-full px-2 py-1 text-[11px] font-semibold ' +
                    (u.gps_activo ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-100 text-slate-600')}>
                    {u.gps_activo ? 'GPS compartido' : 'Sin GPS'}
                  </span>
                </div>
                <div className="mt-3 flex items-center justify-between gap-2">
                  <span className="text-[11px] text-slate-500">Cuenta activa</span>
                  <button type="button" onClick={() => rastrear(u.usuario_id)}
                    className="min-h-10 rounded-lg bg-emerald-800 px-3 py-2 text-xs font-bold text-white hover:bg-emerald-700">
                    Rastrear usuario
                  </button>
                </div>
              </article>
            ))}
          </div>
        </div>

        <div className="min-w-0 space-y-3">
          <div className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2 px-1">
              <h2 className="font-bold text-slate-900">Ubicación de usuarios</h2>
              <span className="text-xs text-slate-500">
                {actualizado ? 'Actualizado: ' + actualizado.toLocaleTimeString() : 'Sin actualizar'}
              </span>
            </div>
            <ProteccionMapa>
              <Suspense fallback={<div className="h-[380px] animate-pulse rounded-xl bg-slate-100" role="status">Cargando mapa…</div>}>
                <MapaUsuarios usuarios={usuarios} seleccionadoId={seleccionado}
                  alSeleccionar={rastrear} />
              </Suspense>
            </ProteccionMapa>
          </div>
          {elegido && (
            <div className="rounded-2xl border border-emerald-200 bg-white p-4 shadow-sm"
              data-testid="usuario-rastreado">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="font-bold text-slate-900">{elegido.usuario_nombre}</h3>
                <button type="button" onClick={() => { setSeleccionado(null); setAviso(null) }}
                  className="rounded-lg border px-3 py-2 text-xs">Dejar de seguir en el mapa</button>
              </div>
              {elegido.gps_activo && elegido.lat != null && elegido.lng != null ? (
                <>
                  <p className="mt-2 text-sm font-semibold text-emerald-700">Ubicación compartida en tiempo real</p>
                  <p className="mt-1 text-xs text-slate-600">
                    {elegido.dispositivo ?? 'Dispositivo'} · última señal: {' '}
                    {elegido.ultima_at ? new Date(elegido.ultima_at).toLocaleString() : 'sin fecha'}
                    {elegido.precision_m != null && ' · precisión aprox. ' + Math.round(elegido.precision_m) + ' m'}
                  </p>
                </>
              ) : (
                <p className="mt-2 text-sm text-amber-800">
                  Cuenta activa, GPS sin autorizar o sin señal reciente. No se inventa una ubicación.
                  El usuario debe permitir el acceso desde ACMA en su propio dispositivo.
                </p>
              )}
            </div>
          )}
          {aviso && <p role="status" className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">{aviso}</p>}
          <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-600">
            Cada persona decide compartir su ubicación en ACMA. No se puede encender su GPS a distancia.
            Si eres usuario, puedes <Link className="font-semibold text-emerald-800 underline" to="/mi-ubicacion">
              activar tu ubicación desde aquí</Link>. Las posiciones se actualizan aproximadamente cada 10–15 segundos
            mientras el dispositivo mantiene la aplicación visible.
          </div>
        </div>
      </section>
    </div>
  )
}
