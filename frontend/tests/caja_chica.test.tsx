import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { PerfilConTema, Rol } from '../src/types/api'
import type { FolioDetalle, FolioResumen } from '../src/types/folios'
import type { Fondo, Gasto } from '../src/types/inventario'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const T = '11111111-1111-1111-1111-111111111111'
const UN1 = 'u0000000-0000-0000-0000-000000000001'
const EQ1 = 'e0000000-0000-0000-0000-000000000001'
const FOLIO = '0f000000-0000-0000-0000-000000000061'
const GASTO = 'g0000000-0000-0000-0000-000000000001'

const fondo: Fondo = {
  id: 'fo1', prestador_id: 'p1', tecnico_id: 't1', tecnico_nombre: 'Tomás Técnico', monto_inicial: '5000.00', saldo_actual: '3200.00', moneda: 'MXN',
  umbral_alerta_pct: '20', porcentaje_saldo: '64', bajo_umbral: false, gastos_pendientes: 1, fecha_ultima_reposicion: '2026-10-01', activo: true,
  created_at: '2026-10-01T10:00:00Z', updated_at: '2026-10-28T10:00:00Z',
}

function gasto(extra: Partial<Gasto> = {}): Gasto {
  return {
    id: GASTO, prestador_id: 'p1', tenant_id: T, fondo_id: 'fo1', folio_id: FOLIO, numero_folio: 'CD-000061', tecnico_id: 't1', tecnico_nombre: 'Tomás Técnico',
    proveedor: 'Refaccionaria El Tornillo', rfc_proveedor: 'RET980101AB1', uuid_cfdi: 'A1B2C3D4-0000-0000-0000-000000000001', descripcion: 'Capacitor de arranque 35 µF',
    numero_parte: 'CAP-35', articulo_id: null, articulo_codigo: null, cantidad: '1', subtotal: '620.00', iva: '99.20', monto: '719.20', estado: 'capturado',
    estado_cfdi: 'no_validado', imagen_disponible: false, aprobado_por: null, aprobado_por_nombre: null, aprobado_at: null, razon_rechazo: null,
    centro_costos: 'MANTENIMIENTO', cuenta_contable: '5101-001', poliza_id: null, timestamp: '2026-10-28T11:30:00Z', created_at: '2026-10-28T11:30:00Z',
    updated_at: '2026-10-28T11:30:00Z', ...extra,
  }
}

function folio(extra: Partial<FolioResumen> = {}): FolioResumen {
  return {
    id: FOLIO, created_at: '2026-10-28T10:00:00Z', updated_at: '2026-10-28T10:00:00Z', version_hash: null, numero_folio: 'CD-000061', tenant_id: T, prestador_id: 'p1',
    un_id: UN1, un_nombre: 'Sucursal Centro', un_codigo: 'SUC-001', equipo_id: EQ1, equipo_codigo: 'EQ-0001', equipo_nombre: 'Refrigerador vertical', tipo_falla_id: 'tf1',
    tipo_falla: 'No enfría', tipo_folio: 'correctivo', estado: 'en_ejecucion', prioridad: 0, descripcion: 'El refrigerador no enfría', tecnico_id: 't1', tecnico_nombre: 'Tomás Técnico',
    severidad: null, severidad_origen: 'automatica_matriz', confirmacion_un: true, monto_estimado: null, criticidad: 'B', capturado_por: 'op', capturado_por_nombre: 'Olga Operadora',
    capturado_at: '2026-10-28T10:00:00Z', fecha_falla: '2026-10-28T09:00:00Z', fecha_inicio_atencion: '2026-10-28T10:30:00Z', fecha_cierre: null, razon_cancelacion: null,
    flujo: null, triggers_pendientes: 0, antiguedad_horas: 2, ...extra,
  }
}

function detalle(f: FolioResumen, extra: Partial<FolioDetalle> = {}): FolioDetalle {
  return {
    folio: f,
    captura: { capturado_por: 'op', capturado_por_nombre: 'Olga Operadora', capturado_at: f.capturado_at, un: { id: UN1, codigo: 'SUC-001', nombre: 'Sucursal Centro', direccion: 'Av. Juárez 100' },
      equipo: { id: EQ1, codigo: 'EQ-0001', nombre: 'Refrigerador vertical', criticidad: 'B' }, tipo_falla: 'No enfría', descripcion: f.descripcion, geolat_captura: null, geolng_captura: null,
      confirmacion_un: true, confirmacion_un_timestamp: f.capturado_at, confirmacion_un_geolat: null, confirmacion_un_geolng: null, folio_duplicado_justificacion: null,
      folio_duplicado_ref_id: null, folio_duplicado_ref_numero: null },
    formulario_captura: null, asignacion: { tecnico_id: 't1', tecnico_nombre: 'Tomás Técnico', asignado_at: '2026-10-28T10:10:00Z', vehiculo: null, orden_en_ruta: 1, ventana_inicio: null, ventana_fin: null },
    historial: [], reasignaciones: [], hallazgos: [], derivaciones: [], clasificacion: null, evidencias: [], formulario_atencion: null, refacciones: [],
    sla: { nivel_severidad_id: 's3', tiempo_respuesta_prometido_horas: 4, tiempo_resolucion_prometido_horas: 24, tiempo_respuesta_real_min: null, tiempo_resolucion_real_min: null, cumplimiento_respuesta: null, cumplimiento_resolucion: null },
    encuesta: null, triggers_revision: [], aprobacion: null, decisiones: [], chat: [], financiero: {}, acciones: [], puede_aprobar: false, ...extra,
  }
}

async function entrar(rol: Rol, ruta: string, rutas: Parameters<typeof simularApi>[0] = {}, extra: Partial<PerfilConTema> = {}) {
  localStorage.setItem('acma.sesion', '1')  // P11a: solo la marca; el refresh va en cookie httpOnly
  const llamadas = simularApi({
    'POST /api/auth/refresh': () => ({ json: TOKENS }),
    'GET /api/auth/yo': () => ({ json: perfil(rol, { prestador_id: 'p1', ...extra }) }),
    'GET /api/notificaciones/no-leidas': () => ({ json: { no_leidas: 0 } }),
    'GET /api/caja-chica/fondos': () => ({ json: [fondo] }),
    ...rutas,
  })
  renderApp(ruta)
  return llamadas
}

describe('Caja chica', () => {
  it('el Admin prestador aprueba el gasto en un toque y queda registrada la refacción y el descuento al fondo', async () => {
    let aprobado = false
    const llamadas = await entrar('admin_prestador', `/caja-chica?gasto=${GASTO}`, {
      'GET /api/caja-chica/gastos': (_c, url) => {
        const filtro = url.searchParams.get('estado')
        const actual = aprobado ? gasto({ estado: 'aprobado', aprobado_por: 'ap', aprobado_por_nombre: 'Persona Prueba', aprobado_at: '2026-10-28T12:00:00Z' }) : gasto()
        return { json: filtro && filtro !== actual.estado ? [] : [actual] }
      },
      [`POST /api/caja-chica/gastos/${GASTO}/aprobar`]: () => {
        aprobado = true
        return { json: { gasto: gasto({ estado: 'aprobado' }), refaccion_id: 'rf1', movimientos: ['mv1', 'mv2'], saldo_fondo: '2480.80' } }
      },
    })
    const panel = await screen.findByTestId('detalle-gasto', {}, { timeout: 5000 })
    expect(within(panel).getByText('Capacitor de arranque 35 µF')).toBeInTheDocument()
    expect(within(panel).getByText('CFDI: validación SAT en Fase 2')).toBeInTheDocument()
    expect(within(panel).getByText(/subtotal \$620\.00 · IVA \$99\.20 · total \$719\.20/)).toBeInTheDocument()
    const user = userEvent.setup()
    const resolver = within(panel).getByTestId('resolver-gasto')
    expect(within(resolver).getByRole('button', { name: 'Rechazar' })).toBeDisabled()
    await user.click(within(resolver).getByRole('button', { name: 'Aprobar' }))
    await waitFor(() => expect(llamadas.filter((l) => l.clave === `POST /api/caja-chica/gastos/${GASTO}/aprobar`)).toHaveLength(1))
    expect(await screen.findByText('Gasto aprobado: se dio de alta la refacción y se descontó del fondo')).toBeInTheDocument()
    expect(await within(panel).findByText('Aprobado')).toBeInTheDocument()
    expect(within(panel).queryByTestId('resolver-gasto')).not.toBeInTheDocument()
  })

  it('el técnico captura el gasto de la refaccionaria desde la atención del folio', async () => {
    let capturado = false
    const llamadas = await entrar('tecnico', `/campo/folio/${FOLIO}`, {
      [`GET /api/folios/${FOLIO}`]: () => ({ json: detalle(folio()) }),
      'GET /api/folios/transiciones': () => ({ json: [] }),
      'GET /api/formularios/resolver': () => ({ estado: 404, json: { codigo: 'NO_ENCONTRADO', mensaje: 'Sin formulario', detalles: [] } }),
      [`GET /api/folios/${FOLIO}/chats`]: () => ({ json: [] }),
      'GET /api/inventario/articulos': () => ({ json: [] }),
      'GET /api/caja-chica/gastos': () => ({ json: capturado ? [gasto()] : [] }),
      'POST /api/caja-chica/gastos': () => { capturado = true; return { estado: 201, json: gasto() } },
    })
    const panel = await screen.findByTestId('caja-chica-campo', {}, { timeout: 5000 })
    expect(within(panel).getByText('Saldo $3,200.00')).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(within(panel).getByRole('button', { name: 'Capturar gasto de caja chica' }))
    expect(within(panel).getByRole('button', { name: 'Enviar para aprobación' })).toBeDisabled()
    await user.type(within(panel).getByLabelText('Proveedor'), 'Refaccionaria El Tornillo')
    await user.type(within(panel).getByLabelText('Descripción'), 'Capacitor de arranque 35 µF')
    await user.type(within(panel).getByLabelText('Subtotal'), '620')
    await user.type(within(panel).getByLabelText('IVA'), '99.20')
    expect(within(panel).getByText('$719.20')).toBeInTheDocument()
    await user.click(within(panel).getByRole('button', { name: 'Enviar para aprobación' }))
    await waitFor(() => expect(llamadas.find((l) => l.clave === 'POST /api/caja-chica/gastos')?.cuerpo).toEqual({
      folio_id: FOLIO, proveedor: 'Refaccionaria El Tornillo', descripcion: 'Capacitor de arranque 35 µF', cantidad: '1', subtotal: '620', iva: '99.2' }))
    expect(await within(panel).findByText('Gasto enviado al Admin prestador para su aprobación')).toBeInTheDocument()
    expect(await within(panel).findByText('Por aprobar')).toBeInTheDocument()
  })

  it('el técnico no puede aprobar su propio gasto', async () => {
    await entrar('tecnico', `/caja-chica?gasto=${GASTO}`, {
      'GET /api/caja-chica/gastos': () => ({ json: [gasto()] }),
    })
    const panel = await screen.findByTestId('detalle-gasto', {}, { timeout: 5000 })
    expect(within(panel).getByText('Por aprobar')).toBeInTheDocument()
    expect(within(panel).queryByTestId('resolver-gasto')).not.toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Mis gastos' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Autorizar fondo' })).not.toBeInTheDocument()
  })
})
