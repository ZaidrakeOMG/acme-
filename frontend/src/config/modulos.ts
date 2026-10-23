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
    roles: ['superadmin', ...PRESTADOR_GESTION, 'admin_empresa', 'admin_un', 'supervisor_operadores', 'operador', 'tecnico'] },
  { id: 'app_campo', nombre: 'App de campo y chat', descripcion: 'Captura, evidencias, firma y modo offline', prompt: 'P05',
    grupo: 'Operación', roles: ['operador', 'tecnico'] },
  { id: 'preventivos', nombre: 'Preventivos y planes', descripcion: 'Calendario y triggers por tiempo y calendario', prompt: 'P06',
    grupo: 'Operación', roles: ['superadmin', 'admin_prestador', 'despachador', 'admin_empresa'] },
  { id: 'reasignaciones', nombre: 'Reasignaciones', descripcion: 'Reasignación forzada con razones', prompt: 'P06', grupo: 'Operación',
    roles: ['admin_prestador', 'despachador', 'mesa_control'] },
  { id: 'minuta', nombre: 'Minuta del día', descripcion: 'Generación, validación y respuesta', prompt: 'P07', grupo: 'Seguimiento',
    roles: ['admin_prestador', 'despachador', 'mesa_control', 'admin_empresa', 'admin_un'] },
  { id: 'seguimiento', nombre: 'Seguimiento', descripcion: 'Cotizaciones, presupuesto, interno y reprogramación', prompt: 'P07',
    grupo: 'Seguimiento', roles: [...PRESTADOR_GESTION, 'direccion_prestador', 'admin_empresa', 'admin_un'] },
  { id: 'clasificacion', nombre: 'Folios no críticos', descripcion: 'Clasificación y calificación por período', prompt: 'P07',
    grupo: 'Seguimiento', roles: ['admin_empresa', 'admin_un'] },
  { id: 'trabajos_especiales', nombre: 'Trabajos especiales', descripcion: '8 estados y aceptación del cliente', prompt: 'P08',
    grupo: 'Operación', roles: [...PRESTADOR_GESTION, 'admin_empresa'] },
  { id: 'oc_instalacion', nombre: 'OC de instalación', descripcion: 'Seguimiento del trámite de OC', prompt: 'P08', grupo: 'Seguimiento',
    roles: ['admin_prestador', 'mesa_control', 'admin_empresa'] },
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
