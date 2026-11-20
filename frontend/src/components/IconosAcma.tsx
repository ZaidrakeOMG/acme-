import type { ReactNode } from 'react'

/** Iconografía SVG uniforme. Sin emojis, librerías nuevas ni fuentes externas. */
const TRAZOS: Record<string, ReactNode> = {
  menu: <><path d="M4 7h16M4 12h16M4 17h16" /></>,
  fijar: <><path d="m16 3 5 5-2.4 1.3-2.2 4.6-3.4 1.3-2.1 5.8-1.6-1.6 1.7-6-3.9-3.9-4.8 1.3-1.3-1.3 5.2-2.4 1.2-3.9 4.8-1.9z" /></>,
  desfijar: <><path d="m3 3 18 18M15 4l5 4-2.5 1.5-1.3 3M12 16l-1.4 5-1.6-1.6 1-3M4 10l2-2 2 2" /></>,

  cerrar: <><path d="M6 6 18 18M18 6 6 18" /></>,
  chevron: <><path d="m6 9 6 6 6-6" /></>,
  buscar: <><circle cx="11" cy="11" r="7" /><path d="m16 16 4 4" /></>,
  inicio: <><path d="m3 10 9-7 9 7v10H3z" /><path d="M9 20v-7h6v7" /></>,
  salir: <><path d="M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h5" /><path d="m14 8 4 4-4 4M18 12H8" /></>,
  flecha: <><path d="M4 12h16m-6-6 6 6-6 6" /></>,
  cuadrícula: <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>,
  escudo: <><path d="M12 2 4 6v6c0 5 3.5 8 8 10 4.5-2 8-5 8-10V6z" /><path d="m9 12 2 2 4-4" /></>,
  campana: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9ZM10 21h4" /></>,
  usuarios: <><circle cx="9" cy="8" r="3" /><path d="M2 20v-2a6 6 0 0 1 12 0v2M17 5a3 3 0 0 1 0 6m1 4a5 5 0 0 1 4 5" /></>,
  edificio: <><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M8 7h2m4 0h2M8 11h2m4 0h2M8 15h2m4 0h2M10 21v-4h4v4" /></>,
  herramientas: <><path d="M14.2 5.3a5 5 0 0 0-6.3 6.3L3 16.2 7.8 21l4.9-4.9a5 5 0 0 0 6.3-6.3l-3.4 3.4-4.8-4.8z" /></>,
  folios: <><rect x="5" y="3" width="14" height="18" rx="2" /><path d="M9 8h6M9 12h6M9 16h4" /></>,
  calendario: <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M7 3v4m10-4v4M3 10h18m-13 5h3" /></>,
  actividad: <><path d="M3 12h4l3-7 4 14 3-7h4" /></>,
  reporte: <><path d="M4 20h16M7 17v-6m5 6V5m5 12V9" /></>,
  seguridad: <><path d="M12 2 4 6v6c0 5 3.5 8 8 10 4.5-2 8-5 8-10V6z" /><path d="m9 12 2 2 4-4" /></>,
  ajustes: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.9l-1.9 1.9a1.7 1.7 0 0 0-1.9-.34l-1.4.6V21h-2.7v-1.94l-1.4-.6a1.7 1.7 0 0 0-1.9.34l-1.9-1.9a1.7 1.7 0 0 0 .34-1.9l-.6-1.4H3v-2.7h1.94l.6-1.4a1.7 1.7 0 0 0-.34-1.9l1.9-1.9a1.7 1.7 0 0 0 1.9.34l1.4-.6V3h2.7v1.94l1.4.6a1.7 1.7 0 0 0 1.9-.34l1.9 1.9a1.7 1.7 0 0 0-.34 1.9l.6 1.4H21v2.7h-1.94z" /></>,
  almacén: <><path d="m3 9 9-6 9 6v12H3z" /><path d="M3 9h18M9 21v-8h6v8" /></>,
  caja: <><rect x="3" y="6" width="18" height="14" rx="2" /><path d="M3 10h18M16 15h2" /></>,
  libro: <><path d="M12 6c-3-2-6-2-9-1v15c3-1 6-1 9 1 3-2 6-2 9-1V5c-3-1-6-1-9 1zm0 0v15" /></>,
  mensaje: <><path d="M4 5h16v12H9l-5 4z" /><path d="M8 10h8m-8 3h5" /></>,
  documento: <><path d="M6 2h9l4 4v16H6zM15 2v5h4M9 12h7M9 16h7" /></>,
  gráfica: <><path d="M3 3v18h18M7 16l4-5 3 2 5-7" /><path d="M16 6h3v3" /></>,
  ubicación: <><path d="M20 10c0 5-8 12-8 12S4 15 4 10a8 8 0 1 1 16 0z" /><circle cx="12" cy="10" r="2.5" /></>,
  usuario: <><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></>,
  reloj: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  carpeta: <><path d="M3 6h7l2 3h9v11H3z" /></>,
  sincronizar: <><path d="M20 7v5h-5m-11 5v-5h5" /><path d="M5.6 9A7 7 0 0 1 18 7l2 5M4 12l2 5a7 7 0 0 0 12.4-2" /></>,
  correo: <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3 7 9 6 9-6" /></>,
  checklist: <><path d="m4 7 2 2 4-4m2 3h8M4 16l2 2 4-4m2 3h8" /></>,
  escáner: <><path d="M4 9V4h5m6 0h5v5M4 15v5h5m6 0h5v-5M7 12h10" /></>,
}

const ICONO_MODULO: Record<string, string> = {
  usuarios: 'usuarios', tenants: 'edificio', prestadores: 'edificio', unidades: 'edificio',
  contratos: 'documento', alertas: 'campana', capacitacion: 'libro', auditoria: 'escudo',
  catalogos: 'carpeta', formularios: 'documento', mis_formularios: 'checklist',
  biblioteca: 'libro', operaciones: 'actividad', folios: 'folios', app_campo: 'herramientas',
  preventivos: 'calendario', reasignaciones: 'sincronizar', minuta: 'documento',
  seguimiento: 'actividad', clasificacion: 'checklist', notificaciones: 'campana',
  mensajeria: 'mensaje', trabajos_especiales: 'herramientas', oc_activos: 'documento',
  inventario: 'almacén', caja_chica: 'caja', presupuestos: 'gráfica',
  activos: 'herramientas', medidores: 'actividad', rutas: 'ubicación',
  iso55000: 'escudo', erp: 'sincronizar', sla: 'reloj', bi: 'gráfica',
}
export function IconoAcma({ nombre, className = 'h-5 w-5' }: { nombre: string; className?: string }) {
  const tipo = ICONO_MODULO[nombre] ?? nombre
  return (
    <svg aria-hidden="true" className={`shrink-0 ${className}`} fill="none" viewBox="0 0 24 24"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      {TRAZOS[tipo] ?? TRAZOS.cuadrícula}
    </svg>
  )
}
