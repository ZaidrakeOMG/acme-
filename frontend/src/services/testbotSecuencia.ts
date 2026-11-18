/**
 * Secuencia permanente de ACMA TestBot, después de Formularios dinámicos.
 *
 * Estas son pruebas reales de disponibilidad/lectura del servidor. No equivalen a
 * pruebas CRUD completas y NUNCA deben presentarse como si hubieran probado altas,
 * firmas, evidencias, pagos, transferencias o flujos por otros roles.
 * Es deliberadamente read-only en producción.
 */
import { api } from './api'
import { ejecutarEscrituraDemo } from './testbotEscriturasDemo'
import { MODULOS } from '../config/modulos'

type TipoRespuesta = 'lista' | 'objeto' | 'json' | 'nullable'
type Chequeo = { ruta: string; tipo: TipoRespuesta; titulo: string; params?: Record<string, string> }
export type EstadoModulo = 'consulta_verificada' | 'pendiente_funcional' | 'requiere_otro_rol' | 'alta_demo_verificada' | 'alta_cambio_demo_verificados' | 'error'
export interface ResultadoModulo {
  id: string
  nombre: string
  estado: EstadoModulo
  mensaje: string
  detalles: string[]
  comprobadoEn: string
}
export interface EstadoRecorrido {
  indice: number
  resultados: ResultadoModulo[]
}
export const INICIAL_RECORRIDO: EstadoRecorrido = { indice: 0, resultados: [] }

const ORDEN: string[] = [
  'biblioteca', 'operaciones', 'folios', 'app_campo', 'preventivos', 'reasignaciones',
  'notificaciones', 'minuta', 'seguimiento', 'clasificacion', 'trabajos_especiales',
  'oc_activos', 'inventario', 'caja_chica', 'presupuestos', 'activos', 'medidores',
  'rutas', 'iso55000', 'erp', 'sla', 'bi', 'mensajeria',
  'usuarios', 'tenants', 'prestadores', 'unidades', 'contratos', 'alertas',
  'capacitacion', 'auditoria',
]
export const SECUENCIA_ACMA = ORDEN.map((id) => {
  const modulo = MODULOS.find((m) => m.id === id)
  if (!modulo) throw new Error('El módulo ' + id + ' no está en la navegación ACMA')
  return modulo
})

const PRUEBAS: Record<string, Chequeo[]> = {
  biblioteca: [
    { ruta: '/catalogos/tipos-equipo', tipo: 'lista', titulo: 'Tipos de equipo disponibles' },
    { ruta: '/biblioteca/manuales', tipo: 'lista', titulo: 'Consulta de manuales y fichas' },
    { ruta: '/biblioteca/contenido', tipo: 'lista', titulo: 'Contenido técnico de servicio' },
  ],
  operaciones: [{ ruta: '/operacion/tablero', tipo: 'objeto', titulo: 'Tablero en tiempo real' }],
  folios: [
    { ruta: '/folios', tipo: 'lista', titulo: 'Listado de folios' },
    { ruta: '/folios/transiciones', tipo: 'json', titulo: 'Transiciones permitidas' },
  ],
  preventivos: [
    { ruta: '/preventivos/calendario', tipo: 'lista', titulo: 'Calendario del mes DEMO', params: { mes: 'actual', tenant_id: '@demoTenant' } },
    { ruta: '/planes', tipo: 'lista', titulo: 'Planes del prestador DEMO', params: { prestador_id: '@demoPrestador' } },
  ],
  reasignaciones: [{ ruta: '/reasignaciones/reporte', tipo: 'json', titulo: 'Reporte de reasignaciones' }],
  notificaciones: [
    { ruta: '/notificaciones', tipo: 'json', titulo: 'Bandeja de notificaciones' },
    { ruta: '/notificaciones/preferencias', tipo: 'json', titulo: 'Preferencias de notificación' },
  ],
  minuta: [{ ruta: '/minutas', tipo: 'json', titulo: 'Minutas de jornada' }],
  seguimiento: [
    { ruta: '/seguimiento/periodos-presupuestales', tipo: 'nullable', titulo: 'Período presupuestal del cliente DEMO', params: { tenant_id: '@demoTenant' } },
  ],
  clasificacion: [
    { ruta: '/clasificacion/pendientes', tipo: 'json', titulo: 'Folios pendientes de clasificar' },
  ],
  trabajos_especiales: [{ ruta: '/trabajos-especiales', tipo: 'json', titulo: 'Trabajos especiales' }],
  oc_activos: [{ ruta: '/oc-activos/pendientes', tipo: 'json', titulo: 'Órdenes de compra pendientes' }],
  inventario: [
    { ruta: '/inventario/articulos', tipo: 'lista', titulo: 'Catálogo de artículos' },
    { ruta: '/inventario/ubicaciones', tipo: 'lista', titulo: 'Ubicaciones de inventario' },
  ],
  caja_chica: [{ ruta: '/caja-chica/fondos', tipo: 'json', titulo: 'Fondos de caja chica' }],
  presupuestos: [{ ruta: '/presupuestos', tipo: 'json', titulo: 'Presupuestos registrados' }],
  activos: [{ ruta: '/activos', tipo: 'json', titulo: 'Activos registrados' }],
  medidores: [
    { ruta: '/medidores/tipos', tipo: 'json', titulo: 'Tipos de medidor' },
    { ruta: '/medidores/lecturas/por-revisar', tipo: 'json', titulo: 'Lecturas por revisar' },
  ],
  rutas: [
    { ruta: '/rutas/mercados', tipo: 'lista', titulo: 'Mercados del prestador DEMO', params: { prestador_id: '@demoPrestador' } },
    { ruta: '/rutas/tiempos-servicio', tipo: 'lista', titulo: 'Tiempos de servicio del prestador DEMO', params: { prestador_id: '@demoPrestador' } },
  ],
  iso55000: [
    { ruta: '/criticidad/guia', tipo: 'json', titulo: 'Guía de criticidad sin crear configuración' },
    { ruta: '/criticidad/resumen', tipo: 'json', titulo: 'Resumen ISO 55000 del cliente DEMO', params: { tenant_id: '@demoTenant' } },
  ],
  erp: [
    { ruta: '/erp/exportaciones', tipo: 'lista', titulo: 'Exportaciones ERP (sin generar nuevas)' },
    { ruta: '/erp/eventos', tipo: 'json', titulo: 'Eventos de integración' },
  ],
  sla: [{ ruta: '/contratos', tipo: 'lista', titulo: 'Contratos disponibles para calcular SLA' }],
  bi: [{ ruta: '/bi/tablero', tipo: 'json', titulo: 'Indicadores BI' }],
  mensajeria: [
    { ruta: '/mensajeria/configuracion', tipo: 'nullable', titulo: 'Configuración de mensajería del prestador DEMO', params: { prestador_id: '@demoPrestador' } },
    { ruta: '/mensajeria/consumo', tipo: 'json', titulo: 'Consumo del prestador DEMO (sin enviar mensajes)', params: { prestador_id: '@demoPrestador' } },
  ],
  usuarios: [{ ruta: '/usuarios', tipo: 'lista', titulo: 'Listado de usuarios (sin modificaciones)' }],
  tenants: [{ ruta: '/tenants', tipo: 'lista', titulo: 'Clientes registrados' }],
  prestadores: [{ ruta: '/prestadores', tipo: 'lista', titulo: 'Prestadores registrados' }],
  unidades: [
    { ruta: '/unidades-negocio', tipo: 'lista', titulo: 'Unidades de negocio' },
    { ruta: '/grupos-un', tipo: 'lista', titulo: 'Grupos de unidades' },
  ],
  contratos: [{ ruta: '/contratos', tipo: 'lista', titulo: 'Contratos y vigencias' }],
  alertas: [
    { ruta: '/alertas/configuracion', tipo: 'json', titulo: 'Configuración de alertas del prestador DEMO', params: { prestador_id: '@demoPrestador' } },
    { ruta: '/alertas/catalogo', tipo: 'json', titulo: 'Catálogo de alertas' },
  ],
  capacitacion: [
    { ruta: '/capacitacion/cursos', tipo: 'lista', titulo: 'Cursos' },
    // El backend exige actor.prestador_id, que la cuenta Superadmin no tiene.
    // No se invoca ni se confunde con un error funcional del módulo.
  ],
  auditoria: [{ ruta: '/auditoria/eventos', tipo: 'json', titulo: 'Bitácora de auditoría' }],
}

const PRESTADOR_DEMO = 'MANTENIMIENTO DEMO ACMA SA DE CV'
const TENANT_DEMO = 'EMPRESA DEMO ACMA SA DE CV'
type Ambito = { id: string; razon_social: string; estado: string }
function normalizar(valor: string): string {
  return valor.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase().replace(/\s+/g, ' ').trim()
}
/** Nunca elige "el primer cliente": exige una única coincidencia exacta y activa de DEMO. */
async function obtenerAmbitoDemostracion(tipo: '@demoTenant' | '@demoPrestador'): Promise<string> {
  const ruta = tipo === '@demoTenant' ? '/tenants' : '/prestadores'
  const esperado = tipo === '@demoTenant' ? TENANT_DEMO : PRESTADOR_DEMO
  const lista = await api<Ambito[]>(ruta)
  if (!Array.isArray(lista)) throw new Error('No se pudo obtener ' + ruta)
  const exactos = lista.filter((r) => normalizar(r.razon_social) === esperado && r.estado === 'activo')
  if (exactos.length !== 1) {
    throw new Error('Se requiere exactamente un registro DEMO activo en ' + ruta + ', se encontraron ' + exactos.length)
  }
  return exactos[0]!.id
}

function estructuraCorrecta(tipo: TipoRespuesta, datos: unknown): boolean {
  if (tipo === 'nullable') return datos === null || !!datos && typeof datos === 'object'
  if (tipo === 'lista') return Array.isArray(datos)
  if (tipo === 'objeto') return !!datos && typeof datos === 'object' && !Array.isArray(datos)
  return datos !== undefined && datos !== null && typeof datos === 'object'
}
function detalleError(e: unknown): string {
  if (e instanceof Error) return e.message
  return String(e)
}

/** No se hacen escrituras en esta fase; se evita alterar operaciones reales. */
export async function probarModuloLectura(id: string): Promise<ResultadoModulo> {
  const modulo = SECUENCIA_ACMA.find((m) => m.id === id)
  if (!modulo) throw new Error('Módulo fuera de la secuencia de ACMA: ' + id)
  const ahora = new Date().toISOString()
  if (id === 'app_campo') {
    return {
      id, nombre: modulo.nombre, comprobadoEn: ahora, estado: 'requiere_otro_rol',
      mensaje: 'La captura real de campo requiere probar con cuentas Técnico y Operador. No se simuló su sesión.',
      detalles: ['Pendiente: captura de folio, uso sin conexión y sincronización por rol.'],
    }
  }
  const checks = PRUEBAS[id]
  if (!checks?.length) {
    return { id, nombre: modulo.nombre, comprobadoEn: ahora, estado: 'pendiente_funcional',
      mensaje: 'No existe aún una prueba segura para este módulo.',
      detalles: ['Pendiente de implementar un ejecutor específico.'] }
  }
  const detalles: string[] = []
  try {
    const cacheAmbito: Partial<Record<'@demoTenant' | '@demoPrestador', string>> = {}
    let faltaConfiguracion = false
    for (const check of checks) {
      const entradas = check.params ? Object.entries(check.params) : []
      const params: Record<string, string> = {}
      for (const [key, valor] of entradas) {
        if (valor === 'actual') params[key] = new Date().toISOString().slice(0, 7)
        else if (valor === '@demoTenant' || valor === '@demoPrestador') {
          if (!cacheAmbito[valor]) cacheAmbito[valor] = await obtenerAmbitoDemostracion(valor)
          params[key] = cacheAmbito[valor]!
        } else params[key] = valor
      }
      const datos = await api<unknown>(check.ruta, { params })
      if (!estructuraCorrecta(check.tipo, datos)) {
        throw new Error('El servidor devolvió una estructura inesperada en ' + check.titulo)
      }
      if (check.tipo === 'nullable' && datos === null) {
        faltaConfiguracion = true
        detalles.push('• ' + check.titulo + ' — no configurado; el servidor respondió null (permitido)')
      } else {
        detalles.push('✓ ' + check.titulo + ' — consulta confirmada')
      }
    }
    if (id === 'capacitacion') {
      detalles.push('• Vencimientos de certificaciones — pendiente con una cuenta Admin prestador; el backend exige actor.prestador_id')
      return { id, nombre: modulo.nombre, comprobadoEn: ahora, estado: 'requiere_otro_rol',
        mensaje: 'Catálogo de cursos consultado. Los vencimientos requieren una sesión asociada a un prestador.',
        detalles }
    }
    if (faltaConfiguracion) {
      return { id, nombre: modulo.nombre, comprobadoEn: ahora, estado: 'pendiente_funcional',
        mensaje: 'Consulta válida, pero falta una configuración opcional DEMO. No es un error del servidor.',
        detalles }
    }
    return { id, nombre: modulo.nombre, comprobadoEn: ahora, estado: 'consulta_verificada',
      mensaje: 'Consultas del servidor verificadas. La prueba funcional de altas, cambios y permisos sigue pendiente.',
      detalles }
  } catch (error) {
    detalles.push('ERROR: ' + detalleError(error))
    return { id, nombre: modulo.nombre, comprobadoEn: ahora, estado: 'error',
      mensaje: 'Error real durante la consulta. Se conserva el fallo y el recorrido puede continuar.',
      detalles }
  }
}

/**
 * Ejecuta primero las comprobaciones originales y, solo con autorización en la interfaz,
 * hace pruebas reales sobre datos DEMO. Una escritura fallida nunca se etiqueta como OK.
 */
export async function probarModuloDemo(id: string, habilitarEscrituras: boolean): Promise<ResultadoModulo> {
  const lectura = await probarModuloLectura(id)
  if (!habilitarEscrituras || lectura.estado === 'error' || lectura.estado === 'requiere_otro_rol') {
    return lectura
  }
  try {
    const funcional = await ejecutarEscrituraDemo(id)
    if (!funcional) return lectura
    // Repetir GET después de escribir: se detecta también cualquier fallo de relectura.
    const posterior = await probarModuloLectura(id)
    if (posterior.estado === 'error') return posterior
    return {
      ...posterior,
      estado: funcional.estado,
      mensaje: funcional.mensaje,
      detalles: [...posterior.detalles, ...funcional.detalles],
    }
  } catch (error) {
    return { ...lectura, estado: 'error',
      mensaje: 'Falló una prueba real de alta o edición DEMO. No se tocaron registros ajenos al ámbito.',
      detalles: [...lectura.detalles, 'ERROR funcional: ' + detalleError(error)] }
  }
}

export function siguienteModulo(estado: EstadoRecorrido) {
  return SECUENCIA_ACMA[estado.indice] ?? null
}

export function guardarResultado(estado: EstadoRecorrido, resultado: ResultadoModulo): EstadoRecorrido {
  const esperado = siguienteModulo(estado)
  if (!esperado || esperado.id !== resultado.id) throw new Error('Prueba fuera de secuencia')
  return {
    indice: estado.indice + 1,
    resultados: [...estado.resultados.filter((r) => r.id !== resultado.id), resultado],
  }
}
