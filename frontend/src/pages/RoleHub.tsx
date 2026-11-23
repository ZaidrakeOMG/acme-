import { useMemo, useState } from 'react'
import { Link } from 'react-router'
import { modulosDe, NOMBRE_ROL, type GrupoModulo, type Modulo } from '../config/modulos'
import { IconoAcma } from '../components/IconosAcma'
import { useAuth } from '../contexts/AuthContext'

const AREAS: Array<'Todos' | GrupoModulo> = [
  'Todos', 'Operación', 'Seguimiento', 'Administración', 'Finanzas y activos', 'Análisis',
]

/** Inicio real por rol: no se muestran métricas ficticias ni módulos sin permiso. */
export function RoleHub() {
  const { usuario } = useAuth()
  const [buscar, setBuscar] = useState('')
  const [area, setArea] = useState<'Todos' | GrupoModulo>('Todos')
  const modulos = useMemo(() => usuario ? modulosDe(usuario.rol, usuario.modulos_habilitados) : [], [usuario?.rol, usuario?.modulos_habilitados])
  const consulta = buscar.trim().toLocaleLowerCase('es-MX')
  const visibles = modulos.filter(m => (area === 'Todos' || m.grupo === area) &&
    (!consulta || `${m.nombre} ${m.descripcion} ${m.grupo}`.toLocaleLowerCase('es-MX').includes(consulta)))

  if (!usuario) return null
  const disponibles = new Set(modulos.map(m => m.grupo)).size
  const primerNombre = usuario.nombre.split(/\s+/)[0]
  const recomendado = modulos.find(m => m.id === 'folios') ?? modulos.find(m => m.id === 'app_campo') ?? modulos[0]

  return (
    <div className="space-y-8">
      <section className="acma-hero relative isolate overflow-hidden rounded-[1.75rem] px-5 py-7 text-white sm:px-8 sm:py-9 lg:px-10">
        <div className="pointer-events-none absolute -right-12 -top-32 h-80 w-80 rounded-full border-[48px] border-white/5 sm:right-6" aria-hidden="true" />
        <div className="pointer-events-none absolute -bottom-44 right-12 h-72 w-72 rounded-full border-[48px] border-white/5" aria-hidden="true" />
        <div className="relative z-10 grid gap-6 lg:grid-cols-[1fr_auto] lg:items-end">
          <div className="min-w-0">
            <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-3 py-1.5 text-[11px] font-bold uppercase tracking-[.15em] text-white/90">
              <IconoAcma nombre="actividad" className="h-4 w-4 text-[#ffc2d0]" />
              Centro de operaciones
            </div>
            <h1 className="max-w-2xl break-words text-[clamp(1.65rem,4vw,2.7rem)] font-extrabold leading-tight tracking-tight">
              Hola, {primerNombre}
            </h1>
            <p className="mt-3 max-w-xl text-sm leading-6 text-white/80 sm:text-base">
              Gestiona tus operaciones, consulta información y continúa tu trabajo desde un solo lugar.
            </p>
            <div className="mt-6 flex flex-wrap items-center gap-2.5">
              {recomendado && (
                <Link to={recomendado.ruta} className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-white px-4 py-2.5 text-sm font-extrabold text-[#87263d] shadow-[0_8px_22px_rgba(0,0,0,.12)] transition hover:bg-[#fff0f4]">
                  <IconoAcma nombre={recomendado.id} className="h-[18px] w-[18px]" />
                  Ir a {recomendado.nombre}
                  <IconoAcma nombre="flecha" className="h-4 w-4" />
                </Link>
              )}
              <span className="inline-flex min-h-11 items-center rounded-xl border border-white/25 bg-white/10 px-4 text-xs font-semibold text-white/90">
                <IconoAcma nombre="escudo" className="mr-2 h-4 w-4" />
                {NOMBRE_ROL[usuario.rol]}
              </span>
            </div>
          </div>
          <div className="flex gap-3 lg:flex-col">
            <div className="min-w-28 rounded-2xl border border-white/15 bg-white/10 px-4 py-3 backdrop-blur">
              <span className="block text-2xl font-extrabold tabular-nums">{modulos.length}</span>
              <span className="block text-xs text-white/80">Módulos disponibles</span>
            </div>
            <div className="min-w-28 rounded-2xl border border-white/15 bg-white/10 px-4 py-3 backdrop-blur">
              <span className="block text-2xl font-extrabold tabular-nums">{disponibles}</span>
              <span className="block text-xs text-white/80">Áreas de trabajo</span>
            </div>
          </div>
        </div>
      </section>

      {usuario.mfa_obligatorio && !usuario.mfa_habilitado && (
        <div className="flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">
          <IconoAcma nombre="escudo" className="mt-0.5 h-5 w-5" />
          <div>Tu rol requiere verificación en dos pasos. <Link to="/seguridad" className="font-bold underline underline-offset-2">Actívala aquí</Link>.</div>
        </div>
      )}

      <section aria-labelledby="modulos" className="space-y-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="mb-1 text-[11px] font-bold uppercase tracking-[.16em] text-primario">Tu espacio de trabajo</p>
            <h2 id="modulos" className="text-2xl font-extrabold tracking-tight text-[#25272e] sm:text-[1.8rem]">Explora tus módulos</h2>
            <p className="mt-1 text-sm text-slate-500">Herramientas disponibles según tus permisos de acceso.</p>
          </div>
          <span className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600">
            {visibles.length} disponibles
          </span>
        </div>

        <div className="flex flex-col gap-4 rounded-2xl border border-slate-200/80 bg-white p-3 shadow-sm sm:p-4">
          <label className="acma-filtro-busqueda">
            <IconoAcma nombre="buscar" className="h-5 w-5 text-slate-400" />
            <span className="sr-only">Buscar módulos</span>
            <input type="search" value={buscar} onChange={e => setBuscar(e.target.value)}
              placeholder="Buscar herramientas, folios, inventario..."
              className="min-h-10 min-w-0 flex-1 bg-transparent text-sm text-slate-800 outline-none placeholder:text-slate-400" />
          </label>
          <div className="flex gap-2 overflow-x-auto pb-1" role="group" aria-label="Filtrar módulos por área">
            {AREAS.filter(g => g === 'Todos' || modulos.some(m => m.grupo === g)).map(grupo => (
              <button key={grupo} type="button" onClick={() => setArea(grupo)} aria-pressed={area === grupo}
                className={`acma-filtro-pill ${area === grupo ? 'acma-filtro-pill-activo' : ''}`}>
                {grupo}
              </button>
            ))}
          </div>
        </div>

        {visibles.length ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {visibles.map(m => <TarjetaModulo key={m.id} modulo={m} />)}
          </div>
        ) : (
          <div role="status" className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center">
            <IconoAcma nombre="buscar" className="mx-auto mb-3 h-9 w-9 text-slate-400" />
            <p className="font-bold text-slate-800">No encontramos ese módulo</p>
            <p className="mt-1 text-sm text-slate-500">Prueba con otra palabra o selecciona «Todos».</p>
            <button type="button" onClick={() => { setBuscar(''); setArea('Todos') }}
              className="mt-4 rounded-lg bg-primario px-4 py-2 text-sm font-semibold text-white">Mostrar todos</button>
          </div>
        )}
      </section>
    </div>
  )
}

function TarjetaModulo({ modulo }: { modulo: Modulo }) {
  return (
    <Link to={modulo.ruta} data-testid={`modulo-${modulo.id}`} className="acma-modulo-tarjeta group flex min-w-0 flex-col p-5 sm:p-6">
      <div className="mb-5 flex items-start justify-between gap-3">
        <span className="acma-modulo-icono">
          <IconoAcma nombre={modulo.id} className="h-6 w-6" />
        </span>
        <IconoAcma nombre="flecha" className="h-5 w-5 text-slate-300 transition duration-200 group-hover:translate-x-1 group-hover:text-primario" />
      </div>
      <p className="mb-2 text-[10px] font-bold uppercase tracking-[.14em] text-primario/80">{modulo.grupo}</p>
      <h3 className="mb-2 text-[16px] font-bold text-[#28272c]">{modulo.nombre}</h3>
      <p className="line-clamp-3 flex-1 text-sm leading-6 text-slate-500">{modulo.descripcion}</p>
      <div className="mt-5 flex items-center gap-2 border-t border-slate-100 pt-4 text-xs font-bold text-primario">
        Abrir módulo <IconoAcma nombre="flecha" className="h-4 w-4" />
      </div>
    </Link>
  )
}
