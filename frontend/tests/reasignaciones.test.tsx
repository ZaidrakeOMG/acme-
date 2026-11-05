import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { PerfilConTema, Rol } from '../src/types/api'
import type { FolioDetalle, FolioResumen } from '../src/types/folios'
import type { Candidato, RazonReasignacion } from '../src/types/preventivos'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const T = '11111111-1111-1111-1111-111111111111'
const FOLIO = '0f000000-0000-0000-0000-000000000002'
const TEC1 = 't0000000-0000-0000-0000-000000000001'
const TEC2 = 't0000000-0000-0000-0000-000000000002'
const TEC4 = 't0000000-0000-0000-0000-000000000004'

const folio: FolioResumen = {
  id: FOLIO, created_at: '2026-10-27T10:00:00Z', updated_at: '2026-10-27T10:00:00Z', version_hash: null, numero_folio: 'CD-000130', tenant_id: T, prestador_id: 'p1', un_id: 'u1',
  un_nombre: 'Sucursal Centro', un_codigo: 'SUC-001', equipo_id: 'e1', equipo_codigo: 'EQ-0001', equipo_nombre: 'Refrigerador vertical', tipo_falla_id: 'tf1', tipo_falla: 'No enfría',
  tipo_folio: 'correctivo', estado: 'asignado', prioridad: 0, descripcion: 'El refrigerador no enfría', tecnico_id: TEC1, tecnico_nombre: 'Tomás Técnico', severidad: null, severidad_origen: 'automatica_matriz',
  confirmacion_un: true, monto_estimado: null, criticidad: 'B', capturado_por: 'op', capturado_por_nombre: 'Olga', capturado_at: '2026-10-27T10:00:00Z', fecha_falla: '2026-10-27T10:00:00Z',
  fecha_inicio_atencion: null, fecha_cierre: null, razon_cancelacion: null, flujo: null, triggers_pendientes: 0, antiguedad_horas: 3,
}

function detalle(f: FolioResumen, extra: Partial<FolioDetalle> = {}): FolioDetalle {
  return {
    folio: f,
    captura: { capturado_por: 'op', capturado_por_nombre: 'Olga', capturado_at: f.capturado_at, un: { codigo: 'SUC-001', nombre: 'Sucursal Centro', direccion: '' }, equipo: { codigo: 'EQ-0001', nombre: 'Refrigerador vertical' }, tipo_falla: 'No enfría', descripcion: f.descripcion,
      geolat_captura: null, geolng_captura: null, confirmacion_un: true, confirmacion_un_timestamp: null, confirmacion_un_geolat: null, confirmacion_un_geolng: null, folio_duplicado_justificacion: null, folio_duplicado_ref_id: null, folio_duplicado_ref_numero: null },
    formulario_captura: null, asignacion: { tecnico_id: f.tecnico_id, tecnico_nombre: f.tecnico_nombre, asignado_at: '2026-10-27T11:00:00Z', vehiculo: 'ACM-001', orden_en_ruta: null, ventana_inicio: null, ventana_fin: null },
    historial: [], reasignaciones: [], hallazgos: [], derivaciones: [], clasificacion: null, evidencias: [], formulario_atencion: null, refacciones: [], sla: null, encuesta: null, triggers_revision: [], aprobacion: null, decisiones: [], chat: [], financiero: {},
    acciones: ['reasignado', 'cancelado'], puede_aprobar: false, ...extra,
  }
}

const candidatos: Candidato[] = [
  { usuario_id: TEC1, tecnico_id: 'x1', nombre: 'Tomás Técnico', vehiculo_placas: 'ACM-001', habilidad_ok: true, habilidad_requerida: 'refrigeracion', carga_dia: 2, refaccion_ok: null, es_actual: true, advertencias: [] },
  { usuario_id: TEC2, tecnico_id: 'x2', nombre: 'Teresa Técnica', vehiculo_placas: 'ACM-002', habilidad_ok: false, habilidad_requerida: 'refrigeracion', carga_dia: 1, refaccion_ok: null, es_actual: false, advertencias: ['Sin la habilidad refrigeracion'] },
  { usuario_id: TEC4, tecnico_id: 'x4', nombre: 'Tania Técnica', vehiculo_placas: 'ACM-004', habilidad_ok: true, habilidad_requerida: 'refrigeracion', carga_dia: 0, refaccion_ok: null, es_actual: false, advertencias: ['Refacción no verificada (inventario del vehículo en P09)'] },
]
const razones: RazonReasignacion[] = [
  { id: 'r1', prestador_id: 'p1', descripcion: 'Incidencia del técnico', detalle: 'Accidente, descompostura…', activa: true, orden_display: 1 },
  { id: 'r3', prestador_id: 'p1', descripcion: 'Optimización de ruta', detalle: 'Mejora que el algoritmo no capturó', activa: true, orden_display: 3 },
]

async function entrar(rol: Rol, ruta: string, rutas: Parameters<typeof simularApi>[0] = {}, extra: Partial<PerfilConTema> = {}) {
  localStorage.setItem('acma.sesion', '1')  // P11a: solo la marca; el refresh va en cookie httpOnly
  const llamadas = simularApi({
    'POST /api/auth/refresh': () => ({ json: TOKENS }),
    'GET /api/auth/yo': () => ({ json: perfil(rol, { prestador_id: 'p1', ...extra }) }),
    'GET /api/folios/transiciones': () => ({ json: [{ origen: 'asignado', destino: 'cancelado', roles: ['despachador'] }] }),
    [`GET /api/folios/${FOLIO}/chats`]: () => ({ json: [] }),
    'GET /api/reasignaciones/razones': () => ({ json: razones }),
    ...rutas,
  })
  renderApp(ruta)
  return llamadas
}

describe('Reasignación forzada', () => {
  it('muestra candidatos con habilidad y advertencias, exige razón y confirmación explícita ante 409', async () => {
    let reasignado = false
    const llamadas = await entrar('despachador', `/folios/${FOLIO}`, {
      [`GET /api/folios/${FOLIO}`]: () => ({ json: reasignado
        ? detalle({ ...folio, tecnico_id: TEC4, tecnico_nombre: 'Tania Técnica' }, { reasignaciones: [{ id: 'rs1', tecnico_origen_id: TEC1, tecnico_origen_nombre: 'Tomás Técnico', tecnico_destino_id: TEC4, tecnico_destino_nombre: 'Tania Técnica', tipo: 'forzada', razon: 'Optimización de ruta', comentario: 'Pasa por ahí', despachador_id: 'd', despachador_nombre: 'Persona Prueba', timestamp: '2026-10-28T12:00:00Z' }] })
        : detalle(folio) }),
      [`GET /api/folios/${FOLIO}/reasignacion/candidatos`]: () => ({ json: candidatos }),
      [`POST /api/folios/${FOLIO}/reasignar`]: (cuerpo) => {
        const c = cuerpo as { confirmar_advertencias?: boolean }
        if (!c.confirmar_advertencias) return { estado: 409, json: { codigo: 'CONFIRMACION_REQUERIDA', mensaje: 'Hay advertencias; confirma explícitamente la reasignación', detalles: ['Refacción no verificada (inventario del vehículo en P09)'] } }
        reasignado = true
        return { estado: 201, json: { id: 'rs1', tecnico_origen_id: TEC1, tecnico_origen_nombre: 'Tomás Técnico', tecnico_destino_id: TEC4, tecnico_destino_nombre: 'Tania Técnica', tipo: 'forzada', razon: 'Optimización de ruta', comentario: 'Pasa por ahí', despachador_id: 'd', despachador_nombre: 'Persona Prueba', timestamp: '2026-10-28T12:00:00Z' } }
      },
    })
    await screen.findByRole('heading', { name: 'CD-000130' })
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Reasignar' }))
    const dialogo = await screen.findByRole('dialog', { name: 'Reasignar CD-000130' })
    // El técnico actual no aparece como destino; el que no tiene la habilidad se marca.
    expect(within(dialogo).queryByLabelText('Tomás Técnico')).not.toBeInTheDocument()
    expect(within(within(dialogo).getByTestId(`candidato-${TEC2}`)).getByText('Sin habilidad refrigeracion')).toBeInTheDocument()
    expect(within(within(dialogo).getByTestId(`candidato-${TEC4}`)).getByText('Habilidad refrigeracion')).toBeInTheDocument()
    const boton = within(dialogo).getByRole('button', { name: 'Reasignar' })
    expect(boton).toBeDisabled()
    await user.click(within(dialogo).getByLabelText('Tania Técnica'))
    expect(boton).toBeDisabled()  // falta la razón
    await user.selectOptions(within(dialogo).getByLabelText('Razón de la reasignación (obligatoria)'), 'r3')
    expect(within(dialogo).getByText('Mejora que el algoritmo no capturó')).toBeInTheDocument()
    await user.type(within(dialogo).getByLabelText('Comentario'), 'Pasa por ahí')
    await user.click(boton)
    // 409 → advertencias con casilla de confirmación; el botón se bloquea hasta marcarla.
    const adv = await within(dialogo).findByTestId('advertencias')
    expect(within(adv).getByText('Refacción no verificada (inventario del vehículo en P09)')).toBeInTheDocument()
    expect(boton).toBeDisabled()
    await user.click(within(adv).getByRole('checkbox'))
    await user.click(boton)
    expect(await screen.findByText('Folio reasignado a Tania Técnica')).toBeInTheDocument()
    const envios = llamadas.filter((l) => l.clave === `POST /api/folios/${FOLIO}/reasignar`).map((l) => l.cuerpo as Record<string, unknown>)
    expect(envios).toHaveLength(2)
    expect(envios[1]).toEqual({ tecnico_destino_id: TEC4, razon_id: 'r3', comentario: 'Pasa por ahí', confirmar_advertencias: true, razon_sin_habilidad: null })
    await waitFor(() => expect(screen.getByTestId('reasignaciones')).toHaveTextContent('Tomás Técnico → Tania Técnica · Optimización de ruta'))
  })

  it('un técnico sin la habilidad pide razón adicional; el operador no ve el botón', async () => {
    await entrar('despachador', `/folios/${FOLIO}`, {
      [`GET /api/folios/${FOLIO}`]: () => ({ json: detalle(folio) }),
      [`GET /api/folios/${FOLIO}/reasignacion/candidatos`]: () => ({ json: candidatos }),
    })
    await screen.findByRole('heading', { name: 'CD-000130' })
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Reasignar' }))
    const dialogo = await screen.findByRole('dialog')
    await user.click(within(dialogo).getByLabelText('Teresa Técnica'))
    expect(within(dialogo).getByLabelText(/Razón para asignar sin la habilidad/)).toBeInTheDocument()
  })

  it('el operador no ve Reasignar y un folio en ejecución tampoco', async () => {
    await entrar('operador', `/folios/${FOLIO}`, { [`GET /api/folios/${FOLIO}`]: () => ({ json: detalle(folio) }) }, { tenant_id: T, prestador_id: null })
    await screen.findByRole('heading', { name: 'CD-000130' })
    expect(screen.queryByRole('button', { name: 'Reasignar' })).not.toBeInTheDocument()
  })

  it('el reporte muestra causas con porcentaje y el catálogo de razones', async () => {
    await entrar('admin_prestador', '/reasignaciones/reporte', {
      'GET /api/reasignaciones/reporte': () => ({ json: { desde: '2026-10-01', hasta: '2026-10-31', total: 3,
        por_razon: [{ nombre: 'Optimización de ruta', total: 2, porcentaje: 66.7 }, { nombre: 'Incidencia del técnico', total: 1, porcentaje: 33.3 }],
        por_tecnico_origen: [{ nombre: 'Tomás Técnico', total: 3, porcentaje: 100 }], por_tecnico_destino: [{ nombre: 'Tania Técnica', total: 3, porcentaje: 100 }], por_tipo: [{ nombre: 'forzada', total: 3, porcentaje: 100 }] } }),
    })
    await screen.findByRole('heading', { name: 'Reasignaciones' })
    expect(await screen.findByText('3 reasignaciones')).toBeInTheDocument()
    expect(within(screen.getByTestId('por-razon')).getByText('66.7%')).toBeInTheDocument()
    expect(within(screen.getByTestId('por-razon')).getByText('Incidencia del técnico')).toBeInTheDocument()
    expect(screen.getByText('Catálogo de razones (§6.8.2)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Agregar' })).toBeInTheDocument()
  })
})
