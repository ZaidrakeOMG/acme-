import type { ReactNode } from 'react'
import type { HabilidadDeTecnico, Rol } from '../../types/api'
import type { EstadoFolio, FolioResumen, SeveridadResumen } from '../../types/folios'
import { NOMBRE_ESTADO } from '../../types/folios'

export const ROLES_CAPTURA: Rol[] = ['superadmin', 'operador', 'admin_un', 'admin_empresa', 'supervisor_operadores', 'mesa_control', 'tecnico', 'despachador']
export const ROLES_APROBADOR: Rol[] = ['superadmin', 'admin_un', 'supervisor_operadores', 'admin_empresa']

const TONO_ESTADO: Record<EstadoFolio, string> = {
  capturado: 'bg-slate-100 text-slate-700', en_revision: 'bg-amber-100 text-amber-900', pendiente_informacion: 'bg-orange-100 text-orange-900',
  autorizado: 'bg-sky-100 text-sky-900', asignado: 'bg-indigo-100 text-indigo-900', reasignado: 'bg-indigo-50 text-indigo-800',
  en_camino: 'bg-violet-100 text-violet-900', en_ejecucion: 'bg-blue-100 text-blue-900', pendiente_refaccion: 'bg-rose-100 text-rose-900',
  cerrado: 'bg-green-100 text-green-900', cancelado: 'bg-red-100 text-red-900',
}

export function EstadoInsignia({ estado }: { estado: EstadoFolio }) {
  return <span data-testid={`estado-${estado}`} className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${TONO_ESTADO[estado]}`}>{NOMBRE_ESTADO[estado]}</span>
}

/** Insignia con el color del nivel de severidad (§6.10.1). */
export function SeveridadInsignia({ severidad }: { severidad: SeveridadResumen | null }) {
  if (!severidad) return <span className="text-xs text-slate-400">Sin severidad</span>
  return (
    <span className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium" style={{ borderColor: severidad.color_hex, color: severidad.color_hex }}>
      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: severidad.color_hex }} aria-hidden />
      {severidad.nombre}
    </span>
  )
}

export function antiguedad(horas: number): string {
  if (horas < 1) return `${Math.round(horas * 60)} min`
  if (horas < 48) return `${Math.round(horas)} h`
  return `${Math.round(horas / 24)} d`
}

export function fecha(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString('es-MX', { dateStyle: 'short', timeStyle: 'short' }) : '—'
}

export function TarjetaFolio({ folio, children }: { folio: FolioResumen; children?: ReactNode }) {
  return (
    <article data-testid={`folio-${folio.numero_folio}`} className="rounded-lg border border-slate-200 bg-white p-3 text-sm shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-xs font-semibold text-slate-700">{folio.numero_folio}</span>
        <SeveridadInsignia severidad={folio.severidad} />
      </div>
      <p className="mt-1 line-clamp-2 text-slate-800">{folio.descripcion}</p>
      <p className="mt-1 text-xs text-slate-500">{folio.un_codigo} · {folio.equipo_codigo} {folio.tecnico_nombre ? `· ${folio.tecnico_nombre}` : ''} · {antiguedad(folio.antiguedad_horas)}</p>
      {children}
    </article>
  )
}

/**
 * Resumen de habilidades de un técnico para elegirlo (§6.10.3, F2-01): desde F2-01 la asignación exige la habilidad
 * **certificada y vigente**, así que la lista separa las que sirven de las que ya no.
 */
export function resumenCertificaciones(habilidades: HabilidadDeTecnico[]): string {
  if (habilidades.length === 0) return 'sin habilidades'
  const vigentes = habilidades.filter((h) => h.certificada && h.vigente !== false)
  const caidas = habilidades.filter((h) => !h.certificada || h.vigente === false)
  const partes: string[] = []
  if (vigentes.length) partes.push(`certificadas: ${vigentes.map((h) => h.clave).join(', ')}`)
  if (caidas.length) partes.push(`sin certificación vigente: ${caidas.map((h) => h.clave).join(', ')}`)
  return partes.join(' · ')
}
