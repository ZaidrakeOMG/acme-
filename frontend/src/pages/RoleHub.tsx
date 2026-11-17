import { Link } from 'react-router'
import { modulosDe, NOMBRE_ROL, type Modulo } from '../config/modulos'
import { useAuth } from '../contexts/AuthContext'

/** Inicio por rol: tarjetas de los módulos que el rol puede ver (§5). */
export function RoleHub() {
  const { usuario } = useAuth()
  if (!usuario) return null
  const modulos = modulosDe(usuario.rol)

  return (
    <div>
      <div className="mb-5 sm:mb-8">
        <p className="text-sm text-slate-500">{NOMBRE_ROL[usuario.rol]}</p>
        <h1 className="break-words text-xl font-semibold text-slate-900 sm:text-2xl">Hola, {usuario.nombre.split(' ')[0]}</h1>
      </div>

      {usuario.mfa_obligatorio && !usuario.mfa_habilitado && (
        <div className="mb-6 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Tu rol requiere verificación en dos pasos. <Link to="/seguridad" className="font-medium underline">Actívala aquí</Link>.
        </div>
      )}

      <section aria-labelledby="modulos">
        <h2 id="modulos" className="mb-3 text-sm font-medium uppercase tracking-wide text-slate-500">Tus módulos</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4 lg:grid-cols-3">
          {modulos.map((m) => (
            <TarjetaModulo key={m.id} modulo={m} />
          ))}
        </div>
      </section>
    </div>
  )
}

function TarjetaModulo({ modulo }: { modulo: Modulo }) {
  const contenido = (
    <>
      <div className="mb-2 flex items-start justify-between gap-2">
        <h3 className="font-semibold text-slate-900">{modulo.nombre}</h3>
        <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-acento" />
      </div>
      <p className="text-sm text-slate-600">{modulo.descripcion}</p>
    </>
  )
  return (
    <Link
      to={modulo.ruta}
      data-testid={`modulo-${modulo.id}`}
      className="block min-w-0 rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition sm:p-5 hover:-translate-y-0.5 hover:border-primario/40 hover:shadow"
    >
      {contenido}
    </Link>
  )
}
