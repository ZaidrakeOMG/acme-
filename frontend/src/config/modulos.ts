/**
 * Módulos de Fase 1 (Anexo de alcance v1.0) y roles que los ven (§5 del Documento de Diseño v2.5).
 * `prompt` indica en qué prompt se construye; los que no son P01 se muestran como "Disponible en el prompt Pxx".
 * La asignación módulo→rol de los módulos futuros es preliminar (ver CONTEXTO.md, decisiones pendientes).
 */
import type { Rol } from '../types/api'

export type GrupoModulo = 'Administración' | 'Operación' | 'Seguimiento' | 'Finanzas y activos' | 'Análisis'

export interface Modulo {
  id: string
  nombre: string
  descripcion: string
  prompt: string
  grupo: GrupoModulo
  ruta?: string
  roles: Rol[]
}

const PRESTADOR_GESTION: Rol[] = ['admin_prestador', 'mesa_control', 'despachador']
const LECTURA_EJECUTIVA: Rol[] = ['direccion_prestador', 'supervisor_prestador']

export const MODULOS: Modulo[] = [
  // ---------------------------------------------------------------- P01
  { id: 'usuarios', nombre: 'Usuarios', descripcion: 'Altas, roles y estado de los usuarios', prompt: 'P01', grupo: 'Administración',
    ruta: '/usuarios', roles: ['superadmin', 'admin_prestador', 'admin_empresa'] },
  { id: 'tenants', nombre: 'Clientes (tenants)', descripcion: 'Empresas cliente y su vínculo con prestadores', prompt: 'P01',
    grupo: 'Administración', ruta: '/tenants', roles: ['superadmin', 'admin_prestador'] },
  { id: 'prestadores', nombre: 'Prestadores', descripcion: 'Datos fiscales, logo y colores del prestador', prompt: 'P01',
    grupo: 'Administración', ruta: '/prestadores', roles: ['superadmin', 'admin_prestador'] },
  { id: 'unidades', nombre: 'Unidades de negocio', descripcion: 'UNs, ubicación y grupos de UNs', prompt: 'P01', grupo: 'Administración',
    ruta: '/unidades', roles: ['superadmin', 'admin_empresa', 'admin_un', 'supervisor_operadores', ...PRESTADOR_GESTION] },
  { id: 'contratos', nombre: 'Contratos y SLAs', descripcion: 'Vigencia, modalidad y SLAs por severidad', prompt: 'P01',
    grupo: 'Administración', ruta: '/contratos', roles: ['superadmin', 'admin_prestador', 'direccion_prestador', 'mesa_control', 'admin_empresa'] },
  { id: 'alertas', nombre: 'Configuración de alertas', descripcion: 'Umbrales, canales y supresiones', prompt: 'P01',
    grupo: 'Administración', ruta: '/alertas', roles: ['superadmin', 'admin_prestador', 'admin_empresa'] },
  { id: 'auditoria', nombre: 'Auditoría', descripcion: 'Eventos de seguridad y accesos a la API', prompt: 'P01', grupo: 'Administración',
    ruta: '/auditoria', roles: ['superadmin'] },

  // ------------------------------------------------------------ P02–P10
  { id: 'catalogos', nombre: 'Catálogos maestros', descripcion: 'Técnicos, equipos, fallas, severidades e importador', prompt: 'P02',
    grupo: 'Administración', ruta: '/catalogos', roles: ['superadmin', 'admin_prestador', 'admin_empresa', 'admin_un', 'mesa_control', 'despachador'] },
  { id: 'formularios', nombre: 'Formularios dinámicos', descripcion: 'Constructor con 22 tipos de campo, plantillas y versiones', prompt: 'P03',
    grupo: 'Administración', ruta: '/formularios', roles: ['superadmin', 'admin_prestador', 'mesa_control'] },
  { id: 'mis_formularios', nombre: 'Mis formularios', descripcion: 'Formularios dirigidos a tu rol: llenar, reanudar y consultar', prompt: 'P03',
    grupo: 'Operación', ruta: '/mis-formularios', roles: ['superadmin', 'admin_prestador', 'mesa_control', 'despachador', 'tecnico', 'supervisor_prestador', 'direccion_prestador', 'admin_empresa', 'admin_un', 'supervisor_operadores', 'operador'] },
  { id: 'folios', nombre: 'Folios', descripcion: 'Ciclo de vida, validaciones y aprobaciones', prompt: 'P04', grupo: 'Operación',
    ruta: '/folios', roles: ['superadmin', ...PRESTADOR_GESTION, 'admin_empresa', 'admin_un', 'supervisor_operadores', 'operador', 'tecnico'] },
  { id: 'app_campo', nombre: 'App de campo y chat', descripcion: 'Captura, evidencias, firma y modo offline', prompt: 'P05',
    grupo: 'Operación', ruta: '/campo', roles: ['operador', 'tecnico', 'admin_un'] },
  { id: 'preventivos', nombre: 'Preventivos y planes', descripcion: 'Calendario mensual, planes con triggers y autorizaciones', prompt: 'P06',
    grupo: 'Operación', ruta: '/preventivos/calendario', roles: ['superadmin', ...PRESTADOR_GESTION, 'admin_empresa', 'admin_un', 'supervisor_operadores'] },
  { id: 'reasignaciones', nombre: 'Reasignaciones', descripcion: 'Reporte de causas y catálogo de razones (§6.8.2)', prompt: 'P06', grupo: 'Operación',
    ruta: '/reasignaciones/reporte', roles: ['superadmin', ...PRESTADOR_GESTION, 'direccion_prestador', 'supervisor_prestador', 'admin_empresa'] },
  { id: 'minuta', nombre: 'Minuta del día', descripcion: 'Cierre de jornada por UN y global: validación, entrega y respuesta', prompt: 'P07', grupo: 'Seguimiento',
    ruta: '/minutas', roles: ['superadmin', ...PRESTADOR_GESTION, 'admin_empresa', 'admin_un', 'supervisor_operadores', ...LECTURA_EJECUTIVA] },
  { id: 'seguimiento', nombre: 'Seguimiento', descripcion: 'Cotizaciones, por presupuesto, seguimiento interno y reprogramación', prompt: 'P07',
    grupo: 'Seguimiento', ruta: '/seguimiento', roles: ['superadmin', ...PRESTADOR_GESTION, ...LECTURA_EJECUTIVA, 'admin_empresa', 'admin_un', 'supervisor_operadores'] },
  { id: 'clasificacion', nombre: 'Folios no críticos', descripcion: 'Clasificación en plazo y calificación del Admin UN', prompt: 'P07',
    grupo: 'Seguimiento', ruta: '/clasificacion', roles: ['superadmin', 'admin_empresa', 'admin_un', 'supervisor_operadores'] },
  { id: 'notificaciones', nombre: 'Notificaciones', descripcion: 'Bandeja y preferencias de canal por evento', prompt: 'P07', grupo: 'Operación',
    ruta: '/notificaciones', roles: ['superadmin', 'admin_prestador', 'direccion_prestador', 'mesa_control', 'despachador', 'supervisor_prestador', 'tecnico', 'admin_empresa', 'admin_un', 'supervisor_operadores', 'operador'] },
  { id: 'trabajos_especiales', nombre: 'Trabajos especiales', descripcion: 'Ciclo de 8 estados, validación del cliente por botón y TE de urgencia', prompt: 'P08',
    grupo: 'Operación', ruta: '/trabajos-especiales', roles: ['superadmin', ...PRESTADOR_GESTION, 'admin_empresa', 'admin_un', 'supervisor_operadores', ...LECTURA_EJECUTIVA] },
  { id: 'oc_activos', nombre: 'OC de activos', descripcion: 'Seguimiento del trámite de OC para instalación de activos', prompt: 'P08', grupo: 'Seguimiento',
    ruta: '/oc-activos', roles: ['superadmin', 'admin_empresa', 'admin_un', 'supervisor_operadores', ...PRESTADOR_GESTION] },
  { id: 'inventario', nombre: 'Inventario', descripcion: 'Almacén, orígenes de refacción y OC', prompt: 'P09', grupo: 'Finanzas y activos',
    roles: ['admin_prestador', 'tecnico'] },
  { id: 'caja_chica', nombre: 'Caja chica', descripcion: 'Captura manual del gasto con foto', prompt: 'P09', grupo: 'Finanzas y activos',
    roles: ['admin_prestador', 'tecnico'] },
  { id: 'presupuestos', nombre: 'Presupuestos', descripcion: 'Por UN, grupo y tipo de actividad', prompt: 'P09', grupo: 'Finanzas y activos',
    roles: ['admin_empresa'] },
  { id: 'activos', nombre: 'Equipos y activos', descripcion: 'Ficha, historial, depreciación y TCO', prompt: 'P09', grupo: 'Finanzas y activos',
    roles: ['admin_prestador', 'admin_empresa', 'admin_un'] },
  { id: 'erp', nombre: 'Exportación ERP', descripcion: 'XML/Excel de pólizas, OC y gastos', prompt: 'P09', grupo: 'Finanzas y activos',
    roles: ['admin_prestador'] },
  { id: 'sla', nombre: 'Contador de SLA', descripcion: 'Pausas, exclusiones y penalizaciones', prompt: 'P10', grupo: 'Análisis',
    roles: ['admin_prestador', 'mesa_control', 'admin_empresa', ...LECTURA_EJECUTIVA] },
  { id: 'bi', nombre: 'Inteligencia de negocio', descripcion: 'Dashboards y reportes comparativos', prompt: 'P10', grupo: 'Análisis',
    roles: ['admin_prestador', 'mesa_control', 'admin_empresa', 'admin_un', 'supervisor_operadores', ...LECTURA_EJECUTIVA] },
]

export function modulosDe(rol: Rol): Modulo[] {
  return rol === 'superadmin' ? MODULOS : MODULOS.filter((m) => m.roles.includes(rol))
}

export const NOMBRE_ROL: Record<Rol, string> = {
  superadmin: 'Superadmin',
  admin_prestador: 'Admin prestador',
  direccion_prestador: 'Dirección del prestador',
  mesa_control: 'Mesa de control',
  despachador: 'Despachador',
  supervisor_prestador: 'Supervisor (prestador)',
  tecnico: 'Técnico',
  admin_empresa: 'Admin empresa',
  admin_un: 'Admin unidad de negocio',
  supervisor_operadores: 'Supervisor de operadores',
  operador: 'Operador',
}
