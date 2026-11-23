/**
 * Módulos de Fase 1 (Anexo de alcance v1.0) y roles que los ven (§5 del Documento de Diseño v2.5).
 * Los 27 módulos de Fase 1 tienen pantalla; cada uno declara su ruta y los roles que lo ven.
 */
import type { Rol } from '../types/api'

export type GrupoModulo = 'Administración' | 'Operación' | 'Seguimiento' | 'Finanzas y activos' | 'Análisis'

export interface Modulo {
  id: string
  nombre: string
  descripcion: string
  grupo: GrupoModulo
  ruta: string
  roles: Rol[]
}

const PRESTADOR_GESTION: Rol[] = ['admin_prestador', 'mesa_control', 'despachador']
const LECTURA_EJECUTIVA: Rol[] = ['direccion_prestador', 'supervisor_prestador']

export const MODULOS: Modulo[] = [
  { id: 'usuarios', nombre: 'Usuarios', descripcion: 'Altas, roles y estado de los usuarios', grupo: 'Administración',
    ruta: '/usuarios', roles: ['superadmin', 'admin_prestador', 'admin_empresa'] },
  { id: 'tenants', nombre: 'Clientes (tenants)', descripcion: 'Empresas cliente y su vínculo con prestadores',
    grupo: 'Administración', ruta: '/tenants', roles: ['superadmin', 'admin_prestador'] },
  { id: 'prestadores', nombre: 'Prestadores', descripcion: 'Datos fiscales, logo y colores del prestador',
    grupo: 'Administración', ruta: '/prestadores', roles: ['superadmin', 'admin_prestador'] },
  { id: 'unidades', nombre: 'Unidades de negocio', descripcion: 'UNs, ubicación y grupos de UNs', grupo: 'Administración',
    ruta: '/unidades', roles: ['superadmin', 'admin_empresa', 'admin_un', 'supervisor_operadores', ...PRESTADOR_GESTION] },
  { id: 'contratos', nombre: 'Contratos y SLAs', descripcion: 'Vigencia, modalidad y SLAs por severidad',
    grupo: 'Administración', ruta: '/contratos', roles: ['superadmin', 'admin_prestador', 'direccion_prestador', 'mesa_control', 'admin_empresa'] },
  { id: 'alertas', nombre: 'Configuración de alertas', descripcion: 'Umbrales, canales y supresiones',
    grupo: 'Administración', ruta: '/alertas', roles: ['superadmin', 'admin_prestador', 'admin_empresa'] },
  { id: 'capacitacion', nombre: 'Capacitación y certificaciones',
    descripcion: 'Cursos del personal, vigencia de certificaciones y habilidades certificadas', grupo: 'Administración',
    ruta: '/capacitacion', roles: ['superadmin', 'admin_prestador', 'mesa_control', 'despachador', 'admin_empresa', 'admin_un'] },
  { id: 'auditoria', nombre: 'Auditoría', descripcion: 'Eventos de seguridad y accesos a la API', grupo: 'Administración',
    ruta: '/auditoria', roles: ['superadmin'] },

  { id: 'catalogos', nombre: 'Catálogos maestros', descripcion: 'Técnicos, equipos, fallas, severidades e importador',
    grupo: 'Administración', ruta: '/catalogos', roles: ['superadmin', 'admin_prestador', 'admin_empresa', 'admin_un', 'mesa_control', 'despachador'] },
  { id: 'formularios', nombre: 'Formularios dinámicos', descripcion: 'Constructor con 22 tipos de campo, plantillas y versiones',
    grupo: 'Administración', ruta: '/formularios', roles: ['superadmin', 'admin_prestador', 'mesa_control'] },
  { id: 'mis_formularios', nombre: 'Mis formularios', descripcion: 'Formularios dirigidos a tu rol: llenar, reanudar y consultar',
    grupo: 'Operación', ruta: '/mis-formularios', roles: ['superadmin', 'admin_prestador', 'mesa_control', 'despachador', 'tecnico', 'supervisor_prestador', 'direccion_prestador', 'admin_empresa', 'admin_un', 'supervisor_operadores', 'operador'] },
  { id: 'biblioteca', nombre: 'Biblioteca técnica',
    descripcion: 'Manuales y fichas por tipo de equipo, versiones y contenido de servicio del contrato',
    grupo: 'Operación', ruta: '/biblioteca',
    roles: ['superadmin', 'admin_prestador', 'mesa_control', 'despachador', 'tecnico', 'direccion_prestador', 'supervisor_prestador', 'admin_empresa', 'admin_un', 'supervisor_operadores'] },
  { id: 'operaciones', nombre: 'Operaciones en tiempo real',
    descripcion: 'Mapa en vivo de técnicos en jornada, folios con SLA en riesgo y alertas de la jornada',
    grupo: 'Operación', ruta: '/operaciones',
    roles: ['superadmin', 'admin_prestador', 'despachador', 'mesa_control'] },
  { id: 'folios', nombre: 'Folios', descripcion: 'Ciclo de vida, validaciones y aprobaciones', grupo: 'Operación',
    ruta: '/folios', roles: ['superadmin', ...PRESTADOR_GESTION, 'admin_empresa', 'admin_un', 'supervisor_operadores', 'operador', 'tecnico'] },
  { id: 'app_campo', nombre: 'App de campo y chat', descripcion: 'Captura, evidencias, firma y modo offline',
    grupo: 'Operación', ruta: '/campo', roles: ['operador', 'tecnico', 'admin_un'] },
  { id: 'preventivos', nombre: 'Preventivos y planes', descripcion: 'Calendario mensual, planes con triggers y autorizaciones',
    grupo: 'Operación', ruta: '/preventivos/calendario', roles: ['superadmin', ...PRESTADOR_GESTION, 'admin_empresa', 'admin_un', 'supervisor_operadores'] },
  { id: 'reasignaciones', nombre: 'Reasignaciones', descripcion: 'Reporte de causas y catálogo de razones (§6.8.2)', grupo: 'Operación',
    ruta: '/reasignaciones/reporte', roles: ['superadmin', ...PRESTADOR_GESTION, 'direccion_prestador', 'supervisor_prestador', 'admin_empresa'] },
  { id: 'minuta', nombre: 'Minuta del día', descripcion: 'Cierre de jornada por UN y global: validación, entrega y respuesta', grupo: 'Seguimiento',
    ruta: '/minutas', roles: ['superadmin', ...PRESTADOR_GESTION, 'admin_empresa', 'admin_un', 'supervisor_operadores', ...LECTURA_EJECUTIVA] },
  { id: 'seguimiento', nombre: 'Seguimiento', descripcion: 'Cotizaciones, por presupuesto, seguimiento interno y reprogramación',
    grupo: 'Seguimiento', ruta: '/seguimiento', roles: ['superadmin', ...PRESTADOR_GESTION, ...LECTURA_EJECUTIVA, 'admin_empresa', 'admin_un', 'supervisor_operadores'] },
  { id: 'clasificacion', nombre: 'Folios no críticos', descripcion: 'Clasificación en plazo y calificación del Admin UN',
    grupo: 'Seguimiento', ruta: '/clasificacion', roles: ['superadmin', 'admin_empresa', 'admin_un', 'supervisor_operadores'] },
  { id: 'notificaciones', nombre: 'Notificaciones', descripcion: 'Bandeja y preferencias de canal por evento', grupo: 'Operación',
    ruta: '/notificaciones', roles: ['superadmin', 'admin_prestador', 'direccion_prestador', 'mesa_control', 'despachador', 'supervisor_prestador', 'tecnico', 'admin_empresa', 'admin_un', 'supervisor_operadores', 'operador'] },
  { id: 'mensajeria', nombre: 'Mensajería (WhatsApp y SMS)',
    descripcion: 'Canales activos, plantillas aprobables por Meta, consumo del mes y bitácora de envíos',
    grupo: 'Administración', ruta: '/mensajeria',
    roles: ['superadmin', 'admin_prestador', 'admin_empresa', 'mesa_control', 'direccion_prestador'] },
  { id: 'trabajos_especiales', nombre: 'Trabajos especiales', descripcion: 'Ciclo de 8 estados, validación del cliente por botón y TE de urgencia',
    grupo: 'Operación', ruta: '/trabajos-especiales', roles: ['superadmin', ...PRESTADOR_GESTION, 'admin_empresa', 'admin_un', 'supervisor_operadores', ...LECTURA_EJECUTIVA] },
  { id: 'oc_activos', nombre: 'OC de activos', descripcion: 'Seguimiento del trámite de OC para instalación de activos', grupo: 'Seguimiento',
    ruta: '/oc-activos', roles: ['superadmin', 'admin_empresa', 'admin_un', 'supervisor_operadores', ...PRESTADOR_GESTION] },
  { id: 'inventario', nombre: 'Inventario', descripcion: 'Artículos, existencias por almacén y vehículo, movimientos y órdenes de compra',
    grupo: 'Finanzas y activos', ruta: '/inventario', roles: ['superadmin', ...PRESTADOR_GESTION, 'tecnico', ...LECTURA_EJECUTIVA] },
  { id: 'caja_chica', nombre: 'Caja chica', descripcion: 'Fondo por técnico, captura de la factura y pólizas de reposición',
    grupo: 'Finanzas y activos', ruta: '/caja-chica', roles: ['superadmin', ...PRESTADOR_GESTION, 'tecnico', 'direccion_prestador'] },
  { id: 'presupuestos', nombre: 'Presupuestos', descripcion: 'Gasto contra presupuesto por UN, grupo y tipo de actividad',
    grupo: 'Finanzas y activos', ruta: '/presupuestos', roles: ['superadmin', 'admin_empresa', 'admin_un', 'supervisor_operadores', 'admin_prestador', 'mesa_control', 'direccion_prestador'] },
  { id: 'activos', nombre: 'Equipos y activos', descripcion: 'Ficha, historial, depreciación, TCO y reemplazo recomendado',
    grupo: 'Finanzas y activos', ruta: '/activos', roles: ['superadmin', 'admin_empresa', 'admin_un', 'supervisor_operadores', ...PRESTADOR_GESTION, ...LECTURA_EJECUTIVA] },
  { id: 'medidores', nombre: 'Medidores de activos', descripcion: 'Lecturas por revisar, catálogo de tipos de medidor y llaves de API para recibir lecturas',
    grupo: 'Finanzas y activos', ruta: '/medidores',
    roles: ['superadmin', ...PRESTADOR_GESTION, 'admin_empresa', 'admin_un'] },
  { id: 'rutas', nombre: 'Rutas del día', descripcion: 'Ruta óptima por técnico con habilidades, ventanas, SLA y criticidad; propuestas de reasignación y ETA',
    grupo: 'Operación', ruta: '/rutas',
    roles: ['superadmin', 'admin_prestador', 'despachador', 'mesa_control', 'direccion_prestador', 'supervisor_prestador'] },
  { id: 'iso55000', nombre: 'Gestión de activos ISO 55000', descripcion: 'Criticidad A/B/C/D, matriz de riesgo, modos de falla, mitigaciones y reportes de certificación',
    grupo: 'Finanzas y activos', ruta: '/iso55000',
    roles: ['superadmin', 'admin_empresa', 'admin_un', ...PRESTADOR_GESTION, ...LECTURA_EJECUTIVA] },
  { id: 'erp', nombre: 'Integración ERP', descripcion: 'Eventos, exportación universal XML/Excel y adaptadores',
    grupo: 'Finanzas y activos', ruta: '/erp', roles: ['superadmin', 'admin_prestador', 'direccion_prestador', 'mesa_control', 'despachador'] },
  { id: 'sla', nombre: 'Contador de SLA', descripcion: 'Cumplimiento del contrato, pausas, exclusiones y penalizaciones del período',
    grupo: 'Análisis', ruta: '/contratos?vista=cumplimiento',
    roles: ['superadmin', 'admin_prestador', 'mesa_control', 'despachador', 'admin_empresa', 'admin_un', ...LECTURA_EJECUTIVA] },
  { id: 'bi', nombre: 'Inteligencia de negocio', descripcion: 'Tablero por rol con la jerarquía cliente → grupo → UN y reportes comparativos',
    grupo: 'Análisis', ruta: '/bi',
    roles: ['superadmin', 'admin_prestador', 'mesa_control', 'despachador', 'admin_empresa', 'admin_un', 'supervisor_operadores', ...LECTURA_EJECUTIVA] },
]

export function modulosDe(rol: Rol, habilitados?: string[] | null): Modulo[] {
  const porRol = rol === 'superadmin' ? MODULOS : MODULOS.filter(m => m.roles.includes(rol))
  if (rol === 'superadmin' || habilitados == null) return porRol
  // Usuarios permanece accesible para admin empresa y admin prestador.
  return porRol.filter(m => (m.id === 'usuarios' && ['admin_empresa', 'admin_prestador'].includes(rol)) || habilitados.includes(m.id))
}

export function puedeAccederModulo(rol: Rol, id: string, habilitados?: string[] | null): boolean {
  return modulosDe(rol, habilitados).some(m => m.id === id)
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
