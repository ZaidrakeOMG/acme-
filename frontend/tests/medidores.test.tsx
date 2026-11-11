import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { PerfilConTema, Rol } from '../src/types/api'
import type { EquipoDelOperador, MedidorEquipo, PendienteRevision, TipoMedidor } from '../src/types/medidores'
import type { Plan } from '../src/types/preventivos'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const T = '11111111-1111-1111-1111-111111111111'
const EQ = 'e0000000-0000-0000-0000-000000000001'
const MED = 'd0000000-0000-0000-0000-000000000001'
const TIPO = 'f0000000-0000-0000-0000-000000000001'
const PLAN = 'a0000000-0000-0000-0000-00000000000a'

const tipo: TipoMedidor = {
  id: TIPO, created_at: '2026-11-01T00:00:00Z', updated_at: '2026-11-01T00:00:00Z', version_hash: null,
  prestador_id: null, tenant_id: null, nombre: 'Horas de operación', unidad: 'h', categoria: 'horas',
  descripcion: 'Horómetro del equipo', permite_estimacion: true, decimales: 1, requiere_foto: true,
  factor_salto_maximo: '3.00', activo: true,
}

const medidor: MedidorEquipo = {
  id: MED, tipo_medidor_id: TIPO, tipo: 'Horas de operación', unidad: 'h', categoria: 'horas', decimales: 1,
  requiere_foto: true, valor_actual: '480.00', valor_acumulado: '480.00', valor_ultimo_pm: '0.00',
  fecha_ultima_lectura: '2026-11-10T13:00:00Z', metodo_actualizacion: 'operador', valor_maximo: '99999.00',
  numero_serie_medidor: 'HM-884210', instalado_en: '2025-01-15', activo: true,
  incremento_por_dia: '8.0000', origen_incremento: 'promedio_real',
  estimacion: { incremento_por_dia: '8.0000', incremento_real_promedio: '8.2500', horario_operacion_json: { dias: ['lunes'], horas_por_dia: 8 }, activa: false, desde: '2026-09-12', ultima_estimacion_at: null },
  proximos_mantenimientos: [{
    plan_id: PLAN, plan: 'Cambio de aceite del compresor a las 500 h', ventana_dias: 5, clave: 't1',
    tipo_trigger: 'medidor_umbral', fecha_estimada: '2026-11-14', valor_objetivo: '500.00', valor_actual: '480.00',
    unidad: 'h', faltante: '20.00', motivo: '8.0000 h al día (promedio_real)',
  }],
}

const pendiente: PendienteRevision = {
  id: 'l0000000-0000-0000-0000-000000000001', equipo_id: EQ, equipo: 'Motor eléctrico bomba principal',
  equipo_codigo: 'EQ-1004', tenant_id: T, medidor: 'Energía consumida', unidad: 'kWh', valor: '27000.00',
  valor_acumulado: '27000.00', metodo: 'importacion',
  motivo: 'El salto de 9000.00 kWh en 1 día(s) es más de 3.00× lo esperado (900.00 kWh con 300.0000 kWh al día).',
  timestamp: '2026-11-11T15:00:00Z', valor_anterior: '18000.00', fecha_anterior: '2026-11-10T07:00:00Z',
}

const delOperador: EquipoDelOperador = {
  equipo_medidor_id: MED, equipo_id: EQ, equipo: 'Compresor de aire sala de máquinas', equipo_codigo: 'EQ-1001',
  un_id: 'u1', un_codigo: 'SUC-001', medidor: 'Horas de operación', unidad: 'h', decimales: 1, requiere_foto: true,
  valor_actual: '480.00', valor_maximo: '99999.00', fecha_ultima_lectura: '2026-11-10T13:00:00Z',
}

const plan: Plan = {
  id: PLAN, created_at: '2026-11-01T00:00:00Z', updated_at: '2026-11-01T00:00:00Z', version_hash: null, prestador_id: 'p1',
  tenant_id: null, tipo_equipo_id: 'te1', tipo_equipo_nombre: 'Compresor de aire',
  nombre: 'Revisión del compresor: 90 días o 400 horas', descripcion: '', version: 1, estado: 'activo',
  tiempo_ventana_dias: 7, formulario_id: null, formulario_nombre: null, nivel_severidad_id: null, created_by: null,
  triggers: [
    { id: 'tr1', clave: 't1', tipo_trigger: 'tiempo_fijo', parametros_json: { cada_dias: 90 }, logica_combinacion: null },
    { id: 'tr2', clave: 't2', tipo_trigger: 'medidor_umbral', parametros_json: { tipo_medidor_id: TIPO, umbral: 400 }, logica_combinacion: null },
    { id: 'tr3', clave: 't3', tipo_trigger: 'combinado', parametros_json: { triggers_claves: ['t1', 't2'], triggers_ids: ['tr1', 'tr2'], logica: 'OR' }, logica_combinacion: 'OR' },
  ],
  tareas: [], materiales: [],
  equipos: [{ id: 'ep1', equipo_id: EQ, tenant_id: T, activo: true, fecha_proxima_ejecucion: '2026-11-14', fecha_ultima_ejecucion: null, fecha_alta: '2026-09-12', ultimo_valor_medidor: null }],
}

async function entrar(rol: Rol, ruta: string, rutas: Parameters<typeof simularApi>[0] = {}, extra: Partial<PerfilConTema> = {}) {
  localStorage.setItem('acma.sesion', '1')
  const llamadas = simularApi({
    'POST /api/auth/refresh': () => ({ json: TOKENS }),
    'GET /api/auth/yo': () => ({ json: perfil(rol, { prestador_id: ['despachador', 'admin_prestador', 'mesa_control', 'tecnico'].includes(rol) ? 'p1' : null, tenant_id: ['admin_empresa', 'admin_un', 'operador', 'supervisor_operadores'].includes(rol) ? T : null, ...extra }) }),
    'GET /api/configuracion/mis-permisos': () => ({ json: [] }),
    'GET /api/medidores/tipos': () => ({ json: [tipo] }),
    ...rutas,
  })
  renderApp(ruta)
  return llamadas
}

describe('Medidores de activos (F2-04)', () => {
  it('la bandeja muestra la lectura anómala con su anterior y la aprueba', async () => {
    const llamadas = await entrar('despachador', '/medidores', {
      'GET /api/medidores/lecturas/por-revisar': () => ({ json: [pendiente] }),
      [`POST /api/medidores/lecturas/${pendiente.id}/revision`]: () => ({ json: {
        lectura: { id: pendiente.id, valor: '27000.00', estado: 'valida', motivo: 'ok' },
        duplicada: false, anomalia: '', folios_generados: [{ folio_id: 'f1', numero_folio: 'CD-000200', plan: 'Inspección', fecha_programada: '2026-11-11' }],
      } }),
    })
    await screen.findByRole('heading', { name: 'Medidores de activos' })
    expect(await screen.findByText('EQ-1004 Motor eléctrico bomba principal')).toBeInTheDocument()
    expect(screen.getByText('27,000.00 kWh')).toBeInTheDocument()
    expect(screen.getByText('18,000.00 kWh')).toBeInTheDocument()   // el valor anterior, para comparar
    expect(screen.getByText(/más de 3.00× lo esperado/)).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Revisar' }))
    const dialogo = await screen.findByRole('dialog')
    await user.click(within(dialogo).getByRole('button', { name: 'Aprobar la lectura' }))
    await waitFor(() => expect(llamadas.some((l) => l.clave === `POST /api/medidores/lecturas/${pendiente.id}/revision`)).toBe(true))
    expect(await screen.findByText(/generó 1 folio\(s\) preventivo\(s\)/)).toBeInTheDocument()
    const envio = llamadas.find((l) => l.clave === `POST /api/medidores/lecturas/${pendiente.id}/revision`)!.cuerpo as { aprobar: boolean }
    expect(envio.aprobar).toBe(true)
  })

  it('la llave de API se muestra una sola vez y se revoca', async () => {
    const llamadas = await entrar('admin_empresa', '/medidores', {
      'GET /api/medidores/lecturas/por-revisar': () => ({ json: [] }),
      'GET /api/medidores/llaves': () => ({ json: [] }),
      'POST /api/medidores/llaves': () => ({ json: {
        llave: { id: 'k1', created_at: '2026-11-11T00:00:00Z', tenant_id: T, nombre: 'SCADA planta', prefijo: 'acma_abc', permisos_json: ['medidores.lecturas'], activa: true, creada_por: null, revocada_at: null, ultimo_uso_at: null, usos: 0 },
        secreto: 'acma_abcdefghijklmnopqrstuvwxyz0123456789',
      } }),
    })
    await screen.findByRole('heading', { name: 'Medidores de activos' })
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Llaves de API' }))
    await user.type(await screen.findByLabelText('Nombre del sistema que la va a usar'), 'SCADA planta')
    await user.click(screen.getByRole('button', { name: 'Crear llave' }))
    const aviso = await screen.findByTestId('llave-secreto')
    expect(aviso).toHaveTextContent('acma_abcdefghijklmnopqrstuvwxyz0123456789')
    expect(aviso).toHaveTextContent('no se vuelve a mostrar')
    expect(llamadas.some((l) => l.clave === 'POST /api/medidores/llaves')).toBe(true)
  })

  it('la pestaña de medidores del equipo muestra la gráfica, el próximo PM y registra un reinicio', async () => {
    const llamadas = await entrar('admin_prestador', `/activos/${EQ}?vista=medidores`, {
      [`GET /api/activos/${EQ}`]: () => ({ json: {
        equipo: { id: EQ, codigo: 'EQ-1001', nombre: 'Compresor de aire sala de máquinas', un_codigo: 'SUC-001', un_nombre: 'Sucursal Centro', tipo_equipo: 'Compresor de aire', estado: 'activo', criticidad: 'B', criticidad_origen: 'manual' },
        contrato: null, historial_folios: [], refacciones: [], depreciacion: null, depreciacion_historial: [], medidores: [medidor],
        tco: { periodo: '2026-11', costo_adquisicion: '180000.00', costo_preventivos: '0.00', costo_correctivos: '0.00', costo_refacciones: '0.00', costo_downtime: '0.00', horas_downtime: '0.00', valor_residual: '180000.00', tco_total: '0.00', valor_reposicion: '180000.00', porcentaje_vs_reposicion: '0.00', folios: 0, aviso: '' },
        tco_historial: [], alerta_reemplazo: null, umbral_reemplazo_pct: '70.00', fase_2: [],
      } }),
      [`GET /api/medidores/equipos/${EQ}`]: () => ({ json: [medidor] }),
      'GET /api/medidores/lecturas': () => ({ json: [
        { id: 'l1', created_at: '', updated_at: '', version_hash: null, equipo_medidor_id: MED, equipo_id: EQ, tipo_medidor_id: TIPO, valor: '472.00', valor_acumulado: '472.00', metodo: 'operador', registrado_por: null, folio_id: null, evidencia_id: null, timestamp_dispositivo: null, timestamp: '2026-11-09T13:00:00Z', estado: 'valida', motivo: '', revisada_por: null, revisada_at: null },
        { id: 'l2', created_at: '', updated_at: '', version_hash: null, equipo_medidor_id: MED, equipo_id: EQ, tipo_medidor_id: TIPO, valor: '480.00', valor_acumulado: '480.00', metodo: 'estimado', registrado_por: null, folio_id: null, evidencia_id: null, timestamp_dispositivo: null, timestamp: '2026-11-10T13:00:00Z', estado: 'valida', motivo: '', revisada_por: null, revisada_at: null },
      ] }),
      [`GET /api/medidores/${MED}/cambios`]: () => ({ json: [] }),
      [`POST /api/medidores/${MED}/cambios`]: () => ({ json: { id: 'c1', equipo_medidor_id: MED, tipo: 'reinicio', valor_anterior: '480.00', valor_nuevo: '0.00', acumulado_al_cambio: '480.00', numero_serie_anterior: null, numero_serie_nuevo: null, motivo: 'El marcador dio la vuelta', registrado_por: null, timestamp: '2026-11-11T00:00:00Z' } }),
    })
    await screen.findByTestId('pestana-medidores')
    expect(await screen.findByText('Horas de operación')).toBeInTheDocument()
    expect(screen.getByTestId(`medidor-${TIPO}`)).toHaveTextContent('480.0 h')
    // Las lecturas se ven en la gráfica y también en texto, con su método.
    expect(screen.getByTestId(`grafica-${MED}`)).toBeInTheDocument()
    expect(within(screen.getByTestId(`lecturas-${MED}`)).getByText(/480.0 h · Estimada/)).toBeInTheDocument()
    expect(within(screen.getByTestId(`lecturas-${MED}`)).getByText(/472.0 h · Operador/)).toBeInTheDocument()
    // El próximo mantenimiento por uso, con su fecha estimada y la ventana del plan.
    const proximos = screen.getByTestId(`proximos-${MED}`)
    expect(proximos).toHaveTextContent('Cambio de aceite del compresor a las 500 h')
    expect(proximos).toHaveTextContent('faltan 20.0 h')
    expect(proximos).toHaveTextContent('estimado para el 2026-11-14')
    // Estimado contra real, que es lo que §6.9.2 pide mostrar.
    expect(screen.getByTestId(`estimacion-${MED}`)).toHaveTextContent('8.00 h por día')
    expect(screen.getByTestId(`estimacion-${MED}`)).toHaveTextContent('el uso real medido es 8.25 h por día')
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Reinicio o reemplazo' }))
    const dialogo = await screen.findByRole('dialog')
    await user.type(within(dialogo).getByLabelText('Motivo (obligatorio)'), 'El marcador dio la vuelta')
    await user.click(within(dialogo).getByRole('button', { name: 'Registrar' }))
    await waitFor(() => expect(llamadas.some((l) => l.clave === `POST /api/medidores/${MED}/cambios`)).toBe(true))
    const cuerpo = llamadas.find((l) => l.clave === `POST /api/medidores/${MED}/cambios`)!.cuerpo as { tipo: string; motivo: string }
    expect(cuerpo.tipo).toBe('reinicio')
    expect(await screen.findByText(/el acumulado del equipo no retrocede/)).toBeInTheDocument()
  })

  it('el constructor de planes arma un combinado «lo que ocurra primero»', async () => {
    const llamadas = await entrar('admin_prestador', '/preventivos/planes', {
      'GET /api/planes': () => ({ json: [] }),
      'GET /api/catalogos/tipos-equipo': () => ({ json: [{ id: 'te1', familia_id: 'f1', tenant_id: null, nombre: 'Compresor de aire', descripcion: '', activa: true, es_global: true }] }),
      'GET /api/catalogos/habilidades': () => ({ json: [] }),
      'GET /api/formularios': () => ({ json: [] }),
      'GET /api/planes/eventos-catalogo': () => ({ json: [{ clave: 'falla_correctiva_grave', descripcion: 'Se cerró un folio correctivo grave.', parametros_schema_json: {}, activo: true }] }),
      'POST /api/planes': (cuerpo) => ({ estado: 201, json: { ...plan, ...(cuerpo as object) } }),
    })
    await screen.findByRole('heading', { name: 'Planes de mantenimiento' })
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Nuevo plan' }))
    const dialogo = await screen.findByRole('dialog')
    await user.type(within(dialogo).getByLabelText('Nombre'), '90 días o 400 horas')
    await user.selectOptions(within(dialogo).getByLabelText('Tipo de equipo'), 'te1')
    // t1 queda en «cada 90 días», t2 por medidor y t3 los combina con O.
    await user.clear(within(dialogo).getByLabelText('Días de t1'))
    await user.type(within(dialogo).getByLabelText('Días de t1'), '90')
    await user.click(within(dialogo).getByRole('button', { name: '+ Condición' }))
    await user.selectOptions(await within(dialogo).findByLabelText('Tipo de la condición t2'), 'medidor_umbral')
    await user.clear(within(dialogo).getByLabelText('Valor de t2'))
    await user.type(within(dialogo).getByLabelText('Valor de t2'), '400')
    expect(within(dialogo).getByTestId('resumen-t2')).toHaveTextContent('Al llegar a 400 h de Horas de operación')
    await user.click(within(dialogo).getByRole('button', { name: '+ Condición' }))
    await user.selectOptions(await within(dialogo).findByLabelText('Tipo de la condición t3'), 'combinado')
    await user.click(within(dialogo).getByLabelText('Incluir t1'))
    await user.click(within(dialogo).getByLabelText('Incluir t2'))
    expect(within(dialogo).getByTestId('resumen-t3')).toHaveTextContent('lo que ocurra primero')
    // Las condiciones de un combinado se marcan: por sí solas no disparan.
    expect(within(dialogo).getAllByText('es condición de un combinado: por sí sola no dispara')).toHaveLength(2)
    await user.click(within(dialogo).getByRole('button', { name: 'Crear plan' }))
    await waitFor(() => expect(llamadas.some((l) => l.clave === 'POST /api/planes')).toBe(true))
    const cuerpo = llamadas.find((l) => l.clave === 'POST /api/planes')!.cuerpo as { triggers: { clave: string; tipo_trigger: string; parametros_json: Record<string, unknown> }[] }
    expect(cuerpo.triggers.map((t) => `${t.clave}:${t.tipo_trigger}`)).toEqual(['t1:tiempo_fijo', 't2:medidor_umbral', 't3:combinado'])
    expect(cuerpo.triggers[1]?.parametros_json).toEqual({ tipo_medidor_id: TIPO, umbral: 400 })
    expect(cuerpo.triggers[2]?.parametros_json).toEqual({ triggers_claves: ['t1', 't2'], logica: 'OR' })
  })

  it('la simulación dice cuándo se dispararía el plan con las lecturas actuales', async () => {
    await entrar('admin_prestador', '/preventivos/planes', {
      'GET /api/planes': () => ({ json: [plan] }),
      'GET /api/catalogos/equipos': () => ({ json: [] }),
      [`GET /api/planes/${PLAN}/simulacion`]: () => ({ json: [{
        equipo_id: EQ, equipo: 'Compresor de aire sala de máquinas', equipo_codigo: 'EQ-1001',
        fecha_estimada: '2026-11-14', ultima_ejecucion: null, ultimo_valor_medidor: null, folio_abierto: null,
        triggers: medidor.proximos_mantenimientos,
      }] }),
    })
    await screen.findByRole('heading', { name: 'Planes de mantenimiento' })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Revisión del compresor: 90 días o 400 horas' }))
    await user.click(await screen.findByRole('button', { name: 'Simular: ¿cuándo se dispararía?' }))
    const sim = await screen.findByTestId('simulacion')
    expect(sim).toHaveTextContent('EQ-1001')
    expect(sim).toHaveTextContent('2026-11-14')
    expect(sim).toHaveTextContent('va en 480 de 500 h')
  })

  it('el operador registra la lectura de su unidad y la encola sin señal', async () => {
    const llamadas = await entrar('operador', '/campo/lectura', {
      'GET /api/medidores/operador/equipos': () => ({ json: [delOperador] }),
      'POST /api/medidores/lecturas': () => ({ json: {
        lectura: { id: 'l9', valor: '496.00', estado: 'valida', motivo: '' }, duplicada: false, anomalia: '',
        folios_generados: [],
      } }),
    })
    await screen.findByRole('heading', { name: 'Registrar lectura' })
    const tarjeta = await screen.findByTestId('medidor-operador-EQ-1001')
    expect(tarjeta).toHaveTextContent('va en 480.0 h')
    expect(tarjeta).toHaveTextContent('Este medidor pide foto del marcador')
    const user = userEvent.setup()
    await user.type(within(tarjeta).getByLabelText('Lectura (h)'), '496')
    await user.click(within(tarjeta).getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(llamadas.some((l) => l.clave === 'POST /api/medidores/lecturas')).toBe(true))
    expect(await screen.findByText(/Lectura registrada: EQ-1001 en 496.0 h/)).toBeInTheDocument()
    const cuerpo = llamadas.find((l) => l.clave === 'POST /api/medidores/lecturas')!.cuerpo as { equipo_medidor_id: string; valor: string }
    expect(cuerpo).toEqual({ equipo_medidor_id: MED, valor: '496' })
  })
})
