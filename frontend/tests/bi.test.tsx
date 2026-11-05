import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { PerfilConTema, Rol } from '../src/types/api'
import type { Tablero } from '../src/types/sla'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const T = '11111111-1111-1111-1111-111111111111'
const UN1 = 'u0000000-0000-0000-0000-000000000001'
const GR1 = 'g0000000-0000-0000-0000-000000000001'

const unidades = [{ id: UN1, tenant_id: T, nombre: 'Sucursal Centro', codigo: 'SUC-001', direccion: 'Av. Juárez 100', ubicacion: null, zona_horaria: 'America/Mexico_City', estado: 'activo', grupo_id: GR1 }]
const grupos = [{ id: GR1, tenant_id: T, nombre: 'Zona Metropolitana', descripcion: '', responsable_id: null, activo: true, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', version_hash: null }]

const base = {
  periodo: { desde: '2026-11-01', hasta: '2026-11-02' }, cache: false, ttl_cache_segundos: 120,
  folios_por_estado: { capturado: 2, asignado: 3, cerrado: 12, cancelado: 1 },
  folios_por_severidad: { Crítica: 4, Alta: 6, Media: 8 },
  cumplimiento_sla: {
    total: 12, respuesta_pct: '91.67', resolucion_pct: '75.00',
    por_severidad: { Crítica: { total: 4, respuesta_ok: 4, resolucion_ok: 2, penalizados: 2, respuesta_pct: '100.00', resolucion_pct: '50.00' } },
  },
}

const tableroCliente: Tablero = {
  ...base, tipo: 'cliente', rol: 'admin_empresa',
  gasto_vs_presupuesto: { presupuestos: 3, monto: '300000.00', consumido: '210000.00', disponible: '90000.00', porcentaje: '70.00' },
  mttr: { folios: 12, horas: '6.50' }, mtbf: { equipos: 5, intervalos: 7, horas: '312.40', aviso: '' },
  costo: { folios: 12, total: '185400.00' },
  preventivos: { programados: 8, ejecutados: 7, cumplimiento_pct: '87.50', desvio_promedio_dias: '1.20' },
  hallazgos: { total: 10, convertidos_a_cotizacion: 4, conversion_pct: '40.00' },
  trabajos_especiales: { total: 3, urgencias: 1, por_estado: { cerrado: 2, programado: 1 } },
  top_equipos_costo: [{ equipo_id: 'e1', codigo: 'EQ-0001', nombre: 'Refrigerador vertical', valor: '42000.00', fallas: 4 }],
  top_equipos_fallas: [{ equipo_id: 'e1', codigo: 'EQ-0001', nombre: 'Refrigerador vertical', valor: '4', fallas: 4 }],
  jerarquia: {
    grupos: [{ id: GR1, nombre: 'Zona Metropolitana', folios: 18, cerrados: 12, sla_resolucion_pct: '75.00', costo: '185400.00' }],
    unidades: [{ id: UN1, nombre: 'SUC-001 · Sucursal Centro', folios: 10, cerrados: 7, sla_resolucion_pct: '71.43', costo: '98000.00' }],
  },
  comparativo_periodo: {
    anterior: { folios: 15, cerrados: 10, sla_resolucion_pct: '80.00', costo: '150000.00' },
    anio_anterior: { folios: 12, cerrados: 9, sla_resolucion_pct: '88.89', costo: '120000.00' },
  },
  calificacion_admin_un: null,
}

const tableroSupervision: Tablero = {
  ...base, tipo: 'supervision', rol: 'supervisor_operadores', sin_finanzas: true,
  aviso: 'Tu rol ve el consolidado de sus grupos: sin información financiera ni detalle de cada folio (§5.1).',
  sla_en_riesgo: [{ id: 'a1', clave: 'SLA_RESOLUCION_EN_RIESGO', disparo: '2026-11-02T09:00:00Z',
                    datos: { numero_folio: 'CD-000081' }, atendida: false, escalada: false, estado: 'disparada' }],
}

async function entrar(rol: Rol, ruta: string, rutas: Parameters<typeof simularApi>[0] = {}, extra: Partial<PerfilConTema> = {}) {
  localStorage.setItem('acma.sesion', '1')  // P11a: solo la marca; el refresh va en cookie httpOnly
  const esTenant = ['admin_empresa', 'admin_un', 'supervisor_operadores', 'operador'].includes(rol)
  const llamadas = simularApi({
    'POST /api/auth/refresh': () => ({ json: TOKENS }),
    'GET /api/auth/yo': () => ({ json: perfil(rol, { tenant_id: esTenant ? T : null, prestador_id: esTenant ? null : 'p1', ...extra }) }),
    'GET /api/notificaciones/no-leidas': () => ({ json: { no_leidas: 0 } }),
    'GET /api/unidades-negocio': () => ({ json: unidades }),
    'GET /api/grupos-un': () => ({ json: grupos }),
    ...rutas,
  })
  renderApp(ruta)
  return llamadas
}

describe('Tablero de BI', () => {
  it('el Admin empresa ve sus KPIs, la jerarquía y el comparativo multi-período', async () => {
    const llamadas = await entrar('admin_empresa', '/bi', { 'GET /api/bi/tablero': () => ({ json: tableroCliente }) })
    const panel = await screen.findByTestId('tablero-cliente', {}, { timeout: 5000 })
    // KPIs con su valor en texto (no solo en la gráfica).
    expect(within(panel).getByTestId('kpi-gasto-contra-presupuesto')).toHaveTextContent('70.00 %')
    expect(within(panel).getByTestId('kpi-gasto-contra-presupuesto')).toHaveTextContent('$210,000.00 de $300,000.00')
    expect(within(panel).getByTestId('kpi-mttr')).toHaveTextContent('6.50 h')
    expect(within(panel).getByTestId('kpi-mtbf')).toHaveTextContent('312.40 h')
    expect(within(panel).getByTestId('kpi-preventivos')).toHaveTextContent('87.50 %')
    // Variación contra el período anterior: 12 cerrados contra 10 → +20 %.
    expect(within(panel).getByTestId('kpi-folios-cerrados')).toHaveTextContent('▲ 20.0 % contra el período anterior')
    // Cada valor de las gráficas también en texto.
    expect(within(panel).getByTestId('folios-por-estado')).toHaveTextContent('cerrado: 12')
    expect(within(panel).getByTestId('folios-por-severidad')).toHaveTextContent('Crítica: 4')
    expect(within(panel).getByTestId('sla-por-severidad')).toHaveTextContent('50.00 %')
    // Jerarquía §6.8.5 y comparativos.
    expect(within(panel).getByTestId('jerarquia-grupos')).toHaveTextContent('Zona Metropolitana')
    expect(within(panel).getByTestId('jerarquia-unidades')).toHaveTextContent('SUC-001 · Sucursal Centro')
    const comp = within(panel).getByTestId('comparativo-periodos')
    expect(comp).toHaveTextContent('Anterior')
    expect(comp).toHaveTextContent('Año anterior')
    // Top de equipos con enlace a la ficha del activo.
    expect(within(within(panel).getByTestId('top-costo')).getByRole('link', { name: 'EQ-0001' })).toHaveAttribute('href', '/activos/e1')
    expect(llamadas.some((l) => l.clave === 'GET /api/bi/tablero')).toBe(true)
  })

  it('el Supervisor de operadores no ve montos ni detalle de folios (§5.1)', async () => {
    await entrar('supervisor_operadores', '/bi', { 'GET /api/bi/tablero': () => ({ json: tableroSupervision }) })
    const panel = await screen.findByTestId('tablero-supervision', {}, { timeout: 5000 })
    expect(within(panel).getByText(/sin información financiera ni detalle de cada folio/)).toBeInTheDocument()
    expect(within(panel).getByTestId('folios-por-estado')).toHaveTextContent('cerrado: 12')
    expect(within(panel).getByTestId('folios-por-severidad')).toHaveTextContent('Alta: 6')
    expect(within(panel).getByTestId('sla-en-riesgo')).toHaveTextContent('SLA_RESOLUCION_EN_RIESGO')
    // Nada de dinero ni enlaces al folio.
    expect(within(panel).queryByTestId('kpi-costo-del-periodo')).not.toBeInTheDocument()
    expect(within(panel).queryByTestId('top-costo')).not.toBeInTheDocument()
    expect(within(panel).queryByTestId('jerarquia-unidades')).not.toBeInTheDocument()
    expect(panel.textContent).not.toMatch(/\$/)
  })

  it('el filtro de período y de nivel se manda al servidor', async () => {
    const llamadas = await entrar('admin_empresa', '/bi', { 'GET /api/bi/tablero': () => ({ json: tableroCliente }) })
    await screen.findByTestId('tablero-cliente', {}, { timeout: 5000 })
    const user = userEvent.setup()
    await user.selectOptions(screen.getByLabelText('Grupo de UNs'), GR1)
    await waitFor(() => expect(llamadas.filter((l) => l.clave === 'GET /api/bi/tablero').length).toBeGreaterThan(1))
    await user.selectOptions(screen.getByLabelText('Unidad de negocio'), UN1)
    await waitFor(() => expect(llamadas.filter((l) => l.clave === 'GET /api/bi/tablero').length).toBeGreaterThan(2))
  })

  it('el Despachador ve la barra de jornada de §6.8.4 sin mapa', async () => {
    const jornada: Tablero = {
      ...base, tipo: 'jornada', rol: 'despachador',
      jornada: { completados: 7, total_dia: 11, tecnicos_activos: 3, alertas_abiertas: 2,
                 tiempo_promedio_atencion_horas: '2.40',
                 aviso_fase_2: 'El mapa en vivo, el GPS y los desvíos de ruta llegan en Fase 2' },
    }
    await entrar('despachador', '/bi', { 'GET /api/bi/tablero': () => ({ json: jornada }) })
    const barra = await screen.findByTestId('barra-jornada', {}, { timeout: 5000 })
    expect(within(barra).getByTestId('kpi-folios-completados')).toHaveTextContent('7 / 11')
    expect(within(barra).getByTestId('kpi-tecnicos-activos')).toHaveTextContent('3')
    expect(within(barra).getByTestId('kpi-alertas-abiertas')).toHaveTextContent('2')
    expect(within(barra).getByTestId('kpi-atencion-promedio')).toHaveTextContent('2.40 h')
    expect(screen.getByText('El mapa en vivo, el GPS y los desvíos de ruta llegan en Fase 2')).toBeInTheDocument()
  })

  it('la Dirección del prestador ve su histórico de escalaciones en solo lectura', async () => {
    const direccion: Tablero = {
      ...base, tipo: 'direccion', rol: 'direccion_prestador', solo_lectura: true,
      costo: { folios: 12, total: '185400.00' },
      penalizaciones: { periodos: 3, folios_incumplidos: 5, monto: '9800.00', detalle: [] },
      escalaciones: [{ id: 'e1', clave: 'SLA_INCUMPLIDO_ESCALADO_DIRECCION', disparo: '2026-11-01T09:00:00Z',
                       datos: { clave_origen: 'SLA_INCUMPLIDO' }, atendida: false, escalada: false, estado: 'disparada' }],
    }
    await entrar('direccion_prestador', '/bi', { 'GET /api/bi/tablero': () => ({ json: direccion }) })
    const panel = await screen.findByTestId('tablero-direccion', {}, { timeout: 5000 })
    expect(within(panel).getByText('solo lectura')).toBeInTheDocument()
    const tabla = within(panel).getByTestId('escalaciones-direccion')
    expect(tabla).toHaveTextContent('SLA_INCUMPLIDO_ESCALADO_DIRECCION')
    expect(tabla).toHaveTextContent('SLA_INCUMPLIDO')
    expect(within(panel).getByTestId('kpi-penalizacion-acumulada')).toHaveTextContent('$9,800.00')
  })
})

describe('Reportes ejecutivos', () => {
  it('genera un reporte del período y lo registra en el historial', async () => {
    const generado = {
      id: 'rg1', created_at: '2026-11-02T10:00:00Z', updated_at: '2026-11-02T10:00:00Z', version_hash: null,
      programado_id: null, tipo_reporte: 'cliente', formato: 'pdf' as const, archivo_key: 'reportes/t/cliente-2026-11.pdf',
      filas: 24, ms_generacion: 906, generado_at: '2026-11-02T10:00:00Z', filtros_json: { desde: '2026-11-01', hasta: '2026-11-02' },
    }
    let hecho = false
    const llamadas = await entrar('admin_empresa', '/bi/reportes', {
      'GET /api/bi/reportes/generados': () => ({ json: hecho ? [generado] : [] }),
      'GET /api/bi/reportes/programados': () => ({ json: [] }),
      'GET /api/usuarios': () => ({ json: [] }),
      'POST /api/bi/reportes/generar': () => { hecho = true; return { json: { ok: true } } },
    })
    const panel = await screen.findByTestId('generar-reporte', {}, { timeout: 5000 })
    const user = userEvent.setup()
    await user.selectOptions(within(panel).getByLabelText('Formato'), 'excel')
    await user.click(within(panel).getByRole('button', { name: 'Generar y descargar' }))
    await waitFor(() => expect(llamadas.find((l) => l.clave === 'POST /api/bi/reportes/generar')?.cuerpo)
      .toMatchObject({ tipo_reporte: 'cliente', formato: 'excel' }))
    expect(await screen.findByText('Reporte generado y descargado')).toBeInTheDocument()
    const historial = await screen.findByTestId('generados')
    expect(within(historial).getByText('Reporte ejecutivo del cliente')).toBeInTheDocument()
    expect(within(historial).getByText('906 ms')).toBeInTheDocument()
    expect(within(historial).getByText('24')).toBeInTheDocument()
  })

  it('programa un reporte con su periodicidad y destinatarios', async () => {
    const usuarios = [{ id: 'u1', email: 'admin.empresa@acma.dev', nombre: 'Elena Empresa', rol: 'admin_empresa',
                        dominio: 'tenant', tenant_id: T, prestador_id: null, estado: 'activo', mfa_habilitado: false,
                        created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', version_hash: null }]
    let programados: unknown[] = []
    const llamadas = await entrar('admin_empresa', '/bi/reportes', {
      'GET /api/bi/reportes/generados': () => ({ json: [] }),
      'GET /api/bi/reportes/programados': () => ({ json: programados }),
      'GET /api/usuarios': () => ({ json: usuarios }),
      'POST /api/bi/reportes/programados': (cuerpo) => {
        programados = [{ id: 'pr1', created_at: '2026-11-02T10:00:00Z', updated_at: '2026-11-02T10:00:00Z', version_hash: null,
                         tenant_id: T, prestador_id: null, filtros_json: {}, activo: true, ultimo_envio_at: null,
                         ...(cuerpo as object) }]
        return { estado: 201, json: programados[0] }
      },
    })
    await screen.findByTestId('programados', {}, { timeout: 5000 })
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Programar' }))
    const form = await screen.findByTestId('form-programado')
    await user.type(within(form).getByLabelText('Nombre'), 'Ejecutivo semanal')
    await user.selectOptions(within(form).getByLabelText('Periodicidad'), 'semanal')
    expect(within(form).getByLabelText(/Día y hora/)).toHaveValue('lunes 08:00')
    await user.click(within(form).getByLabelText(/Elena Empresa/))
    await user.click(within(form).getByRole('button', { name: 'Programar' }))
    await waitFor(() => expect(llamadas.find((l) => l.clave === 'POST /api/bi/reportes/programados')?.cuerpo)
      .toMatchObject({ nombre: 'Ejecutivo semanal', periodicidad: 'semanal', dia_hora: 'lunes 08:00', destinatarios_json: ['u1'] }))
    expect(await screen.findByText('Reporte programado')).toBeInTheDocument()
    const tabla = await screen.findByTestId('programados')
    expect(within(tabla).getByText('Semanal · lunes 08:00')).toBeInTheDocument()
  })
})
