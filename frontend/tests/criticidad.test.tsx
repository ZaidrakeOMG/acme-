import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { PerfilConTema, Rol } from '../src/types/api'
import type {
  ConfiguracionCriticidad, DetalleCriticidad, EvaluacionHistorial, FilaRegistro, MatrizCriticidad, MatrizRiesgo,
  Mitigacion, MitigacionPendiente, ModoFalla, ResumenCriticidad, SugerenciaModo,
} from '../src/types/criticidad'
import { impactoPonderado, indiceDe, nivelDe, sumaPesos } from '../src/types/criticidad'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const T = '11111111-1111-1111-1111-111111111111'
const EQ = 'e0000000-0000-0000-0000-000000000001'
const MODO = 'm0000000-0000-0000-0000-000000000001'
const MIT = 'c0000000-0000-0000-0000-000000000001'

const GUIA = {
  operacional: { pregunta: '¿Cuánto afecta la falla a la operación de la unidad?', peso_default: 30,
    niveles: { 1: 'Sin impacto', 2: 'Molestia menor', 3: 'Afecta parte de la operación', 4: 'Detiene un proceso importante', 5: 'Cierre total' } },
  seguridad: { pregunta: '¿Puede la falla generar riesgo para personas o instalaciones?', peso_default: 35,
    niveles: { 1: 'Sin riesgo', 2: 'Riesgo leve', 3: 'Riesgo con lesión menor posible', 4: 'Riesgo de lesión seria', 5: 'Riesgo de accidente grave' } },
  economico: { pregunta: '¿Cuál es el costo estimado de la falla?', peso_default: 25,
    niveles: { 1: 'Menor a $5,000', 2: 'De $5,000 a $25,000', 3: 'De $25,000 a $100,000', 4: 'De $100,000 a $500,000', 5: 'Mayor a $500,000' } },
  imagen: { pregunta: '¿Afecta la falla la experiencia del cliente final?', peso_default: 10,
    niveles: { 1: 'Sin impacto visible', 2: 'Lo nota el personal', 3: 'Lo nota algún cliente', 4: 'Lo notan varios clientes', 5: 'Afecta directamente al cliente' } },
} as DetalleCriticidad['guia']

const PESOS = { operacional: 30, seguridad: 35, economico: 25, imagen: 10 }

const sinEvaluar: DetalleCriticidad = {
  evaluado: false, guia: GUIA, pesos: PESOS, meses_revision: 12, nivel_manual: null,
  economico_propuesto: { nivel: 3, texto: 'De $25,000 a $100,000' },
  probabilidad: null, probabilidad_estimada: false, probabilidad_origen: 'historial_equipo',
  probabilidad_detalle: { fallas_12m: 12, meses: 12 }, probabilidad_si_se_evalua: '5.00',
}

const evaluado: DetalleCriticidad = {
  evaluado: true, guia: GUIA, pesos: PESOS, meses_revision: 12,
  nivel: 'A', etiqueta: 'Crítico',
  implicaciones: 'PM obligatorio con plan definido. Respuesta a correctivos máximo 4 horas. Técnico especialista requerido. Refacciones siempre en inventario.',
  indice_criticidad: '86.00', probabilidad: '5.00', probabilidad_estimada: false,
  probabilidad_origen: 'historial_equipo', probabilidad_detalle: { fallas_12m: 13, meses: 12 },
  impacto_ponderado: '4.30', origen: 'calculado', razon_manual: '',
  fecha_evaluacion: '2026-11-11', proxima_revision: '2027-11-06', revision_vencida: false,
  dimensiones: [
    { clave: 'operacional', valor: 5, peso: 30, aporte: '1.50', pregunta: GUIA.operacional.pregunta, texto: 'Cierre total' },
    { clave: 'seguridad', valor: 4, peso: 35, aporte: '1.40', pregunta: GUIA.seguridad.pregunta, texto: 'Riesgo de lesión seria' },
    { clave: 'economico', valor: 4, peso: 25, aporte: '1.00', pregunta: GUIA.economico.pregunta, texto: 'De $100,000 a $500,000' },
    { clave: 'imagen', valor: 4, peso: 10, aporte: '0.40', pregunta: GUIA.imagen.pregunta, texto: 'Lo notan varios clientes' },
  ],
}

const historial: EvaluacionHistorial[] = [{
  id: 'h1', equipo_id: EQ, indice_anterior: '51.60', indice_nuevo: '86.00', nivel_anterior: 'B', nivel_nuevo: 'A',
  probabilidad: '5.00', impacto_ponderado: '4.30', dimensiones_json: { operacional: 5 },
  motivo: 'recalculo_por_historial', razon: 'Recálculo automático con el historial de fallas',
  evaluado_por: null, timestamp: '2026-11-11T10:00:00Z',
}]

const modo: ModoFalla = {
  id: MODO, tenant_id: T, equipo_id: EQ, tipo_equipo_id: null,
  descripcion_falla: 'Pérdida de carga de refrigerante por fuga en el serpentín',
  tipo_falla_id: null, causa_probable: 'Corrosión por condensados',
  efecto_operacional: 'La cámara no sostiene la temperatura', severidad: 5, frecuencia_historica: 4,
  fallas_12m: 7, deteccion: null, nivel_riesgo: 20, origen: 'manual', activo: true, registrado_por: null,
}

const mitigacion: Mitigacion = {
  id: MIT, modo_falla_id: MODO, tenant_id: T, accion_mitigacion: 'Cambiar el empaque de la puerta cada seis meses',
  tipo: 'plan_preventivo', plan_mantenimiento_id: null, curso_id: null, articulo_id: null, responsable_id: null,
  fecha_compromiso: '2026-10-01', fecha_implementacion: null, estado: 'propuesta', efectividad_json: {},
  evidencia_key: null, razon_descarte: '',
}

const sugerencia: SugerenciaModo = {
  descripcion_falla: 'No enfría', tipo_falla_id: 'tf1', causa_probable: 'Falta de mantenimiento',
  severidad: 4, frecuencia_historica: 4, fallas_12m: 7, nivel_riesgo: 16, categoria: 'critico',
  ya_registrado: false, nota: '7 falla(s) en 12 meses; causa más frecuente: Falta de mantenimiento',
}

const ficha = {
  equipo: { id: EQ, codigo: 'EQ-0001', nombre: 'Refrigerador vertical de exhibición', marca: null, modelo: null,
    numero_serie: null, estado: 'operativo', criticidad: 'A', criticidad_origen: 'calculado (ISO 55000 §6.9.3)',
    tipo_equipo: 'Refrigerador vertical', un_id: 'u1', un_codigo: 'SUC-001', un_nombre: 'Sucursal Centro',
    fecha_instalacion: '2024-03-01', fecha_adquisicion: null, costo_adquisicion: null, valor_reposicion: null,
    costo_hora_inactividad: null, numero_activo_fijo_erp: null, garantia_vigente_hasta: null, tenant_id: T },
  contrato: null, historial_folios: [], refacciones: [], depreciacion: null, depreciacion_historial: [],
  tco: { costo_adquisicion: '0', costo_preventivos: '0', costo_correctivos: '0', costo_refacciones: '0',
    costo_downtime: '0', valor_residual: '0', total: '0' },
  tco_historial: [], alerta_reemplazo: null, umbral_reemplazo_pct: '70', fase_2: ['MTBF y MTTR por activo'],
  medidores: [],
}

const registro: FilaRegistro[] = [
  { equipo_id: EQ, codigo: 'EQ-0001', nombre: 'Refrigerador vertical', tipo_equipo: 'Refrigerador vertical',
    un_codigo: 'SUC-001', un_nombre: 'Sucursal Centro', tenant_id: T, nivel: 'A', indice_criticidad: '86.00',
    probabilidad: '5.00', probabilidad_estimada: false, impacto_ponderado: '4.30', origen: 'calculado',
    fecha_evaluacion: '2026-11-11', proxima_revision: '2027-11-06', revision_vencida: false },
  { equipo_id: 'e2', codigo: 'EQ-0012', nombre: 'Lámpara LED', tipo_equipo: 'Lámpara LED de techo',
    un_codigo: 'SUC-003', un_nombre: 'Sucursal Coyoacán', tenant_id: T, nivel: 'D', indice_criticidad: '8.00',
    probabilidad: '2.00', probabilidad_estimada: true, impacto_ponderado: '1.00', origen: 'manual',
    fecha_evaluacion: '2026-11-11', proxima_revision: '2026-10-01', revision_vencida: true },
]

const resumen: ResumenCriticidad = {
  por_nivel: { A: 2, B: 2, C: 4, D: 4 }, total: 12, criticos_sin_plan: 1, criticos_sin_plan_ids: [EQ],
  mitigaciones_vencidas: 2, revisiones_vencidas: 1,
}

const matrizActivos: MatrizCriticidad = {
  total: 2,
  celdas: [
    { probabilidad: 5, impacto: 4, total: 1, equipos: [{ equipo_id: EQ, codigo: 'EQ-0001', nivel: 'A' }] },
    { probabilidad: 2, impacto: 1, total: 1, equipos: [{ equipo_id: 'e2', codigo: 'EQ-0012', nivel: 'D' }] },
  ],
}

const matrizModos: MatrizRiesgo = {
  total: 1, por_categoria: { bajo: 0, medio: 0, alto: 0, critico: 1 },
  celdas: [{ severidad: 5, frecuencia: 4, total: 1, categoria: 'critico',
    modos: [{ id: MODO, descripcion: modo.descripcion_falla, equipo_id: EQ, nivel_riesgo: 20 }] }],
}

const pendientes: MitigacionPendiente[] = [{
  id: MIT, accion_mitigacion: 'Cambiar el empaque de la puerta', tipo: 'otro', estado: 'propuesta',
  fecha_compromiso: '2026-10-01', responsable_id: null, vencida: true, dias_vencida: 41, modo_falla_id: MODO,
  modo_falla: modo.descripcion_falla, nivel_riesgo: 20, equipo_id: EQ, equipo_codigo: 'EQ-0001',
  equipo_nombre: 'Refrigerador vertical', tenant_id: T,
}]

const configuracion: ConfiguracionCriticidad = {
  id: 'cfg1', tenant_id: T, pesos_json: PESOS,
  rangos_economico_json: [{ nivel: 1, hasta: 5000, texto: 'Menor a $5,000' }],
  escala_probabilidad_json: {
    meses: 12, minimo_meses_historia: 6, minimo_fallas_para_mtbf: 3, por_mtbf: [],
    por_fallas: [
      { nivel: 1, hasta: 0, texto: 'Sin fallas en 12 meses' },
      { nivel: 5, hasta: null, texto: '12 fallas o más en 12 meses' },
    ],
  },
  rangos_nivel_json: [
    { nivel: 'A', desde: 80, hasta: 100, etiqueta: 'Crítico' },
    { nivel: 'B', desde: 50, hasta: 79, etiqueta: 'Importante' },
    { nivel: 'C', desde: 20, hasta: 49, etiqueta: 'Estándar' },
    { nivel: 'D', desde: 0, hasta: 19, etiqueta: 'No crítico' },
  ],
  meses_revision: 12,
  implicaciones_activas_json: {
    pm_obligatorio: { alerta: true, restriccion: false },
    respuesta_maxima: { alerta: true, restriccion: false },
    tecnico_certificado: { alerta: true, restriccion: false },
    refaccion_en_inventario: { alerta: true, restriccion: false },
  },
  configurado_por: null, version_hash: 'x',
}

const RUTAS_MODULO = {
  'GET /api/criticidad': () => ({ json: registro }),
  'GET /api/criticidad/resumen': () => ({ json: resumen }),
  'GET /api/criticidad/matriz': () => ({ json: matrizActivos }),
  'GET /api/criticidad/configuracion': () => ({ json: configuracion }),
  'GET /api/modos-falla/matriz': () => ({ json: matrizModos }),
  'GET /api/mitigaciones/pendientes': () => ({ json: pendientes }),
  'GET /api/reportes/iso55000': () => ({ json: [{ tipo: 'iso_registro', nombre: 'ISO 55000 · Registro de activos con criticidad' }] }),
  'GET /api/catalogos/tipos-equipo': () => ({ json: [{ id: 'te1', nombre: 'Refrigerador vertical' }] }),
}

async function entrar(rol: Rol, ruta: string, rutas: Parameters<typeof simularApi>[0] = {}, extra: Partial<PerfilConTema> = {}) {
  localStorage.setItem('acma.sesion', '1')
  const llamadas = simularApi({
    'POST /api/auth/refresh': () => ({ json: TOKENS }),
    'GET /api/auth/yo': () => ({ json: perfil(rol, {
      prestador_id: ['despachador', 'admin_prestador', 'mesa_control', 'tecnico'].includes(rol) ? 'p1' : null,
      tenant_id: ['admin_empresa', 'admin_un', 'operador', 'supervisor_operadores'].includes(rol) ? T : null, ...extra }) }),
    'GET /api/configuracion/mis-permisos': () => ({ json: [] }),
    ...rutas,
  })
  renderApp(ruta)
  return llamadas
}

describe('Criticidad de activos y riesgo (F2-05)', () => {
  it('la fórmula del índice y el nivel se calculan igual que en el servidor', () => {
    expect(impactoPonderado({ operacional: 5, seguridad: 4, economico: 4, imagen: 4 }, PESOS)).toBe(4.3)
    expect(impactoPonderado({ operacional: 5, seguridad: 5, economico: 5, imagen: 5 }, PESOS)).toBe(5)
    expect(indiceDe(5, 4.3)).toBe(86)
    expect(indiceDe(5, 5)).toBe(100)
    expect(indiceDe(1, 1)).toBe(4)
    const rangos = configuracion.rangos_nivel_json
    expect(nivelDe(80, rangos)).toBe('A')
    expect(nivelDe(79.99, rangos)).toBe('B')
    expect(nivelDe(50, rangos)).toBe('B')
    expect(nivelDe(49.99, rangos)).toBe('C')
    expect(nivelDe(20, rangos)).toBe('C')
    expect(nivelDe(19.99, rangos)).toBe('D')
    expect(sumaPesos(PESOS)).toBe(100)
    expect(sumaPesos({ ...PESOS, operacional: 40 })).toBe(110)
  })

  it('la ficha del activo muestra el nivel, el desglose del índice y el historial', async () => {
    await entrar('admin_empresa', `/activos/${EQ}?vista=criticidad`, {
      [`GET /api/activos/${EQ}`]: () => ({ json: ficha }),
      [`GET /api/criticidad/equipos/${EQ}`]: () => ({ json: evaluado }),
      [`GET /api/criticidad/equipos/${EQ}/historial`]: () => ({ json: historial }),
      'GET /api/modos-falla': () => ({ json: [modo] }),
      'GET /api/mitigaciones': () => ({ json: [mitigacion] }),
    })
    expect(await screen.findByText('A · Crítico')).toBeInTheDocument()
    expect(screen.getByText('86.00')).toBeInTheDocument()
    expect(screen.getByText(/Respuesta a correctivos máximo 4 horas/)).toBeInTheDocument()
    // El desglose contesta «¿de dónde salió este 86?».
    expect(screen.getByText(/Probabilidad 5.00 \(de historial de fallas del activo\) × impacto 4.30 ÷ 25 × 100 = 86.00/)).toBeInTheDocument()
    expect(screen.getByText('4 · Riesgo de lesión seria')).toBeInTheDocument()
    expect(screen.getByText('1.40')).toBeInTheDocument()
    // El historial de evaluaciones, con el cambio de nivel y su motivo.
    expect(screen.getByText('Recálculo por historial')).toBeInTheDocument()
    expect(screen.getByText('B → A')).toBeInTheDocument()
    // El FMEA con su nivel de riesgo y la mitigación propuesta.
    expect(screen.getByText(modo.descripcion_falla)).toBeInTheDocument()
    expect(screen.getByText('20 · Crítico')).toBeInTheDocument()
    expect(screen.getByText(/Cambiar el empaque de la puerta cada seis meses/)).toBeInTheDocument()
    expect(screen.getByText('Propuesta')).toBeInTheDocument()
  })

  it('la evaluación guiada manda las cuatro dimensiones y muestra el índice estimado', async () => {
    const llamadas = await entrar('admin_empresa', `/activos/${EQ}?vista=criticidad`, {
      [`GET /api/activos/${EQ}`]: () => ({ json: ficha }),
      [`GET /api/criticidad/equipos/${EQ}`]: () => ({ json: sinEvaluar }),
      'GET /api/modos-falla': () => ({ json: [] }),
      [`POST /api/criticidad/equipos/${EQ}`]: () => ({ json: { ...evaluado, id: 'ac1', equipo_id: EQ, tenant_id: T } }),
    })
    expect(await screen.findByText(/todavía no tiene criticidad evaluada/)).toBeInTheDocument()
    expect(screen.getByText(/Impacto económico propuesto: nivel 3/)).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Evaluar criticidad' }))
    const dialogo = await screen.findByRole('dialog')
    // La guía trae la pregunta y el texto de cada nivel de §6.9.3.
    const operacional = within(dialogo).getByLabelText(/Operacional \(30 %\).*¿Cuánto afecta la falla/)
    await user.selectOptions(operacional, '5')
    await user.selectOptions(within(dialogo).getByLabelText(/Seguridad \(35 %\)/), '4')
    await user.selectOptions(within(dialogo).getByLabelText(/Económico \(25 %\)/), '4')
    await user.selectOptions(within(dialogo).getByLabelText(/Imagen \(10 %\)/), '4')
    // Con la probabilidad que saldría hoy (5) el índice estimado es el mismo que calcula el servidor.
    expect(within(dialogo).getByText(/Impacto ponderado 4.30 · índice estimado 86.00/)).toBeInTheDocument()
    await user.click(within(dialogo).getByRole('button', { name: 'Guardar la evaluación' }))
    await waitFor(() => expect(llamadas.some((l) => l.clave === `POST /api/criticidad/equipos/${EQ}`)).toBe(true))
    const cuerpo = llamadas.find((l) => l.clave === `POST /api/criticidad/equipos/${EQ}`)!.cuerpo as {
      dimensiones: Record<string, number>; motivo: string }
    expect(cuerpo.dimensiones).toEqual({ operacional: 5, seguridad: 4, economico: 4, imagen: 4 })
    expect(cuerpo.motivo).toBe('evaluacion_inicial')
  })

  it('el ajuste manual exige razón y se manda con el nivel elegido', async () => {
    const llamadas = await entrar('admin_empresa', `/activos/${EQ}?vista=criticidad`, {
      [`GET /api/activos/${EQ}`]: () => ({ json: ficha }),
      [`GET /api/criticidad/equipos/${EQ}`]: () => ({ json: evaluado }),
      [`GET /api/criticidad/equipos/${EQ}/historial`]: () => ({ json: historial }),
      'GET /api/modos-falla': () => ({ json: [] }),
      [`POST /api/criticidad/equipos/${EQ}/ajuste`]: () => ({ json: { ...evaluado, nivel: 'C', origen: 'manual' } }),
    })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Ajustar a mano' }))
    const dialogo = await screen.findByRole('dialog')
    await user.selectOptions(within(dialogo).getByLabelText('Nivel'), 'C')
    await user.type(within(dialogo).getByLabelText('Razón del ajuste'), 'Se reubicó a una bodega sin producto')
    await user.click(within(dialogo).getByRole('button', { name: 'Fijar el nivel' }))
    await waitFor(() => expect(llamadas.some((l) => l.clave === `POST /api/criticidad/equipos/${EQ}/ajuste`)).toBe(true))
    const cuerpo = llamadas.find((l) => l.clave === `POST /api/criticidad/equipos/${EQ}/ajuste`)!.cuerpo as {
      nivel: string; razon: string }
    expect(cuerpo.nivel).toBe('C')
    expect(cuerpo.razon).toContain('bodega sin producto')
  })

  it('los modos de falla propuestos desde el historial se aceptan en lote', async () => {
    const llamadas = await entrar('admin_prestador', `/activos/${EQ}?vista=criticidad`, {
      [`GET /api/activos/${EQ}`]: () => ({ json: ficha }),
      [`GET /api/criticidad/equipos/${EQ}`]: () => ({ json: evaluado }),
      [`GET /api/criticidad/equipos/${EQ}/historial`]: () => ({ json: historial }),
      'GET /api/modos-falla': () => ({ json: [] }),
      'GET /api/modos-falla/sugerencias': () => ({ json: [sugerencia] }),
      'POST /api/modos-falla/aceptar-sugerencias': () => ({ json: [modo] }),
    })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Proponer desde el historial' }))
    expect(await screen.findByText('16 · Crítico')).toBeInTheDocument()
    expect(screen.getByText(/7 falla\(s\) en 12 meses/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Aceptar los que faltan' }))
    await waitFor(() => expect(llamadas.some((l) => l.clave === 'POST /api/modos-falla/aceptar-sugerencias')).toBe(true))
    const cuerpo = llamadas.find((l) => l.clave === 'POST /api/modos-falla/aceptar-sugerencias')!.cuerpo as {
      equipo_id: string; sugerencias: { descripcion_falla: string }[] }
    expect(cuerpo.equipo_id).toBe(EQ)
    expect(cuerpo.sugerencias.map((s) => s.descripcion_falla)).toEqual(['No enfría'])
  })

  it('el módulo ISO 55000 lista el registro con su nivel y marca lo vencido y lo que no tiene plan', async () => {
    await entrar('admin_empresa', '/iso55000', RUTAS_MODULO)
    await screen.findByRole('heading', { name: 'Gestión de activos ISO 55000' })
    expect(await screen.findByText('A · 2')).toBeInTheDocument()
    expect(screen.getByText('EQ-0001 · Refrigerador vertical')).toBeInTheDocument()
    // «A · Crítico» sale en la fila y en el filtro de nivel.
    expect(screen.getAllByText('A · Crítico').length).toBeGreaterThan(0)
    expect(screen.getByText('86.00')).toBeInTheDocument()
    expect(screen.getByText('Sin plan')).toBeInTheDocument()       // el A sin plan de mantenimiento
    expect(screen.getByText('Vencida')).toBeInTheDocument()        // la revisión vencida del EQ-0012
    expect(screen.getByText('A mano')).toBeInTheDocument()         // el nivel fijado manualmente
    expect(screen.getByText(/5.00 × 4.30/)).toBeInTheDocument()
    expect(screen.getByText('(estimada)')).toBeInTheDocument()
  })

  it('la matriz de riesgo dibuja las 25 celdas y al hacer clic lista los activos de la celda', async () => {
    await entrar('admin_empresa', '/iso55000', RUTAS_MODULO)
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Matriz de riesgo' }))
    const celda = await screen.findByRole('button', { name: 'Probabilidad 5, Impacto 4: 1' })
    // Las 25 celdas de cada matriz están dibujadas, ocupadas o no.
    expect(screen.getAllByRole('button', { name: /^Probabilidad \d, Impacto \d: \d+$/ })).toHaveLength(25)
    expect(screen.getAllByRole('button', { name: /^Severidad \d, Frecuencia \d: \d+$/ })).toHaveLength(25)
    expect(screen.getByRole('button', { name: 'Probabilidad 1, Impacto 1: 0' })).toBeDisabled()
    await user.click(celda)
    expect(await screen.findByText(/Probabilidad 5 · Impacto 4 · 1 elemento/)).toBeInTheDocument()
    expect(screen.getByText('nivel A', { exact: false })).toBeInTheDocument()
  })

  it('la bandeja muestra la acción vencida con sus días y la marca implementada', async () => {
    const llamadas = await entrar('admin_prestador', '/iso55000', {
      ...RUTAS_MODULO,
      [`POST /api/mitigaciones/${MIT}/estado`]: () => ({ json: { ...mitigacion, estado: 'implementada' } }),
    })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Pendientes' }))
    expect(await screen.findByText('Cambiar el empaque de la puerta')).toBeInTheDocument()
    expect(screen.getByText('41 día(s)')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Marcar implementada' }))
    await waitFor(() => expect(llamadas.some((l) => l.clave === `POST /api/mitigaciones/${MIT}/estado`)).toBe(true))
    const cuerpo = llamadas.find((l) => l.clave === `POST /api/mitigaciones/${MIT}/estado`)!.cuerpo as { estado: string }
    expect(cuerpo.estado).toBe('implementada')
  })

  it('la configuración de pesos no deja guardar si no suman 100 y la guarda cuando sí', async () => {
    const llamadas = await entrar('admin_empresa', '/iso55000', {
      ...RUTAS_MODULO,
      'PUT /api/criticidad/configuracion': () => ({ json: configuracion }),
    })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Configuración' }))
    const operacional = await screen.findByLabelText('Operacional (%)')
    await user.clear(operacional)
    await user.type(operacional, '40')
    expect(await screen.findByText(/Suman 110 %/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Guardar los pesos' })).toBeDisabled()
    await user.clear(operacional)
    await user.type(operacional, '30')
    expect(await screen.findByText('Suman 100 %')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Guardar los pesos' }))
    await waitFor(() => expect(llamadas.some((l) => l.clave === 'PUT /api/criticidad/configuracion')).toBe(true))
    const cuerpo = llamadas.find((l) => l.clave === 'PUT /api/criticidad/configuracion')!.cuerpo as {
      pesos_json: Record<string, number> }
    expect(cuerpo.pesos_json).toEqual(PESOS)
  })

  it('las implicaciones se activan como aviso o como restricción, y solo el Admin empresa las ve', async () => {
    const llamadas = await entrar('admin_empresa', '/iso55000', {
      ...RUTAS_MODULO,
      'PUT /api/criticidad/configuracion': () => ({ json: configuracion }),
    })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Configuración' }))
    const casilla = await screen.findByLabelText('Restringir: Técnico especialista en A y certificado en B')
    expect(casilla).not.toBeChecked()
    await user.click(casilla)
    await waitFor(() => expect(llamadas.some((l) => l.clave === 'PUT /api/criticidad/configuracion')).toBe(true))
    const cuerpo = llamadas.find((l) => l.clave === 'PUT /api/criticidad/configuracion')!.cuerpo as {
      implicaciones_activas_json: Record<string, { alerta: boolean; restriccion: boolean }> }
    expect(cuerpo.implicaciones_activas_json.tecnico_certificado).toEqual({ alerta: true, restriccion: true })
  })

  it('el prestador no ve la pestaña de configuración del cliente', async () => {
    await entrar('despachador', '/iso55000', RUTAS_MODULO)
    await screen.findByRole('heading', { name: 'Gestión de activos ISO 55000' })
    expect(screen.queryByRole('button', { name: 'Configuración' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Evaluación masiva' })).not.toBeInTheDocument()
  })

  it('la evaluación masiva por tipo de equipo manda el tipo y las dimensiones', async () => {
    const llamadas = await entrar('admin_empresa', '/iso55000', {
      ...RUTAS_MODULO,
      'POST /api/criticidad/masiva': () => ({ json: { evaluados: 3, omitidos: 1, por_nivel: { A: 0, B: 1, C: 2, D: 0 } } }),
    })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Evaluación masiva' }))
    const dialogo = await screen.findByRole('dialog')
    await user.selectOptions(within(dialogo).getByLabelText('Tipo de equipo'), 'te1')
    await user.selectOptions(within(dialogo).getByLabelText('Seguridad (1–5)'), '4')
    await user.click(within(dialogo).getByRole('button', { name: 'Evaluar el tipo de equipo' }))
    await waitFor(() => expect(llamadas.some((l) => l.clave === 'POST /api/criticidad/masiva')).toBe(true))
    const cuerpo = llamadas.find((l) => l.clave === 'POST /api/criticidad/masiva')!.cuerpo as {
      tipo_equipo_id: string; dimensiones: Record<string, number>; solo_sin_evaluar: boolean }
    expect(cuerpo.tipo_equipo_id).toBe('te1')
    expect(cuerpo.dimensiones.seguridad).toBe(4)
    expect(cuerpo.solo_sin_evaluar).toBe(true)
    expect(await screen.findByText(/3 evaluado\(s\), 1 omitido\(s\)/)).toBeInTheDocument()
  })
  it('el tablero del cliente trae la distribución por nivel, los A sin plan y lo vencido', async () => {
    const tablero = {
      tipo: 'cliente', rol: 'admin_empresa', periodo: { desde: '2026-11-01', hasta: '2026-11-11' },
      cache: false, ttl_cache_segundos: 120, criticidad: resumen,
    }
    await entrar('admin_empresa', '/bi', { 'GET /api/bi/tablero': () => ({ json: tablero }) })
    const tarjeta = await screen.findByTestId('criticidad-tablero')
    expect(within(tarjeta).getByTestId('kpi-nivel-a-critico')).toHaveTextContent('2')
    expect(within(tarjeta).getByTestId('kpi-nivel-d-no-critico')).toHaveTextContent('4')
    expect(screen.getByTestId('kpi-activos-a-sin-plan')).toHaveTextContent('1')
    expect(screen.getByTestId('kpi-mitigaciones-vencidas')).toHaveTextContent('2')
    expect(screen.getByTestId('kpi-revisiones-vencidas')).toHaveTextContent('1')
    expect(screen.getByRole('link', { name: 'Ver el módulo' })).toHaveAttribute('href', '/iso55000')
  })
})
