import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { PerfilConTema, Rol } from '../src/types/api'
import type { FolioDetalle, FolioResumen, PendienteAprobacion, TransicionTabla } from '../src/types/folios'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const T = '11111111-1111-1111-1111-111111111111'
const UN1 = 'u0000000-0000-0000-0000-000000000001'
const UN2 = 'u0000000-0000-0000-0000-000000000002'
const EQ1 = 'e0000000-0000-0000-0000-000000000001'
const TF1 = 'a0000000-0000-0000-0000-000000000001'
const FOLIO = '0f000000-0000-0000-0000-000000000001'
const FAM = 'f0000000-0000-0000-0000-000000000001'

const unidades = [
  { id: UN1, tenant_id: T, nombre: 'Sucursal Centro', codigo: 'SUC-001', direccion: 'Av. Juárez 100, Centro, CDMX', ubicacion: null, zona_horaria: 'America/Mexico_City', estado: 'activo', grupo_id: null },
  { id: UN2, tenant_id: T, nombre: 'Sucursal Polanco', codigo: 'SUC-002', direccion: 'Masaryk 200', ubicacion: null, zona_horaria: 'America/Mexico_City', estado: 'activo', grupo_id: null },
]
const equipo = { id: EQ1, tenant_id: T, un_id: UN1, tipo_equipo_id: 'te000000-0000-0000-0000-000000000001', familia_id: FAM, codigo: 'EQ-0001', nombre: 'Refrigerador vertical', marca: null, modelo: null, numero_serie: null, fecha_instalacion: null, valor_reposicion: null, estado: 'activo', garantia_vigente_hasta: null, contrato_id: null, notas: '', con_contrato_activo: true, en_garantia: false, criticidad: 'B' }
const tiposFalla = [{ id: TF1, prestador_id: 'p1', descripcion: 'No enciende', familia_equipo_id: FAM, requiere_revision_manual: false, activa: true }]

// Tabla §6.8.6 (extracto) tal como la devuelve GET /api/folios/transiciones.
const TRANSICIONES: TransicionTabla[] = [
  { origen: 'autorizado', destino: 'asignado', roles: ['despachador', 'sistema'] },
  { origen: 'autorizado', destino: 'cancelado', roles: ['admin_empresa', 'admin_prestador', 'despachador'] },
  { origen: 'en_ejecucion', destino: 'cerrado', roles: ['sistema', 'tecnico'] },
  { origen: 'en_ejecucion', destino: 'pendiente_refaccion', roles: ['tecnico'] },
  { origen: 'en_revision', destino: 'autorizado', roles: ['admin_prestador', 'despachador', 'sistema'] },
]

function folio(extra: Partial<FolioResumen> = {}): FolioResumen {
  return {
    id: FOLIO, created_at: '2026-10-27T10:00:00Z', updated_at: '2026-10-27T10:00:00Z', version_hash: null, numero_folio: 'CD-000099', tenant_id: T,
    prestador_id: 'p1', un_id: UN1, un_nombre: 'Sucursal Centro', un_codigo: 'SUC-001', equipo_id: EQ1, equipo_codigo: 'EQ-0001', equipo_nombre: 'Refrigerador vertical',
    tipo_falla_id: TF1, tipo_falla: 'No enciende', tipo_folio: 'correctivo', estado: 'autorizado', prioridad: 0, descripcion: 'El refrigerador no enciende desde la mañana',
    tecnico_id: null, tecnico_nombre: null, severidad: { id: 's5', clave: 'critica', nombre: 'Crítica', orden: 5, color_hex: '#D32F2F' }, severidad_origen: 'automatica_matriz',
    confirmacion_un: true, monto_estimado: null, criticidad: 'B', capturado_por: 'op', capturado_por_nombre: 'Olga Operadora', capturado_at: '2026-10-27T10:00:00Z',
    fecha_falla: '2026-10-27T10:00:00Z', fecha_inicio_atencion: null, fecha_cierre: null, razon_cancelacion: null, flujo: null, triggers_pendientes: 0, antiguedad_horas: 2, ...extra,
  }
}

function detalle(f: FolioResumen, extra: Partial<FolioDetalle> = {}): FolioDetalle {
  return {
    folio: f,
    captura: { capturado_por: 'op', capturado_por_nombre: 'Olga Operadora', capturado_at: f.capturado_at, un: { id: UN1, codigo: 'SUC-001', nombre: 'Sucursal Centro', direccion: 'Av. Juárez 100' },
      equipo: { id: EQ1, codigo: 'EQ-0001', nombre: 'Refrigerador vertical', criticidad: 'B' }, tipo_falla: 'No enciende', descripcion: f.descripcion, geolat_captura: null, geolng_captura: null,
      confirmacion_un: true, confirmacion_un_timestamp: f.capturado_at, confirmacion_un_geolat: null, confirmacion_un_geolng: null, folio_duplicado_justificacion: null, folio_duplicado_ref_id: null, folio_duplicado_ref_numero: null },
    formulario_captura: null, asignacion: { tecnico_id: null, tecnico_nombre: null, asignado_at: null, vehiculo: null, orden_en_ruta: null, ventana_inicio: null, ventana_fin: null },
    historial: [{ id: 'h1', evento: 'transicion', estado_anterior: null, estado_nuevo: 'capturado', actor_id: 'op', actor_rol: 'operador', actor_nombre: 'Olga Operadora', timestamp: f.capturado_at, notas: 'Folio capturado', datos_contexto_json: {} },
      { id: 'h2', evento: 'transicion', estado_anterior: 'capturado', estado_nuevo: 'autorizado', actor_id: null, actor_rol: 'sistema', actor_nombre: null, timestamp: f.capturado_at, notas: 'Sin reglas', datos_contexto_json: {} }],
    reasignaciones: [], hallazgos: [], derivaciones: [], clasificacion: null, evidencias: [], formulario_atencion: null, refacciones: [], sla: { nivel_severidad_id: 's5', tiempo_respuesta_prometido_horas: 2, tiempo_resolucion_prometido_horas: 8, tiempo_respuesta_real_min: null, tiempo_resolucion_real_min: null, cumplimiento_respuesta: null, cumplimiento_resolucion: null },
    encuesta: null, triggers_revision: [], aprobacion: null, decisiones: [], chat: [], financiero: {}, acciones: ['asignado', 'cancelado'], puede_aprobar: false, ...extra,
  }
}

async function entrar(rol: Rol, ruta: string, rutas: Parameters<typeof simularApi>[0] = {}, extra: Partial<PerfilConTema> = {}) {
  localStorage.setItem('acma.sesion', '1')  // P11a: solo la marca; el refresh va en cookie httpOnly
  const llamadas = simularApi({
    'POST /api/auth/refresh': () => ({ json: TOKENS }),
    'GET /api/auth/yo': () => ({ json: perfil(rol, { tenant_id: ['operador', 'admin_un', 'admin_empresa', 'supervisor_operadores'].includes(rol) ? T : null, ...extra }) }),
    'GET /api/unidades-negocio': () => ({ json: unidades }),
    'GET /api/catalogos/severidades': () => ({ json: [] }),
    'GET /api/folios/transiciones': () => ({ json: TRANSICIONES }),
    ...rutas,
  })
  renderApp(ruta)
  return llamadas
}

describe('Folios', () => {
  it('captura completa con selector de UN, equipo con contrato, tipo de falla y confirmación obligatoria de UN', async () => {
    const llamadas = await entrar('operador', '/folios/nuevo', {
      'GET /api/catalogos/equipos': (_c, url) => ({ json: url.searchParams.get('con_contrato') === 'true' && url.searchParams.get('un_id') === UN1 ? [equipo] : [] }),
      'GET /api/catalogos/tipos-falla': () => ({ json: tiposFalla }),
      'GET /api/folios/verificar-duplicado': () => ({ json: { existe: false, bloqueo_total: false } }),
      'GET /api/formularios/resolver': () => ({ estado: 404, json: { codigo: 'NO_ENCONTRADO', mensaje: 'Sin formulario', detalles: [] } }),
      'POST /api/folios': () => ({ estado: 201, json: folio({ estado: 'en_revision' }) }),
      'GET /api/folios/0f000000-0000-0000-0000-000000000001': () => ({ json: detalle(folio({ estado: 'en_revision' }), { acciones: [] }) }),
    })
    await screen.findByRole('heading', { name: 'Nuevo folio' })
    await userEvent.type(screen.getByRole('combobox', { name: 'Unidad de negocio' }), 'cen')
    await userEvent.click(await screen.findByRole('button', { name: /SUC-001/ }))
    await userEvent.selectOptions(await screen.findByLabelText('Equipo'), EQ1)
    await userEvent.selectOptions(await screen.findByLabelText('Tipo de falla'), TF1)
    await userEvent.type(screen.getByLabelText('Descripción'), 'No enciende desde la mañana')
    expect(screen.queryByTestId('tarjeta-duplicado')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
    // Paso final obligatorio: nombre y dirección de la UN con los dos únicos botones de §6.8.6.
    await screen.findByRole('heading', { name: 'Confirma la unidad de negocio' })
    expect(screen.getByText('Sucursal Centro')).toBeInTheDocument()
    expect(screen.getByText('Av. Juárez 100, Centro, CDMX')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'No, quiero cambiarla' })).toBeInTheDocument()
    expect(llamadas.some((l) => l.clave === 'POST /api/folios')).toBe(false)
    await userEvent.click(screen.getByRole('button', { name: 'Sí, es esta unidad' }))
    await waitFor(() => expect(llamadas.some((l) => l.clave === 'POST /api/folios')).toBe(true))
    const cuerpo = llamadas.find((l) => l.clave === 'POST /api/folios')!.cuerpo as Record<string, unknown>
    expect(cuerpo).toMatchObject({ un_id: UN1, equipo_id: EQ1, tipo_falla_id: TF1, confirmacion_un: true, descripcion: 'No enciende desde la mañana', respuesta_id: null })
    expect(typeof cuerpo.confirmacion_un_timestamp).toBe('string')
    await screen.findByRole('heading', { name: 'CD-000099' })
  })

  it('«No, quiero cambiarla» regresa a elegir la UN y la tarjeta de duplicado exige justificación', async () => {
    await entrar('admin_un', '/folios/nuevo', {
      'GET /api/catalogos/equipos': () => ({ json: [equipo] }),
      'GET /api/catalogos/tipos-falla': () => ({ json: tiposFalla }),
      'GET /api/folios/verificar-duplicado': () => ({ json: { existe: true, bloqueo_total: false, folio_id: FOLIO, numero_folio: 'CD-000050', estado: 'asignado', descripcion: 'Ya reportado', capturado_at: '2026-10-27T08:00:00Z', tecnico_nombre: 'Tomás Técnico', eta: null, severidad: 'Crítica' } }),
      'GET /api/formularios/resolver': () => ({ estado: 404, json: { codigo: 'NO_ENCONTRADO', mensaje: '', detalles: [] } }),
    })
    await screen.findByRole('heading', { name: 'Nuevo folio' })
    await userEvent.type(screen.getByRole('combobox', { name: 'Unidad de negocio' }), 'suc')
    await userEvent.click(await screen.findByRole('button', { name: /SUC-001/ }))
    await userEvent.selectOptions(await screen.findByLabelText('Equipo'), EQ1)
    const tarjeta = await screen.findByTestId('tarjeta-duplicado')
    expect(within(tarjeta).getByText(/CD-000050/)).toBeInTheDocument()
    expect(within(tarjeta).getByText(/Tomás Técnico/)).toBeInTheDocument()
    await userEvent.selectOptions(await screen.findByLabelText('Tipo de falla'), TF1)
    await userEvent.type(screen.getByLabelText('Descripción'), 'Es otra cosa distinta')
    expect(screen.getByRole('button', { name: 'Continuar' })).toBeDisabled()
    await userEvent.click(within(tarjeta).getByRole('button', { name: 'Es una falla diferente — continuar' }))
    expect(screen.getByRole('button', { name: 'Continuar' })).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Justificación del duplicado'), 'Ahora hace ruido, antes no encendía')
    expect(screen.getByRole('button', { name: 'Continuar' })).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
    await userEvent.click(await screen.findByRole('button', { name: 'No, quiero cambiarla' }))
    expect(await screen.findByRole('combobox', { name: 'Unidad de negocio' })).toBeInTheDocument()
  })

  it('el detalle muestra solo los botones de transiciones válidas para el rol y el estado', async () => {
    const f = folio({ estado: 'autorizado' })
    await entrar('despachador', `/folios/${FOLIO}`, { [`GET /api/folios/${FOLIO}`]: () => ({ json: detalle(f) }) })
    await screen.findByRole('heading', { name: 'CD-000099' })
    const acciones = screen.getByTestId('acciones')
    expect(within(acciones).getByRole('button', { name: 'Asignar técnico' })).toBeInTheDocument()
    expect(within(acciones).getByRole('button', { name: 'Cancelar' })).toBeInTheDocument()
    expect(within(acciones).queryByRole('button', { name: 'Cerrar folio' })).not.toBeInTheDocument()
    expect(within(acciones).queryByRole('button', { name: 'Autorizar' })).not.toBeInTheDocument()
    expect(screen.getByText(/Respuesta 2 h · Resolución 8 h/)).toBeInTheDocument()
    expect(screen.getByText('Capturado → Autorizado')).toBeInTheDocument()
  })

  it('un técnico en ejecución ve Cerrar folio y Pendiente de refacción; el operador no ve acciones', async () => {
    const f = folio({ estado: 'en_ejecucion', tecnico_id: 't1', tecnico_nombre: 'Tomás Técnico' })
    await entrar('tecnico', `/folios/${FOLIO}`, { [`GET /api/folios/${FOLIO}`]: () => ({ json: detalle(f, { acciones: ['cerrado', 'pendiente_refaccion'] }) }) })
    await screen.findByRole('heading', { name: 'CD-000099' })
    expect(screen.getByRole('button', { name: 'Cerrar folio' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Pendiente de refacción' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Cancelar' })).not.toBeInTheDocument()
  })

  it('bandeja de aprobación: Aprobar / Rechazar y rechazo en dos pasos con las cuatro razones', async () => {
    const pendiente: PendienteAprobacion = {
      folio: folio({ estado: 'en_revision', flujo: { id: 'fl1', nivel_actual: 1, nivel_maximo_requerido: 1, estado: 'activo', iniciado_at: '2026-10-27T10:00:00Z', resuelto_at: null, rol_aprobador_actual: 'admin_un', vence_at: null } }),
      flujo: { id: 'fl1', nivel_actual: 1, nivel_maximo_requerido: 1, estado: 'activo', iniciado_at: '2026-10-27T10:00:00Z', resuelto_at: null, rol_aprobador_actual: 'admin_un', vence_at: null },
      vence_at: null,
    }
    let pendientes = [pendiente]
    const llamadas = await entrar('admin_un', '/folios/aprobaciones', {
      'GET /api/folios/pendientes-aprobacion': () => ({ json: pendientes }),
      [`POST /api/folios/${FOLIO}/aprobacion/rechazar`]: () => { pendientes = []; return { json: folio({ estado: 'cancelado' }) } },
    })
    const tarjeta = await screen.findByTestId('pendiente-CD-000099')
    expect(within(tarjeta).getByRole('button', { name: 'Aprobar' })).toBeInTheDocument()
    expect(within(tarjeta).getByText('Nivel 1 de 1')).toBeInTheDocument()
    await userEvent.click(within(tarjeta).getByRole('button', { name: 'Rechazar' }))
    const razones = await screen.findByTestId('razones-rechazo')
    expect(within(razones).getAllByRole('radio')).toHaveLength(4)
    expect(within(razones).getByText('Módulo: Cotizaciones')).toBeInTheDocument()
    expect(within(razones).getByRole('button', { name: 'Confirmar rechazo' })).toBeDisabled()
    await userEvent.click(within(razones).getByLabelText(/Requiere cotización primero/))
    await userEvent.click(within(razones).getByRole('button', { name: 'Confirmar rechazo' }))
    await waitFor(() => expect(llamadas.some((l) => l.clave === `POST /api/folios/${FOLIO}/aprobacion/rechazar`)).toBe(true))
    expect(llamadas.find((l) => l.clave === `POST /api/folios/${FOLIO}/aprobacion/rechazar`)!.cuerpo).toMatchObject({ canal: 'app', razon_rechazo: 'requiere_cotizacion' })
    await screen.findByText('No tienes folios pendientes de autorización.')
    expect(screen.queryByText('Configuración del flujo de aprobación (Admin empresa)')).not.toBeInTheDocument()
  })

  it('el listado muestra estado, severidad con color y antigüedad, y cambia a Kanban', async () => {
    await entrar('admin_empresa', '/folios', { 'GET /api/folios': () => ({ json: [folio(), folio({ id: 'x2', numero_folio: 'CD-000100', estado: 'cerrado', antiguedad_horas: 72 })] }) })
    await screen.findByRole('heading', { name: 'Folios' })
    expect(await screen.findByText('CD-000099')).toBeInTheDocument()
    expect(screen.getByTestId('estado-autorizado')).toHaveTextContent('Autorizado')
    expect(screen.getAllByText('Crítica')[0]).toHaveStyle({ color: '#D32F2F' })
    expect(screen.getByText('3 d')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Nuevo folio' })).toHaveAttribute('href', '/folios/nuevo')
    await userEvent.click(screen.getByRole('button', { name: 'Kanban' }))
    const kanban = await screen.findByTestId('kanban')
    expect(within(within(kanban).getByRole('region', { name: 'Cerrado' })).getByTestId('folio-CD-000100')).toBeInTheDocument()
  })
})
