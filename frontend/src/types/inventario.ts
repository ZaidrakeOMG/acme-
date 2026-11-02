/** Inventario, caja chica, costos del folio, presupuestos, ERP y activos (§6.4–§6.6, §6.8.5, §6.9.4). P09. */
import type { Rol } from './api'

// ------------------------------------------------------------- inventario
export type TipoUbicacion = 'almacen' | 'vehiculo'
export type TipoMovimiento = 'entrada' | 'salida' | 'traspaso' | 'ajuste' | 'consumo_folio'
export type OrigenRefaccion = 'almacen' | 'oc' | 'caja_chica'
export const ESTADOS_OC = ['borrador', 'aprobada', 'enviada_erp', 'recibida', 'cancelada'] as const
export type EstadoOC = (typeof ESTADOS_OC)[number]
export const NOMBRE_ESTADO_OC: Record<EstadoOC, string> = {
  borrador: 'Borrador', aprobada: 'Aprobada', enviada_erp: 'Enviada al ERP', recibida: 'Recibida', cancelada: 'Cancelada',
}
export const NOMBRE_MOVIMIENTO: Record<TipoMovimiento, string> = {
  entrada: 'Entrada', salida: 'Salida', traspaso: 'Traspaso', ajuste: 'Ajuste', consumo_folio: 'Consumo en folio',
}
export const NOMBRE_ORIGEN: Record<OrigenRefaccion, string> = { almacen: 'Almacén', oc: 'Orden de compra', caja_chica: 'Caja chica' }

export interface Articulo {
  id: string; prestador_id: string; codigo: string; numero_parte: string | null; descripcion: string; unidad: string; categoria: string
  costo_unitario_vigente: string; stock_minimo_default: string; activo: boolean; created_at: string; updated_at: string
}
export interface Ubicacion {
  id: string; prestador_id: string; tipo: TipoUbicacion; nombre: string; tecnico_id: string | null; placas: string | null; activo: boolean
  created_at: string; updated_at: string
}
export interface Existencia {
  id: string; ubicacion_id: string; ubicacion: string; ubicacion_tipo: string; articulo_id: string; codigo: string; descripcion: string
  unidad: string; categoria: string; cantidad: string; stock_minimo: string; costo_promedio: string; bajo_minimo: boolean; updated_at: string
}
export interface Movimiento {
  id: string; timestamp: string; tipo: TipoMovimiento; origen: OrigenRefaccion; cantidad: string; costo_unitario: string; articulo_id: string
  codigo: string | null; descripcion: string | null; ubicacion_origen: string | null; ubicacion_destino: string | null; folio_id: string | null
  numero_folio: string | null; razon: string; referencia_externa: string | null; registrado_por: string | null
}
export interface PartidaOC { id: string; articulo_id: string; codigo: string | null; descripcion: string | null; cantidad: string; costo_unitario: string; recibido: string }
export interface OrdenCompra {
  id: string; prestador_id: string; tenant_id: string | null; numero: string; folio_id: string | null; numero_folio: string | null; proveedor: string
  estado: EstadoOC; estado_desde: string; total: string; moneda: string; ubicacion_destino_id: string | null; notas: string
  aprobada_por: string | null; aprobada_at: string | null; recibida_at: string | null; razon_cancelacion: string | null; numero_oc_erp: string | null
  created_by: string | null; partidas: PartidaOC[]; created_at: string; updated_at: string
}

// ------------------------------------------------------------- caja chica
export type EstadoGasto = 'capturado' | 'aprobado' | 'rechazado'
export type EstadoCFDI = 'no_validado' | 'vigente' | 'cancelado' | 'no_encontrado'
export const NOMBRE_ESTADO_GASTO: Record<EstadoGasto, string> = { capturado: 'Por aprobar', aprobado: 'Aprobado', rechazado: 'Rechazado' }

export interface Fondo {
  id: string; prestador_id: string; tecnico_id: string; tecnico_nombre: string | null; monto_inicial: string; saldo_actual: string; moneda: string
  umbral_alerta_pct: string; porcentaje_saldo: string; bajo_umbral: boolean; gastos_pendientes: number; fecha_ultima_reposicion: string | null
  activo: boolean; created_at: string; updated_at: string
}
export interface Gasto {
  id: string; prestador_id: string; tenant_id: string | null; fondo_id: string; folio_id: string | null; numero_folio: string | null
  tecnico_id: string; tecnico_nombre: string | null; proveedor: string; rfc_proveedor: string | null; uuid_cfdi: string | null; descripcion: string
  numero_parte: string | null; articulo_id: string | null; articulo_codigo: string | null; cantidad: string; subtotal: string; iva: string; monto: string
  estado: EstadoGasto; estado_cfdi: EstadoCFDI; imagen_disponible: boolean; aprobado_por: string | null; aprobado_por_nombre: string | null
  aprobado_at: string | null; razon_rechazo: string | null; centro_costos: string; cuenta_contable: string; poliza_id: string | null
  timestamp: string; created_at: string; updated_at: string
}
export interface GastoAprobado { gasto: Gasto; refaccion_id: string | null; movimientos: string[]; saldo_fondo: string }
export interface Poliza {
  id: string; prestador_id: string; fondo_id: string | null; fecha: string; total: string; gastos: number; formato: string; estado: string
  generado_por: string | null; archivo_disponible: boolean; xml_disponible: boolean; created_at: string; updated_at: string
}
export interface ResultadoOCR { disponible: boolean; detalle: string; proveedor?: string | null; rfc_proveedor?: string | null; uuid_cfdi?: string | null; descripcion?: string | null; subtotal?: string | null; iva?: string | null; total?: string | null }

// -------------------------------------------------------- costo del folio
export interface CostoFolio {
  id: string; costo_refacciones: string; costo_mano_obra: string; costo_otros: string; costo_total: string; moneda: string
  horas_mano_obra: string; tarifa_hora: string; origen_horas: string; ajuste: string; razon_ajuste: string; centro_costos: string
  validado_por: string | null; validado_por_nombre: string | null; validado_at: string | null; documento_erp_ref: string | null
}
export interface RefaccionCosto { id: string; descripcion: string; cantidad: string; costo_unitario: string | null; origen: OrigenRefaccion; articulo_id: string | null; importe: string | null }
export interface Financiero {
  visible: boolean; motivo?: string | null; costo: CostoFolio | null; refacciones: RefaccionCosto[]; gastos_caja_chica: Gasto[]; puede_validar: boolean
}
export interface Tarifa { id: string; prestador_id: string; tenant_id: string | null; tipo_folio: string | null; tarifa_hora: string; moneda: string; vigente_desde: string; activa: boolean; created_at: string; updated_at: string }

// ------------------------------------------------------------ presupuestos
export type TipoActividad = 'correctivo' | 'preventivo' | 'especial' | 'todos'
export const NOMBRE_TIPO_ACTIVIDAD: Record<TipoActividad, string> = { correctivo: 'Correctivos', preventivo: 'Preventivos', especial: 'Trabajos especiales', todos: 'Todas las actividades' }
export const NOMBRE_SEMAFORO: Record<string, string> = { verde: 'Dentro del presupuesto', amarillo: 'Cerca del límite', rojo: 'Excedido' }

export interface Presupuesto {
  id: string; tenant_id: string; un_id: string | null; grupo_id: string | null; nombre: string; un_codigo: string | null; un_nombre: string | null
  grupo_nombre: string | null; tipo_actividad: TipoActividad; periodo_inicio: string; periodo_fin: string; monto: string; moneda: string
  umbrales_alerta_json: number[]; activo: boolean; consumido: string; comprometido: string; disponible: string; porcentaje: string
  desviacion: string; semaforo: 'verde' | 'amarillo' | 'rojo'; created_at: string; updated_at: string
}
export interface ConsumoPresupuesto { id: string; folio_id: string | null; numero_folio: string | null; descripcion: string | null; un_id: string | null; un_codigo: string | null; monto: string; fecha: string; tipo: string; created_at: string }
export interface NivelConsolidado {
  id: string | null; nombre: string | null; monto: string; consumido: string; comprometido: string; disponible: string; porcentaje: string
  desviacion: string; semaforo: 'verde' | 'amarillo' | 'rojo'; presupuestos: Presupuesto[]
}
export interface Consolidado { tenant: NivelConsolidado; grupos: NivelConsolidado[]; unidades: NivelConsolidado[]; presupuestos: Presupuesto[] }

// -------------------------------------------------------------------- ERP
export type AdaptadorERP = 'ninguno' | 'contpaqi' | 'microsip'
export type EstadoEventoERP = 'pendiente' | 'procesado' | 'error' | 'omitido'
export type OperacionERP = 'generar_oc' | 'registrar_gasto' | 'crear_activo_fijo' | 'poliza_caja_chica'
export const NOMBRE_OPERACION: Record<OperacionERP, string> = {
  generar_oc: 'Generar orden de compra', registrar_gasto: 'Registrar gasto en centro de costos', crear_activo_fijo: 'Crear activo fijo',
  poliza_caja_chica: 'Póliza de reposición de caja chica',
}
export const NOMBRE_ESTADO_EVENTO: Record<EstadoEventoERP, string> = { pendiente: 'Pendiente', procesado: 'Procesado', error: 'Con error', omitido: 'Omitido' }

export interface ErpConfig {
  id: string; prestador_id: string; adaptador: AdaptadorERP; columnas_excel_json: string[]; cuentas_contables_json: Record<string, string>
  centros_costos_json: Record<string, string>; exportacion_automatica: boolean
  adaptadores_disponibles: { clave: string; nombre: string; fase: number }[]; created_at: string; updated_at: string
}
export interface EventoERP {
  id: string; prestador_id: string; tenant_id: string | null; operacion: OperacionERP; entidad: string; entidad_id: string | null
  payload_json: Record<string, unknown>; estado: EstadoEventoERP; intentos: number; ultimo_error: string | null; adaptador: AdaptadorERP | null
  respuesta_json: Record<string, unknown>; exportacion_id: string | null; procesado_at: string | null; created_at: string
}
export interface Exportacion { id: string; prestador_id: string; periodo_inicio: string; periodo_fin: string; eventos_incluidos: number; total: string; generado_por: string | null; archivo_disponible: boolean; xml_disponible: boolean; created_at: string; updated_at: string }

// ---------------------------------------------------------------- activos
export type MetodoDepreciacion = 'linea_recta' | 'doble_saldo_decreciente' | 'unidades_produccion' | 'manual'
export const NOMBRE_METODO: Record<MetodoDepreciacion, string> = {
  linea_recta: 'Línea recta', doble_saldo_decreciente: 'Doble saldo decreciente', unidades_produccion: 'Unidades de producción', manual: 'Manual',
}
export const DESCRIPCION_METODO: Record<MetodoDepreciacion, string> = {
  linea_recta: 'El activo pierde el mismo valor cada año; para equipos con desgaste uniforme.',
  doble_saldo_decreciente: 'Mayor depreciación en los primeros años; para equipos tecnológicos o de alto uso inicial.',
  unidades_produccion: 'Proporcional al uso medido; requiere medidores de activos (Fase 2).',
  manual: 'El Admin empresa captura el valor en libros; cuando el ERP del cliente ya lo gestiona.',
}

export interface ActivoResumen {
  id: string; codigo: string; nombre: string; marca: string | null; modelo: string | null; numero_serie: string | null; estado: string
  criticidad: string | null; un_id: string; un_codigo: string | null; un_nombre: string | null; tenant_id: string
  costo_adquisicion: string | null; fecha_adquisicion: string | null; fecha_instalacion: string | null; valor_reposicion: string | null
  numero_activo_fijo_erp: string | null; tco_total: string | null; porcentaje_vs_reposicion: string | null; periodo_tco: string | null
  alerta_reemplazo: boolean; alerta_reemplazo_id: string | null
}
export interface ComponentesTCO {
  periodo: string; costo_adquisicion: string; costo_preventivos: string; costo_correctivos: string; costo_refacciones: string
  costo_downtime: string; horas_downtime: string; valor_residual: string; tco_total: string; valor_reposicion: string | null
  porcentaje_vs_reposicion: string; folios: number; aviso: string
}
export interface AlertaReemplazo {
  id: string; equipo_id: string; tenant_id: string; equipo_codigo: string | null; equipo_nombre: string | null; un_codigo: string | null
  fecha_alerta: string; tco_al_momento: string; valor_reposicion: string; porcentaje_umbral: string; porcentaje_alcanzado: string
  decision: 'aceptado' | 'pospuesto' | null; razon: string; decidido_por: string | null; decidido_at: string | null
  trabajo_especial_id: string | null; created_at: string; updated_at: string
}
export interface FichaActivo {
  equipo: Record<string, string | number | boolean | null>
  contrato: Record<string, string | null> | null
  historial_folios: { id: string; numero_folio: string; tipo_folio: string; estado: string; tipo_falla: string | null; descripcion: string; capturado_at: string; fecha_cierre: string | null; tecnico_nombre: string | null; costo_total: string | null; costo_validado: boolean; plan_nombre: string | null; desvio: string | null }[]
  refacciones: { id: string; descripcion: string; cantidad: string; origen: string; costo_unitario: string | null; folio_id: string; importe: string | null }[]
  depreciacion: { metodo: MetodoDepreciacion; vida_util_anios: number; valor_salvamento: string; valor_reposicion: string | null; unidades_vida_util: string | null; unidades_acumuladas: string; valor_en_libros_manual: string | null; fecha_inicio: string; aviso: string } | null
  depreciacion_historial: { periodo: string; valor_en_libros: string; depreciacion_periodo: string; depreciacion_acumulada: string; metodo_aplicado: string }[]
  tco: ComponentesTCO
  tco_historial: { periodo: string; tco_total: string; porcentaje_vs_reposicion: string; costo_preventivos: string; costo_correctivos: string; costo_refacciones: string; costo_downtime: string; valor_residual: string }[]
  alerta_reemplazo: AlertaReemplazo | null
  umbral_reemplazo_pct: string
  fase_2: string[]
}

export const ROLES_INVENTARIO: Rol[] = ['superadmin', 'admin_prestador', 'despachador', 'mesa_control', 'tecnico', 'direccion_prestador', 'supervisor_prestador']
export const ROLES_ESCRIBEN_INVENTARIO: Rol[] = ['superadmin', 'admin_prestador']
export const ROLES_GESTIONAN_INVENTARIO: Rol[] = ['superadmin', 'admin_prestador', 'despachador', 'mesa_control']
export const ROLES_CAJA_CHICA: Rol[] = ['superadmin', 'admin_prestador', 'despachador', 'mesa_control', 'direccion_prestador', 'tecnico']
export const ROLES_APRUEBAN_GASTO: Rol[] = ['superadmin', 'admin_prestador']
export const ROLES_PRESUPUESTOS: Rol[] = ['superadmin', 'admin_empresa', 'admin_un', 'supervisor_operadores', 'admin_prestador', 'mesa_control', 'direccion_prestador']
export const ROLES_ESCRIBEN_PRESUPUESTO: Rol[] = ['superadmin', 'admin_empresa']
export const ROLES_ACTIVOS: Rol[] = ['superadmin', 'admin_empresa', 'admin_un', 'supervisor_operadores', 'admin_prestador', 'mesa_control', 'despachador', 'direccion_prestador', 'supervisor_prestador']
export const ROLES_ERP: Rol[] = ['superadmin', 'admin_prestador', 'direccion_prestador', 'mesa_control', 'despachador']
export const ROLES_VALIDAN_COSTO: Rol[] = ['superadmin', 'mesa_control', 'admin_prestador']
