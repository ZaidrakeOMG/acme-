import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { PerfilConTema, Rol } from '../src/types/api'
import type { ActivoResumen, AlertaReemplazo, FichaActivo } from '../src/types/inventario'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const T = '11111111-1111-1111-1111-111111111111'
const UN1 = 'u0000000-0000-0000-0000-000000000001'
const EQ = 'e0000000-0000-0000-0000-000000000001'
const ALERTA = 'al000000-0000-0000-0000-000000000001'

const unidades = [{ id: UN1, tenant_id: T, nombre: 'Sucursal Centro', codigo: 'SUC-001', direccion: 'Av. Juárez 100', ubicacion: null, zona_horaria: 'America/Mexico_City', estado: 'activo', grupo_id: null }]

function alerta(extra: Partial<AlertaReemplazo> = {}): AlertaReemplazo {
  return {
    id: ALERTA, equipo_id: EQ, tenant_id: T, equipo_codigo: 'EQ-0001', equipo_nombre: 'Refrigerador vertical', un_codigo: 'SUC-001',
    fecha_alerta: '2026-10-28', tco_al_momento: '88000.00', valor_reposicion: '110000.00', porcentaje_umbral: '70', porcentaje_alcanzado: '80',
    decision: null, razon: '', decidido_por: null, decidido_at: null, trabajo_especial_id: null, created_at: '2026-10-28T10:00:00Z',
    updated_at: '2026-10-28T10:00:00Z', ...extra,
  }
}

const resumen: ActivoResumen = {
  id: EQ, codigo: 'EQ-0001', nombre: 'Refrigerador vertical', marca: 'Imbera', modelo: 'VR-12', numero_serie: 'IMB-0451', estado: 'activo',
  criticidad: 'A', un_id: UN1, un_codigo: 'SUC-001', un_nombre: 'Sucursal Centro', tenant_id: T, costo_adquisicion: '60000.00',
  fecha_adquisicion: '2022-03-01', fecha_instalacion: '2022-03-15', valor_reposicion: '110000.00', numero_activo_fijo_erp: 'AF-0001',
  tco_total: '88000.00', porcentaje_vs_reposicion: '80', periodo_tco: '2026-10', alerta_reemplazo: true, alerta_reemplazo_id: ALERTA,
}

function ficha(extra: Partial<FichaActivo> = {}): FichaActivo {
  return {
    equipo: { id: EQ, codigo: 'EQ-0001', nombre: 'Refrigerador vertical', marca: 'Imbera', modelo: 'VR-12', numero_serie: 'IMB-0451', estado: 'activo',
      criticidad: 'A', criticidad_origen: 'manual', un_codigo: 'SUC-001', un_nombre: 'Sucursal Centro', tipo_equipo: 'Refrigeración comercial',
      fecha_instalacion: '2022-03-15', costo_adquisicion: '60000.00', fecha_adquisicion: '2022-03-01', valor_reposicion: '110000.00',
      costo_hora_inactividad: '450.00', garantia_vigente_hasta: null, numero_activo_fijo_erp: 'AF-0001' },
    contrato: { nombre: 'Contrato integral 2026', modalidad: 'integral', fecha_inicio: '2026-01-01', fecha_fin: '2026-12-31' },
    historial_folios: [
      { id: '0f000000-0000-0000-0000-000000000001', numero_folio: 'CD-000011', tipo_folio: 'correctivo', estado: 'cerrado', tipo_falla: 'No enfría',
        descripcion: 'Compresor con fuga', capturado_at: '2026-09-10T10:00:00Z', fecha_cierre: '2026-09-10T18:00:00Z', tecnico_nombre: 'Tomás Técnico',
        costo_total: '12500.00', costo_validado: true, plan_nombre: null, desvio: null },
      { id: '0f000000-0000-0000-0000-000000000002', numero_folio: 'PV-000004', tipo_folio: 'preventivo', estado: 'cerrado', tipo_falla: null,
        descripcion: 'Mantenimiento trimestral', capturado_at: '2026-10-01T10:00:00Z', fecha_cierre: '2026-10-01T13:00:00Z', tecnico_nombre: 'Tomás Técnico',
        costo_total: '3200.00', costo_validado: false, plan_nombre: 'Trimestral de refrigeradores', desvio: '2 días' },
    ],
    refacciones: [{ id: 'rf1', descripcion: 'Compresor 1/3 HP', cantidad: '1', origen: 'oc', costo_unitario: '8200.00', folio_id: '0f000000-0000-0000-0000-000000000001', importe: '8200.00' }],
    depreciacion: { metodo: 'linea_recta', vida_util_anios: 10, valor_salvamento: '6000.00', valor_reposicion: '110000.00', unidades_vida_util: null,
      unidades_acumuladas: '0', valor_en_libros_manual: null, fecha_inicio: '2022-03-01', aviso: '' },
    depreciacion_historial: [
      { periodo: '2026-08', valor_en_libros: '33300.00', depreciacion_periodo: '450.00', depreciacion_acumulada: '26700.00', metodo_aplicado: 'linea_recta' },
      { periodo: '2026-09', valor_en_libros: '32850.00', depreciacion_periodo: '450.00', depreciacion_acumulada: '27150.00', metodo_aplicado: 'linea_recta' },
      { periodo: '2026-10', valor_en_libros: '32400.00', depreciacion_periodo: '450.00', depreciacion_acumulada: '27600.00', metodo_aplicado: 'linea_recta' },
    ],
    tco: { periodo: '2026-10', costo_adquisicion: '60000.00', costo_preventivos: '3200.00', costo_correctivos: '12500.00', costo_refacciones: '8200.00',
      costo_downtime: '44700.00', horas_downtime: '99.3', valor_residual: '32400.00', tco_total: '88000.00', valor_reposicion: '110000.00',
      porcentaje_vs_reposicion: '80', folios: 2, aviso: '' },
    tco_historial: [{ periodo: '2026-10', tco_total: '88000.00', porcentaje_vs_reposicion: '80', costo_preventivos: '3200.00', costo_correctivos: '12500.00',
      costo_refacciones: '8200.00', costo_downtime: '44700.00', valor_residual: '32400.00' }],
    alerta_reemplazo: alerta(),
    umbral_reemplazo_pct: '70',
    // F2-04 saco los medidores de esta lista: ya tienen su propio modulo y su pestaña en la ficha.
    fase_2: ['Criticidad automática por FMEA', 'MTBF y MTTR por equipo'],
    ...extra,
  }
}

async function entrar(rol: Rol, ruta: string, rutas: Parameters<typeof simularApi>[0] = {}, extra: Partial<PerfilConTema> = {}) {
  localStorage.setItem('acma.sesion', '1')  // P11a: solo la marca; el refresh va en cookie httpOnly
  const llamadas = simularApi({
    'POST /api/auth/refresh': () => ({ json: TOKENS }),
    'GET /api/auth/yo': () => ({ json: perfil(rol, { tenant_id: T, ...extra }) }),
    'GET /api/notificaciones/no-leidas': () => ({ json: { no_leidas: 0 } }),
    'GET /api/unidades-negocio': () => ({ json: unidades }),
    ...rutas,
  })
  renderApp(ruta)
  return llamadas
}

describe('Equipos y activos', () => {
  it('la ficha del equipo desglosa el TCO, la depreciación y el historial de folios con sus costos', async () => {
    await entrar('admin_empresa', `/activos/${EQ}`, { [`GET /api/activos/${EQ}`]: () => ({ json: ficha() }) })
    await screen.findByRole('heading', { name: 'EQ-0001 · Refrigerador vertical' })
    expect(screen.getByTestId('tco-total')).toHaveTextContent('$88,000.00')
    expect(screen.getByText('80.0% del valor de reposición ($110,000.00) · umbral 70%')).toBeInTheDocument()
    const componentes = screen.getByTestId('componentes-tco')
    expect(within(componentes).getByText('Costo de adquisición').nextSibling).toHaveTextContent('$60,000.00')
    expect(within(componentes).getByText('Preventivos acumulados').nextSibling).toHaveTextContent('$3,200.00')
    expect(within(componentes).getByText('Correctivos acumulados').nextSibling).toHaveTextContent('$12,500.00')
    expect(within(componentes).getByText('Tiempo de inactividad').nextSibling).toHaveTextContent('$44,700.00')
    expect(within(componentes).getByText('Valor residual (se resta)').nextSibling).toHaveTextContent('$32,400.00')
    expect(screen.getByText('99.3 h de inactividad en 2 folio(s) cerrados. Las refacciones ya están incluidas en los costos de preventivos y correctivos.')).toBeInTheDocument()
    expect(screen.getByText('Línea recta · vida útil 10 años · salvamento $6,000.00 · desde 2022-03-01')).toBeInTheDocument()
    const grafica = screen.getByTestId('grafica-depreciacion')
    expect(within(grafica).getByRole('img', { name: 'Evolución del valor en libros' })).toBeInTheDocument()
    expect(within(grafica).getByText('2026-10: en libros $32,400.00 · del período $450.00 · acumulada $27,600.00')).toBeInTheDocument()
    expect(screen.getByText('Contrato Contrato integral 2026 (integral) vigente de 2026-01-01 a 2026-12-31')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'CD-000011' })).toHaveAttribute('href', '/folios/0f000000-0000-0000-0000-000000000001')
    expect(screen.getByText('validado')).toBeInTheDocument()
    expect(within(screen.getByTestId('refacciones-activo')).getByText(/Compresor 1\/3 HP — 1 · \$8,200\.00/)).toBeInTheDocument()
    expect(screen.getByText('MTBF y MTTR por equipo')).toBeInTheDocument()
    // F2-04: la ficha ahora tiene pestaña de medidores, y los medidores ya no son Fase 2.
    expect(screen.getByRole('button', { name: 'Medidores' })).toBeInTheDocument()
  })

  it('el Admin empresa acepta el reemplazo desde la ficha y se genera el trabajo especial para cotizar', async () => {
    let decidida = false
    const llamadas = await entrar('admin_empresa', `/activos/${EQ}`, {
      [`GET /api/activos/${EQ}`]: () => ({ json: decidida
        ? ficha({ alerta_reemplazo: alerta({ decision: 'aceptado', razon: '', trabajo_especial_id: 'te1', decidido_at: '2026-10-29T10:00:00Z' }) })
        : ficha() }),
      [`POST /api/activos/alertas-reemplazo/${ALERTA}/decidir`]: () => {
        decidida = true
        return { json: { alerta: alerta({ decision: 'aceptado', trabajo_especial_id: 'te1' }), trabajo_especial: { id: 'te1', numero: 'TE-000007', estado: 'creado' } } }
      },
    })
    expect(await screen.findByText(/El costo total de propiedad acumulado \(\$88,000\.00\) superó el umbral del 70% sobre \$110,000\.00 de reposición\./)).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Decidir: reemplazar o reparar' }))
    const panel = await screen.findByTestId('decision-ficha')
    expect(within(panel).getByRole('button', { name: 'Posponer' })).toBeDisabled()
    await user.click(within(panel).getByRole('button', { name: 'Aceptar reemplazo' }))
    await waitFor(() => expect(llamadas.find((l) => l.clave === `POST /api/activos/alertas-reemplazo/${ALERTA}/decidir`)?.cuerpo).toEqual({ decision: 'aceptado', razon: '' }))
    expect(await screen.findByText('Reemplazo aceptado: trabajo especial TE-000007 creado para que el prestador lo cotice')).toBeInTheDocument()
    expect(await screen.findByText(/Decisión registrada: reemplazo aceptado/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'ver el trabajo especial' })).toHaveAttribute('href', '/trabajos-especiales?registro=te1')
    expect(screen.queryByRole('button', { name: 'Decidir: reemplazar o reparar' })).not.toBeInTheDocument()
  })

  it('el listado marca el reemplazo recomendado y el Admin UN no decide ni cambia el umbral', async () => {
    await entrar('admin_un', '/activos', {
      'GET /api/activos': () => ({ json: [resumen] }),
      'GET /api/activos/alertas-reemplazo': () => ({ json: [] }),
    })
    expect(await screen.findByText('Reemplazo recomendado')).toBeInTheDocument()
    expect(screen.getByText('80.0%')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'EQ-0001' })).toHaveAttribute('href', `/activos/${EQ}`)
    expect(screen.queryByRole('button', { name: 'Umbral de reemplazo' })).not.toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: 'Reemplazos recomendados' }))
    const tabla = await screen.findByTestId('alertas-reemplazo')
    expect(within(tabla).getByText('No hay reemplazos recomendados pendientes de decisión')).toBeInTheDocument()
  })
})
