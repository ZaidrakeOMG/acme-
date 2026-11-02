/** Cliente de /api/inventario, /api/caja-chica, /api/presupuestos, /api/erp y /api/activos (P09). */
import type {
  ActivoResumen, AlertaReemplazo, Articulo, Consolidado, ConsumoPresupuesto, ErpConfig, EventoERP, Existencia, Exportacion, FichaActivo, Financiero,
  Fondo, Gasto, GastoAprobado, MetodoDepreciacion, Movimiento, OrdenCompra, Poliza, Presupuesto, ResultadoOCR, Tarifa, Ubicacion,
} from '../types/inventario'
import { api, descargar } from './api'

type Params = Record<string, string | number | boolean | null | undefined>

// ------------------------------------------------------------- inventario
export const listarArticulos = (params: Params = {}) => api<Articulo[]>('/inventario/articulos', { params })
export const crearArticulo = (datos: Partial<Articulo>) => api<Articulo>('/inventario/articulos', { metodo: 'POST', cuerpo: datos })
export const editarArticulo = (id: string, datos: Partial<Articulo>) => api<Articulo>(`/inventario/articulos/${id}`, { metodo: 'PUT', cuerpo: datos })
export const listarUbicaciones = (params: Params = {}) => api<Ubicacion[]>('/inventario/ubicaciones', { params })
export const crearUbicacion = (datos: Partial<Ubicacion>) => api<Ubicacion>('/inventario/ubicaciones', { metodo: 'POST', cuerpo: datos })
export const listarExistencias = (params: Params = {}) => api<Existencia[]>('/inventario/existencias', { params })
export const listarMovimientos = (params: Params = {}) => api<Movimiento[]>('/inventario/movimientos', { params })
export const entradaInventario = (datos: { articulo_id: string; ubicacion_id: string; cantidad: string; costo_unitario?: string | null; referencia?: string; razon?: string }) =>
  api<Movimiento>('/inventario/movimientos/entrada', { metodo: 'POST', cuerpo: datos })
export const traspasoInventario = (datos: { articulo_id: string; origen_id: string; destino_id: string; cantidad: string; razon?: string }) =>
  api<Movimiento>('/inventario/movimientos/traspaso', { metodo: 'POST', cuerpo: datos })
export const ajusteInventario = (datos: { articulo_id: string; ubicacion_id: string; cantidad: string; razon: string }) =>
  api<Movimiento>('/inventario/movimientos/ajuste', { metodo: 'POST', cuerpo: datos })

export const listarOCs = (params: Params = {}) => api<OrdenCompra[]>('/inventario/ordenes-compra', { params })
export const obtenerOC = (id: string) => api<OrdenCompra>(`/inventario/ordenes-compra/${id}`)
export const crearOC = (datos: { proveedor: string; partidas: { articulo_id: string; cantidad: string; costo_unitario?: string }[]; folio_id?: string | null; notas?: string }) =>
  api<OrdenCompra>('/inventario/ordenes-compra', { metodo: 'POST', cuerpo: datos })
export const aprobarOC = (id: string) => api<OrdenCompra>(`/inventario/ordenes-compra/${id}/aprobar`, { metodo: 'POST' })
export const recibirOC = (id: string, recibidas: Record<string, string> = {}) => api<OrdenCompra>(`/inventario/ordenes-compra/${id}/recibir`, { metodo: 'POST', cuerpo: { recibidas } })
export const cancelarOC = (id: string, razon: string) => api<OrdenCompra>(`/inventario/ordenes-compra/${id}/cancelar`, { metodo: 'POST', cuerpo: { razon } })

// ------------------------------------------------------------- caja chica
export const listarFondos = () => api<Fondo[]>('/caja-chica/fondos')
export const crearFondo = (datos: { tecnico_id: string; monto_inicial: string; umbral_alerta_pct?: string }) => api<Fondo>('/caja-chica/fondos', { metodo: 'POST', cuerpo: datos })
export const reponerFondo = (id: string, monto?: string | null) => api<Fondo>(`/caja-chica/fondos/${id}/reponer`, { metodo: 'POST', cuerpo: { monto: monto ?? null } })
export const listarGastos = (params: Params = {}) => api<Gasto[]>('/caja-chica/gastos', { params })
export const capturarGasto = (datos: Record<string, unknown>) => api<Gasto>('/caja-chica/gastos', { metodo: 'POST', cuerpo: datos })
export const aprobarGasto = (id: string) => api<GastoAprobado>(`/caja-chica/gastos/${id}/aprobar`, { metodo: 'POST' })
export const rechazarGasto = (id: string, razon: string) => api<Gasto>(`/caja-chica/gastos/${id}/rechazar`, { metodo: 'POST', cuerpo: { razon } })
export const extraerOCR = (imagen_base64: string, mime = 'image/jpeg') => api<ResultadoOCR>('/caja-chica/ocr', { metodo: 'POST', cuerpo: { imagen_base64, mime } })
export const imagenGasto = (id: string) => descargar(`/caja-chica/gastos/${id}/imagen`)
export const listarPolizas = () => api<Poliza[]>('/caja-chica/polizas')
export const generarPoliza = (params: Params = {}) => api<Poliza | null>('/caja-chica/polizas', { metodo: 'POST', params })
export const archivoPoliza = (id: string, formato: 'xlsx' | 'xml') => descargar(`/caja-chica/polizas/${id}/archivo`, { formato })

// --------------------------------------------------------- costo del folio
export const costosDelFolio = (folioId: string) => api<Financiero>(`/folios/${folioId}/costos`)
export const validarCosto = (folioId: string, datos: { ajuste?: string | null; razon_ajuste?: string; costo_otros?: string | null; centro_costos?: string | null }) =>
  api<Financiero>(`/folios/${folioId}/costos/validar`, { metodo: 'POST', cuerpo: datos })

// ------------------------------------------------------------ presupuestos
export const listarPresupuestos = (params: Params = {}) => api<Presupuesto[]>('/presupuestos', { params })
export const consolidado = (params: Params = {}) => api<Consolidado>('/presupuestos/consolidado', { params })
export const crearPresupuesto = (datos: Record<string, unknown>) => api<Presupuesto>('/presupuestos', { metodo: 'POST', cuerpo: datos })
export const editarPresupuesto = (id: string, datos: Record<string, unknown>) => api<Presupuesto>(`/presupuestos/${id}`, { metodo: 'PUT', cuerpo: datos })
export const consumosPresupuesto = (id: string) => api<ConsumoPresupuesto[]>(`/presupuestos/${id}/consumos`)
export const listarTarifas = () => api<Tarifa[]>('/presupuestos/tarifas')
export const crearTarifa = (datos: Record<string, unknown>) => api<Tarifa>('/presupuestos/tarifas', { metodo: 'POST', cuerpo: datos })

// -------------------------------------------------------------------- ERP
export const erpConfiguracion = () => api<ErpConfig>('/erp/configuracion')
export const guardarErpConfiguracion = (datos: Record<string, unknown>) => api<ErpConfig>('/erp/configuracion', { metodo: 'PUT', cuerpo: datos })
export const eventosERP = (params: Params = {}) => api<EventoERP[]>('/erp/eventos', { params })
export const procesarEventoERP = (id: string) => api<EventoERP>(`/erp/eventos/${id}/procesar`, { metodo: 'POST' })
export const exportaciones = () => api<Exportacion[]>('/erp/exportaciones')
export const exportarERP = (desde: string, hasta: string) => api<Exportacion>('/erp/exportaciones', { metodo: 'POST', cuerpo: { desde, hasta } })
export const archivoExportacion = (id: string, formato: 'xlsx' | 'xml') => descargar(`/erp/exportaciones/${id}/archivo`, { formato })

// ---------------------------------------------------------------- activos
export const listarActivos = (params: Params = {}) => api<ActivoResumen[]>('/activos', { params })
export const fichaActivo = (equipoId: string) => api<FichaActivo>(`/activos/${equipoId}`)
export const guardarDatosEconomicos = (equipoId: string, datos: Record<string, unknown>) => api<FichaActivo>(`/activos/${equipoId}/datos-economicos`, { metodo: 'PUT', cuerpo: datos })
export const guardarDepreciacion = (equipoId: string, datos: { metodo?: MetodoDepreciacion } & Record<string, unknown>) =>
  api<FichaActivo>(`/activos/${equipoId}/depreciacion`, { metodo: 'PUT', cuerpo: datos })
export const recalcularActivo = (equipoId: string) => api<FichaActivo>(`/activos/${equipoId}/calcular`, { metodo: 'POST' })
export const alertasReemplazo = (pendientes = true) => api<AlertaReemplazo[]>('/activos/alertas-reemplazo', { params: { pendientes } })
export const decidirReemplazo = (alertaId: string, decision: 'aceptado' | 'pospuesto', razon = '') =>
  api<{ alerta: AlertaReemplazo; trabajo_especial: { id: string; numero: string; estado: string } | null }>(`/activos/alertas-reemplazo/${alertaId}/decidir`, { metodo: 'POST', cuerpo: { decision, razon } })
export const guardarUmbralReemplazo = (umbral_reemplazo_pct: string) => api<{ umbral_reemplazo_pct: number }>('/activos/umbral-reemplazo', { metodo: 'PUT', cuerpo: { umbral_reemplazo_pct } })
