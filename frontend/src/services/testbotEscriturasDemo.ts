/**
 * Operaciones reales del TestBot, limitadas al cliente/prestador DEMO.
 * No usa usuarios ficticios, tokens ajenos, pagos, envíos o eliminaciones.
 * Reusa registros identificados por claves exactas para poder reanudar.
 */
import { api } from './api'

export const ETIQUETA_TESTBOT = 'TESTBOT DEMO'
const CLIENTE = 'EMPRESA DEMO ACMA SA DE CV'
const PRESTADOR = 'MANTENIMIENTO DEMO ACMA SA DE CV'

export type TipoVerificacionDemo = 'crud_demo_verificado' | 'alta_demo_verificada'
export type VerificacionDemo = { estado: TipoVerificacionDemo; mensaje: string; detalles: string[] }
type Registro = { id: string; [clave: string]: unknown }
type Ambito = Registro & { razon_social: string; estado: string }
type Contexto = { tenantId: string; prestadorId: string }

function exigir(valor: unknown, descripcion: string): asserts valor {
  if (!valor) throw new Error(descripcion)
}
function normalizar(s: string): string {
  return s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/\s+/g, ' ').trim().toUpperCase()
}
function unico<T>(filas: T[], descripcion: string): T | null {
  exigir(filas.length <= 1, 'Hay duplicados de ' + descripcion + ': revisar manualmente antes de escribir.')
  return filas[0] ?? null
}
function idDe(r: Registro, campo: string, esperado: string) {
  exigir(r[campo] === esperado, 'Bloqueado: ' + campo + ' no corresponde al ámbito DEMO')
}
async function filas(ruta: string, params: Record<string, string> = {}): Promise<Registro[]> {
  const r = await api<unknown>(ruta, { params })
  exigir(Array.isArray(r), 'La API no devolvió una lista en ' + ruta)
  return r as Registro[]
}
async function contexto(): Promise<Contexto> {
  const [tenants, prestadores] = await Promise.all([filas('/tenants'), filas('/prestadores')])
  const t = unico(tenants.filter(x => normalizar(String(x.razon_social ?? '')) === CLIENTE && x.estado === 'activo'), 'cliente DEMO')
  const p = unico(prestadores.filter(x => normalizar(String(x.razon_social ?? '')) === PRESTADOR && x.estado === 'activo'), 'prestador DEMO')
  exigir(t && p, 'Falta el cliente o prestador DEMO activo. No se hizo ninguna escritura.')
  const vinculos = await filas('/tenants/' + t.id + '/prestadores')
  const activos = vinculos.filter(x => x.estado === 'activo')
  exigir(activos.length === 1 && activos[0]?.prestador_id === p.id,
    'El cliente DEMO debe tener únicamente al prestador DEMO activo para que las escrituras sean seguras.')
  return { tenantId: t.id, prestadorId: p.id }
}
function resultado(mensaje: string, detalles: string[], crud = false): VerificacionDemo {
  return { estado: crud ? 'crud_demo_verificado' : 'alta_demo_verificada', mensaje, detalles }
}

/** Una UN aislada para toda la simulación; no toma la primera unidad real. */
async function unidad(ctx: Contexto): Promise<Registro> {
  const codigo = 'TESTBOT-DEMO-UN'
  const disponibles = await filas('/unidades-negocio', { tenant_id: ctx.tenantId })
  let u = unico(disponibles.filter(x => x.codigo === codigo && x.tenant_id === ctx.tenantId), 'unidad DEMO')
  if (!u) {
    u = await api<Registro>('/unidades-negocio', { metodo: 'POST', cuerpo: {
      tenant_id: ctx.tenantId, codigo, nombre: 'TESTBOT DEMO - Unidad de pruebas',
      direccion: 'Ubicación ficticia, no usar para servicios',
    } })
  }
  idDe(u, 'tenant_id', ctx.tenantId)
  exigir(u.codigo === codigo, 'La unidad no tiene el código de pruebas.')
  if (u.direccion !== 'Ubicación ficticia - validada por TestBot') {
    await api('/unidades-negocio/' + u.id, { metodo: 'PATCH',
      cuerpo: { direccion: 'Ubicación ficticia - validada por TestBot' } })
  }
  const leida = await api<Registro>('/unidades-negocio/' + u.id)
  idDe(leida, 'tenant_id', ctx.tenantId)
  exigir(leida.codigo === codigo && leida.direccion === 'Ubicación ficticia - validada por TestBot',
    'La creación o edición de la unidad no persistió.')
  return leida
}
async function grupo(ctx: Contexto, un: Registro): Promise<Registro> {
  const nombre = 'TESTBOT DEMO - Grupo de unidades'
  const disponibles = await filas('/grupos-un', { tenant_id: ctx.tenantId })
  let g = unico(disponibles.filter(x => x.nombre === nombre && x.tenant_id === ctx.tenantId), 'grupo DEMO')
  if (!g) {
    g = await api<Registro>('/grupos-un', { metodo: 'POST', cuerpo: {
      tenant_id: ctx.tenantId, nombre, descripcion: 'Grupo ficticio de pruebas',
    } })
  }
  idDe(g, 'tenant_id', ctx.tenantId)
  if (g.descripcion !== 'Validado por TESTBOT DEMO') {
    await api('/grupos-un/' + g.id, { metodo: 'PATCH', cuerpo: { descripcion: 'Validado por TESTBOT DEMO' } })
  }
  const leido = await api<Registro>('/grupos-un/' + g.id)
  idDe(leido, 'tenant_id', ctx.tenantId)
  exigir(leido.nombre === nombre && leido.descripcion === 'Validado por TESTBOT DEMO',
    'El cambio en grupo no persistió.')
  // Solo cambia el grupo que el propio bot creó; nunca reemplaza miembros de un grupo real.
  if (!Array.isArray(leido.unidad_ids) || !leido.unidad_ids.includes(un.id)) {
    await api('/grupos-un/' + g.id + '/unidades', { metodo: 'PUT', cuerpo: { unidad_ids: [un.id] } })
    const vinculado = await api<Registro>('/grupos-un/' + g.id)
    exigir(Array.isArray(vinculado.unidad_ids) && vinculado.unidad_ids.includes(un.id),
      'No se guardó la pertenencia de la unidad DEMO al grupo.')
  }
  return leido
}

async function equipo(ctx: Contexto): Promise<{ equipo: Registro; tipo: Registro; unidad: Registro }> {
  const un = await unidad(ctx)
  // Para no alterar catálogos reales, solo se usan tipos globales ya existentes.
  const tipos = await filas('/catalogos/tipos-equipo')
  const fallas = await filas('/catalogos/tipos-falla', { prestador_id: ctx.prestadorId })
  const tipo = tipos.find(x => x.tenant_id == null && typeof x.familia_id === 'string' &&
    fallas.some(f => f.prestador_id === ctx.prestadorId && f.familia_equipo_id === x.familia_id && f.activa !== false)) ??
    tipos.find(x => x.tenant_id == null && typeof x.familia_id === 'string')
  exigir(tipo, 'No hay tipos globales de equipo: no se fabricó un tipo ajeno al cliente DEMO.')
  const disponibles = await filas('/catalogos/equipos', { tenant_id: ctx.tenantId })
  const codigo = 'TESTBOT-DEMO-EQ'
  let eq = unico(disponibles.filter(x => x.codigo === codigo && x.tenant_id === ctx.tenantId), 'equipo DEMO')
  if (!eq) {
    eq = await api<Registro>('/catalogos/equipos', { metodo: 'POST', params: { tenant_id: ctx.tenantId },
      cuerpo: { un_id: un.id, tipo_equipo_id: tipo.id, codigo,
        nombre: 'TESTBOT DEMO - Equipo ficticio', notas: 'Sin equipo físico asociado' } })
  }
  idDe(eq, 'tenant_id', ctx.tenantId)
  exigir(eq.codigo === codigo && eq.un_id === un.id, 'El equipo de pruebas no pertenece a nuestra UN DEMO.')
  const leido = await api<Registro>('/catalogos/equipos/' + eq.id)
  idDe(leido, 'tenant_id', ctx.tenantId)
  exigir(leido.codigo === codigo, 'El equipo DEMO no quedó guardado.')
  const tipoDelEquipo = tipos.find(x => x.id === leido.tipo_equipo_id)
  exigir(tipoDelEquipo, 'El tipo original del equipo DEMO no está disponible.')
  return { equipo: leido, tipo: tipoDelEquipo, unidad: un }
}

async function inventario(ctx: Contexto): Promise<VerificacionDemo> {
  const codigo = 'TESTBOT-DEMO-ART'
  const articulos = await filas('/inventario/articulos')
  let articulo = unico(articulos.filter(x => x.codigo === codigo && x.prestador_id === ctx.prestadorId), 'artículo DEMO')
  if (!articulo) {
    articulo = await api<Registro>('/inventario/articulos', { metodo: 'POST', cuerpo: {
      prestador_id: ctx.prestadorId, codigo, descripcion: 'Refacción ficticia de pruebas',
      unidad: 'pieza', categoria: 'TESTBOT DEMO', costo_unitario_vigente: 10,
    } })
  }
  idDe(articulo, 'prestador_id', ctx.prestadorId)
  if (articulo.descripcion !== 'Refacción ficticia TESTBOT DEMO validada') {
    articulo = await api<Registro>('/inventario/articulos/' + articulo.id, { metodo: 'PUT',
      cuerpo: { descripcion: 'Refacción ficticia TESTBOT DEMO validada' } })
  }
  const ubicaciones = await filas('/inventario/ubicaciones')
  const nombre = 'TESTBOT DEMO - Almacén ficticio'
  let almacen = unico(ubicaciones.filter(x => x.nombre === nombre && x.prestador_id === ctx.prestadorId), 'almacén DEMO')
  if (!almacen) {
    almacen = await api<Registro>('/inventario/ubicaciones', { metodo: 'POST', cuerpo: {
      prestador_id: ctx.prestadorId, nombre, tipo: 'almacen',
    } })
  }
  idDe(almacen, 'prestador_id', ctx.prestadorId)
  let existencias = await filas('/inventario/existencias', { ubicacion_id: almacen.id, articulo_id: articulo.id })
  let cantidad = Number(existencias.find(x => x.articulo_id === articulo.id && x.ubicacion_id === almacen.id)?.cantidad ?? 0)
  if (cantidad < 5) {
    await api('/inventario/movimientos/entrada', { metodo: 'POST', cuerpo: {
      articulo_id: articulo.id, ubicacion_id: almacen.id, cantidad: 5 - cantidad, costo_unitario: 10,
      referencia: 'TESTBOT DEMO - primera entrada', razon: 'Prueba ficticia de inserción',
    } })
    existencias = await filas('/inventario/existencias', { ubicacion_id: almacen.id, articulo_id: articulo.id })
    cantidad = Number(existencias.find(x => x.articulo_id === articulo.id && x.ubicacion_id === almacen.id)?.cantidad ?? 0)
  }
  exigir(Number.isFinite(cantidad) && cantidad >= 5, 'El movimiento no quedó reflejado en las existencias DEMO.')
  const guardados = await filas('/inventario/articulos')
  exigir(guardados.some(x => x.id === articulo.id && x.prestador_id === ctx.prestadorId &&
    x.descripcion === 'Refacción ficticia TESTBOT DEMO validada'), 'No persistió el cambio del artículo.')
  return resultado('Artículo, almacén, edición y entrada de inventario DEMO verificados.', [
    'Artículo: ' + articulo.id, 'Almacén: ' + almacen.id, 'Existencia comprobada: ' + cantidad + ' piezas',
  ], true)
}

async function presupuesto(ctx: Contexto): Promise<VerificacionDemo> {
  const un = await unidad(ctx)
  const nombre = 'TESTBOT DEMO - Presupuesto ficticio'
  const lista = await filas('/presupuestos', { tenant_id: ctx.tenantId })
  let p = unico(lista.filter(x => x.nombre === nombre && x.tenant_id === ctx.tenantId), 'presupuesto DEMO')
  if (!p) {
    p = await api<Registro>('/presupuestos', { metodo: 'POST', cuerpo: {
      tenant_id: ctx.tenantId, un_id: un.id, nombre, periodo_inicio: '2027-01-01',
      periodo_fin: '2027-12-31', monto: 2500, tipo_actividad: 'todos',
    } })
  }
  idDe(p, 'tenant_id', ctx.tenantId)
  exigir(p.un_id === un.id, 'No se editará un presupuesto de otra UN.')
  if (Number(p.monto) !== 2600) {
    await api('/presupuestos/' + p.id, { metodo: 'PUT', cuerpo: { monto: 2600 } })
  }
  const leido = await api<Registro>('/presupuestos/' + p.id)
  idDe(leido, 'tenant_id', ctx.tenantId)
  exigir(leido.nombre === nombre && Number(leido.monto) === 2600, 'No persistió la edición del presupuesto DEMO.')
  return resultado('Presupuesto DEMO creado, modificado y leído de nuevo.', ['Presupuesto: ' + p.id], true)
}

async function seguimiento(ctx: Contexto): Promise<VerificacionDemo> {
  const params = { tenant_id: ctx.tenantId }
  const actual = await api<Registro | null>('/seguimiento/periodos-presupuestales', { params })
  if (!actual) {
    await api('/seguimiento/periodos-presupuestales', { metodo: 'PUT', params,
      cuerpo: { tipo: 'mensual', fechas: [] } })
  } else {
    idDe(actual, 'tenant_id', ctx.tenantId)
  }
  const nuevo = await api<Registro | null>('/seguimiento/periodos-presupuestales', { params })
  exigir(nuevo && nuevo.tenant_id === ctx.tenantId, 'No se guardó el período DEMO.')
  return resultado('Período presupuestal DEMO configurado y verificado.', [
    'Cliente DEMO: ' + ctx.tenantId, actual ? 'Se reutilizó la configuración existente.' : 'Se creó la configuración mensual.',
  ])
}

async function plan(ctx: Contexto): Promise<VerificacionDemo> {
  const { tipo } = await equipo(ctx)
  const nombre = 'TESTBOT DEMO - Plan de mantenimiento'
  const planes = await filas('/planes', { prestador_id: ctx.prestadorId })
  let p = unico(planes.filter(x => x.nombre === nombre && x.prestador_id === ctx.prestadorId &&
    x.tenant_id === ctx.tenantId), 'plan DEMO')
  if (!p) {
    p = await api<Registro>('/planes', { metodo: 'POST', params: { prestador_id: ctx.prestadorId },
      cuerpo: {
        nombre, descripcion: 'Plan ficticio TESTBOT DEMO',
        tipo_equipo_id: tipo.id, tenant_id: ctx.tenantId, tiempo_ventana_dias: 7,
        triggers: [{ tipo_trigger: 'tiempo_fijo', parametros_json: { cada_dias: 90 } }],
        tareas: [{ orden: 1, descripcion: 'Revisión ficticia TESTBOT DEMO', tiempo_estimado_min: 10 }],
        materiales: [{ descripcion: 'Material de prueba no real', cantidad_estandar: 1, unidad: 'pieza' }],
      } })
  }
  idDe(p, 'prestador_id', ctx.prestadorId)
  idDe(p, 'tenant_id', ctx.tenantId)
  if (p.descripcion !== 'Plan ficticio TESTBOT DEMO verificado') {
    await api('/planes/' + p.id, { metodo: 'PUT', cuerpo: { descripcion: 'Plan ficticio TESTBOT DEMO verificado' } })
  }
  const guardado = await api<Registro>('/planes/' + p.id)
  exigir(guardado.prestador_id === ctx.prestadorId && guardado.tenant_id === ctx.tenantId &&
    guardado.descripcion === 'Plan ficticio TESTBOT DEMO verificado', 'El plan DEMO no persistió.')
  return resultado('Plan preventivo DEMO creado, editado y recuperado.', ['Plan: ' + p.id], true)
}

async function folio(ctx: Contexto): Promise<VerificacionDemo> {
  const { equipo: eq, tipo, unidad: un } = await equipo(ctx)
  const fallas = await filas('/catalogos/tipos-falla', { prestador_id: ctx.prestadorId })
  const falla = fallas.find(f => f.prestador_id === ctx.prestadorId &&
    f.familia_equipo_id === tipo.familia_id && f.activa !== false)
  exigir(falla, 'Falta tipo de falla de la familia del equipo DEMO en el prestador DEMO.')
  const descripcion = 'TESTBOT DEMO - Folio de avería ficticia, no realizar servicio'
  const anteriores = await filas('/folios', { tenant_id: ctx.tenantId })
  let f = unico(anteriores.filter(x => x.tenant_id === ctx.tenantId &&
    x.equipo_id === eq.id && x.descripcion === descripcion), 'folio DEMO')
  if (!f) {
    f = await api<Registro>('/folios', { metodo: 'POST', cuerpo: {
      tenant_id: ctx.tenantId, un_id: un.id, equipo_id: eq.id,
      tipo_falla_id: falla.id, descripcion, tipo_folio: 'correctivo', prioridad: 0,
    } })
  }
  idDe(f, 'tenant_id', ctx.tenantId)
  exigir(f.un_id === un.id && f.equipo_id === eq.id, 'El folio no pertenece al equipo ficticio.')
  const detalle = await api<{ folio: Registro }>('/folios/' + f.id)
  const leido = detalle.folio
  exigir(leido, 'El servidor no devolvió los datos del folio.')
  idDe(leido, 'tenant_id', ctx.tenantId)
  exigir(leido.descripcion === descripcion && leido.equipo_id === eq.id, 'El folio no persistió.')
  return resultado('Folio ficticio insertado y comprobado en el servidor; cierre/asignación requieren roles.', [
    'Folio: ' + String(leido.numero_folio ?? f.id), 'ID: ' + f.id, 'Pendiente: flujo completo con Técnico y Operador.',
  ])
}

async function trabajoEspecial(ctx: Contexto): Promise<VerificacionDemo> {
  const un = await unidad(ctx)
  const descripcion = 'TESTBOT DEMO - Trabajo especial ficticio, sin autorización de ejecución'
  const anteriores = await filas('/trabajos-especiales', { tenant_id: ctx.tenantId })
  let te = unico(anteriores.filter(x => x.tenant_id === ctx.tenantId &&
    x.un_id === un.id && x.descripcion === descripcion), 'trabajo especial DEMO')
  if (!te) {
    te = await api<Registro>('/trabajos-especiales', { metodo: 'POST', cuerpo: {
      un_id: un.id, tenant_id: ctx.tenantId, descripcion,
      detalle: { origen: 'TESTBOT DEMO', alcance: 'Simulación, sin ejecución' }, monto: 100,
    } })
  }
  idDe(te, 'tenant_id', ctx.tenantId)
  exigir(te.un_id === un.id, 'El TE no corresponde a la UN de prueba.')
  const leido = await api<Registro>('/trabajos-especiales/' + te.id)
  idDe(leido, 'tenant_id', ctx.tenantId)
  exigir(leido.descripcion === descripcion, 'El trabajo especial DEMO no persistió.')
  return resultado('Trabajo especial DEMO creado y leído; autorizaciones por rol pendientes.', [
    'Trabajo especial: ' + te.id, 'No se envió al cliente ni se inició intervención real.',
  ])
}

export const MODULOS_CON_ALTAS_DEMO = [
  'folios', 'preventivos', 'seguimiento', 'trabajos_especiales', 'inventario',
  'presupuestos', 'activos', 'unidades',
] as const

/** Retorna null cuando el módulo solo tiene comprobación de consulta o requiere otro rol. */
export async function ejecutarEscrituraDemo(id: string): Promise<VerificacionDemo | null> {
  if (!(MODULOS_CON_ALTAS_DEMO as readonly string[]).includes(id)) return null
  const ctx = await contexto() // se valida antes de cada escritura, incluso al reintentar
  switch (id) {
    case 'unidades': {
      const un = await unidad(ctx)
      const g = await grupo(ctx, un)
      return resultado('UN y grupo DEMO creados, modificados y verificados.', [
        'Unidad: ' + un.id, 'Grupo: ' + g.id,
      ], true)
    }
    case 'activos': {
      const { equipo: eq } = await equipo(ctx)
      return resultado('Activo/equipo DEMO creado y consultado.', ['Activo DEMO: ' + eq.id])
    }
    case 'folios': return folio(ctx)
    case 'preventivos': return plan(ctx)
    case 'seguimiento': return seguimiento(ctx)
    case 'trabajos_especiales': return trabajoEspecial(ctx)
    case 'inventario': return inventario(ctx)
    case 'presupuestos': return presupuesto(ctx)
    default: return null
  }
}
