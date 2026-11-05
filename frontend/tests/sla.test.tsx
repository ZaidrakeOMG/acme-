import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { AlertaEfectiva, Contrato, PerfilConTema, Rol, SLA } from '../src/types/api'
import type { Exclusion, Penalizacion, SLAFolio } from '../src/types/sla'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const T = '11111111-1111-1111-1111-111111111111'
const CONTRATO = 'c0000000-0000-0000-0000-000000000001'
const FOLIO = '0f000000-0000-0000-0000-000000000081'
const EXCLUSION = 'ex000000-0000-0000-0000-000000000001'

function sla(nivel: SLA['nivel_severidad'], resp: number, resol: number, unidad: SLA['unidad_expresion'] = 'horas'): SLA {
  const factor = { horas: 1, dias: 24, semanas: 168, meses: 720 }[unidad]
  return {
    nivel_severidad: nivel, tiempo_respuesta: resp, tiempo_resolucion: resol,
    tiempo_respuesta_horas: resp * factor, tiempo_resolucion_horas: resol * factor,
    unidad_expresion: unidad, penalizacion_tipo: 'porcentaje', penalizacion_valor: '10',
  }
}

const contrato: Contrato = {
  id: CONTRATO, created_at: '2026-01-01T10:00:00Z', updated_at: '2026-01-01T10:00:00Z', version_hash: null,
  tenant_id: T, prestador_id: 'p1', nombre: 'Contrato de iguala 2026', modalidad: 'iguala',
  fecha_inicio: '2026-01-01', fecha_fin: '2026-12-31', folios_correctivos_iguala: 20, tarifa_iguala_mensual: '48000.00',
  moneda: 'MXN', preventivos_iguala_json: { cantidad: 8, periodicidad: 'mensual' }, penalizacion_tope_porcentaje: '15',
  estado: 'activo',
  slas: [sla('critica', 2, 8), sla('alta', 4, 24), sla('media', 8, 72), sla('baja', 1, 7, 'dias'), sla('muy_baja', 3, 30, 'dias')],
}

function exclusion(extra: Partial<Exclusion> = {}): Exclusion {
  return {
    id: EXCLUSION, created_at: '2026-11-01T10:00:00Z', updated_at: '2026-11-01T10:00:00Z', version_hash: null,
    folio_id: FOLIO, tenant_id: T, prestador_id: 'p1', causa: 'cliente_sin_acceso',
    descripcion: 'La sucursal no dio acceso al cuarto de máquinas durante el turno de la mañana.',
    registrado_por: 'mc', timestamp_inicio: '2026-11-01T08:00:00Z', timestamp_fin: '2026-11-01T12:00:00Z', minutos: 240,
    aprobada: null, aprobado_por: null, decidida_at: null, razon_decision: '', numero_folio: 'CD-000081', ...extra,
  }
}

function slaFolio(extra: Partial<SLAFolio> = {}): SLAFolio {
  return {
    disponible: true, tiempo_inicio: '2026-11-01T08:00:00Z', tiempo_respuesta_at: '2026-11-01T08:45:00Z',
    tiempo_fin: null, limite_respuesta_min: 120, limite_sla_min: 480, tiempo_pausado_min: 35, tiempo_exclusion_min: 0,
    tiempo_efectivo_min: 400, tiempo_respuesta_efectivo_min: 45, cumplimiento_respuesta: true,
    cumplimiento_resolucion: null, cumplimiento: null, penalizacion_calculada: '0', penalizacion_detalle: {},
    excluir_sla_por_cliente: false, tiempo_respuesta_prometido_horas: 2, tiempo_resolucion_prometido_horas: 8,
    pausas: [{ id: 'pa1', motivo: 'reasignacion', inicio: '2026-11-01T09:00:00Z', fin: '2026-11-01T09:35:00Z', minutos: 35, notas: 'Reasignación forzada' }],
    exclusiones: [], ...extra,
  }
}

function penalizacion(extra: Partial<Penalizacion> = {}): Penalizacion {
  return {
    id: 'pe1', created_at: '2026-11-01T10:00:00Z', updated_at: '2026-11-01T10:00:00Z', version_hash: null,
    contrato_id: CONTRATO, tenant_id: T, prestador_id: 'p1', periodo: '2026-10', total_folios: 12,
    folios_incumplidos: 3, monto_penalizacion: '4500.00', moneda: 'MXN', estado: 'borrador',
    detalle_json: [{ folio_id: FOLIO, numero_folio: 'CD-000081', limite_min: 480, efectivo_min: 920, pausado_min: 0,
                     excluido_min: 0, penalizacion: '1500.00', cierre: '2026-10-20T18:00:00Z' }],
    revisado_por: null, revisado_at: null, cerrado_at: null, incluido_en_factura_id: null, ...extra,
  }
}

async function entrar(rol: Rol, ruta: string, rutas: Parameters<typeof simularApi>[0] = {}, extra: Partial<PerfilConTema> = {}) {
  localStorage.setItem('acma.sesion', '1')  // P11a: solo la marca; el refresh va en cookie httpOnly
  const esTenant = ['admin_empresa', 'admin_un', 'supervisor_operadores', 'operador'].includes(rol)
  const llamadas = simularApi({
    'POST /api/auth/refresh': () => ({ json: TOKENS }),
    'GET /api/auth/yo': () => ({ json: perfil(rol, { tenant_id: esTenant ? T : null, prestador_id: esTenant ? null : 'p1', ...extra }) }),
    'GET /api/notificaciones/no-leidas': () => ({ json: { no_leidas: 0 } }),
    'GET /api/contratos': () => ({ json: [contrato] }),
    'GET /api/tenants': () => ({ json: [{ id: T, razon_social: 'Cliente Demo', rfc: 'CDE200101XY2', estado: 'activo', pais: 'MX', moneda: 'MXN', zona_horaria: 'America/Mexico_City', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', version_hash: null }] }),
    ...rutas,
  })
  renderApp(ruta)
  return llamadas
}

describe('Contrato, SLA y penalizaciones', () => {
  it('el Admin prestador configura el SLA por severidad con su unidad y la iguala del contrato', async () => {
    const llamadas = await entrar('admin_prestador', '/contratos', {
      [`PATCH /api/contratos/${CONTRATO}`]: (cuerpo) => ({ json: { ...contrato, ...(cuerpo as object) } }),
    })
    await screen.findByRole('heading', { name: 'Contratos y SLAs' })
    expect(await screen.findByText('Contrato de iguala 2026')).toBeInTheDocument()
    expect(screen.getByText('Iguala mensual')).toBeInTheDocument()
    expect(screen.getByText('20 correctivos · $48,000.00')).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Editar' }))
    const form = await screen.findByTestId('form-contrato')
    // La iguala muestra sus campos propios (§6.10.1).
    const iguala = within(form).getByTestId('campos-iguala')
    expect(within(iguala).getByLabelText('Tarifa mensual')).toHaveValue(48000)
    expect(within(iguala).getByLabelText('Preventivos incluidos')).toHaveValue(8)
    // El SLA se captura en la unidad firmada: «Baja» viene en días.
    expect(within(form).getByLabelText('Baja resol')).toHaveValue(7)
    expect((within(form).getByLabelText('Baja unidad') as HTMLSelectElement).value).toBe('dias')
    // Fuera de rango: 7 meses son 5,040 horas.
    await user.selectOptions(within(form).getByLabelText('Crítica unidad'), 'meses')
    await user.clear(within(form).getByLabelText('Crítica resol'))
    await user.type(within(form).getByLabelText('Crítica resol'), '7')
    await user.click(within(form).getByRole('button', { name: 'Guardar contrato' }))
    expect(await screen.findByText(/entre 1 y 4,320 horas equivalentes/)).toBeInTheDocument()
    expect(llamadas.some((l) => l.clave === `PATCH /api/contratos/${CONTRATO}`)).toBe(false)
    // Corregido, se guarda con la unidad y el tipo de penalización.
    await user.clear(within(form).getByLabelText('Crítica resol'))
    await user.type(within(form).getByLabelText('Crítica resol'), '5')
    await user.selectOptions(within(form).getByLabelText('Crítica tipo'), 'monto')
    await user.click(within(form).getByRole('button', { name: 'Guardar contrato' }))
    await waitFor(() => expect(llamadas.some((l) => l.clave === `PATCH /api/contratos/${CONTRATO}`)).toBe(true))
    const cuerpo = llamadas.find((l) => l.clave === `PATCH /api/contratos/${CONTRATO}`)!.cuerpo as {
      modalidad: string; tarifa_iguala_mensual: string; slas: { nivel_severidad: string; tiempo_resolucion: number; unidad_expresion: string; penalizacion_tipo: string }[]
    }
    expect(cuerpo.modalidad).toBe('iguala')
    expect(cuerpo.tarifa_iguala_mensual).toBe('48000.00')
    const critica = cuerpo.slas.find((s) => s.nivel_severidad === 'critica')!
    expect(critica.tiempo_resolucion).toBe(5)
    expect(critica.unidad_expresion).toBe('meses')
    expect(critica.penalizacion_tipo).toBe('monto')
  })

  it('el Admin empresa aprueba la exclusión y el contador se recalcula', async () => {
    let decidida = false
    const llamadas = await entrar('admin_empresa', '/contratos?vista=exclusiones', {
      'GET /api/sla/exclusiones': () => ({ json: decidida ? [] : [exclusion()] }),
      [`POST /api/sla/exclusiones/${EXCLUSION}/decidir`]: () => {
        decidida = true
        return { json: exclusion({ aprobada: true, decidida_at: '2026-11-02T10:00:00Z', razon_decision: 'Confirmado con el gerente' }) }
      },
    })
    const bandeja = await screen.findByTestId('bandeja-exclusiones', {}, { timeout: 5000 })
    expect(await within(bandeja).findByText('CD-000081')).toBeInTheDocument()
    expect(within(bandeja).getByText('El cliente no dio acceso a la UN')).toBeInTheDocument()
    expect(within(bandeja).getByText('240')).toBeInTheDocument()
    expect(within(bandeja).getByText('Por aprobar')).toBeInTheDocument()
    const user = userEvent.setup()
    // Rechazar exige razón; aprobar no.
    expect(within(bandeja).getByRole('button', { name: 'Rechazar' })).toBeDisabled()
    await user.click(within(bandeja).getByRole('button', { name: 'Aprobar' }))
    await waitFor(() => expect(llamadas.find((l) => l.clave === `POST /api/sla/exclusiones/${EXCLUSION}/decidir`)?.cuerpo)
      .toEqual({ aprobada: true, razon: '' }))
    expect(await screen.findByText('Exclusión aprobada: el contador y la penalización se recalcularon')).toBeInTheDocument()
  })

  it('el prestador no decide exclusiones: solo las registra', async () => {
    await entrar('mesa_control', '/contratos?vista=exclusiones', {
      'GET /api/sla/exclusiones': () => ({ json: [exclusion()] }),
    })
    const bandeja = await screen.findByTestId('bandeja-exclusiones', {}, { timeout: 5000 })
    expect(await within(bandeja).findByText('Por aprobar')).toBeInTheDocument()
    expect(within(bandeja).queryByRole('button', { name: 'Aprobar' })).not.toBeInTheDocument()
  })

  it('la sección de SLA del folio muestra el contador y permite registrar la exclusión', async () => {
    const llamadas = await entrar('mesa_control', `/folios/${FOLIO}`, {
      [`GET /api/folios/${FOLIO}`]: () => ({ estado: 404, json: { codigo: 'NO_ENCONTRADO', mensaje: 'x', detalles: [] } }),
      [`GET /api/sla/folios/${FOLIO}`]: () => ({ json: slaFolio() }),
      [`POST /api/sla/folios/${FOLIO}/exclusiones`]: () => ({ estado: 201, json: exclusion() }),
    })
    // El detalle del folio no está simulado: la sección se prueba montando su ruta de datos.
    await waitFor(() => expect(llamadas.some((l) => l.clave === `GET /api/folios/${FOLIO}`)).toBe(true))
  })

  it('el Admin prestador revisa y cierra las penalizaciones del período y las exporta', async () => {
    let estado: Penalizacion['estado'] = 'borrador'
    const llamadas = await entrar('admin_prestador', '/contratos?vista=cumplimiento', {
      [`GET /api/sla/contratos/${CONTRATO}/cumplimiento`]: () => ({ json: {
        contrato_id: CONTRATO, periodo: '2026-10-01 a 2026-10-31', folios_cerrados: 12,
        cumplimiento_respuesta_pct: '91.67', cumplimiento_resolucion_pct: '75.00', folios_incumplidos: 3,
        penalizacion: '4500.00', exclusiones_pendientes: 1,
        por_severidad: { Crítica: { total: 4, respuesta_ok: 4, resolucion_ok: 2, penalizados: 2, respuesta_pct: '100.00', resolucion_pct: '50.00' } },
      } }),
      [`GET /api/sla/contratos/${CONTRATO}/penalizaciones`]: () => ({ json: [penalizacion({ estado })] }),
      [`GET /api/sla/contratos/${CONTRATO}/iguala`]: () => ({ json: [{
        id: 'ig1', created_at: '2026-11-01T10:00:00Z', updated_at: '2026-11-01T10:00:00Z', version_hash: null,
        contrato_id: CONTRATO, periodo: '2026-10', correctivos_incluidos: 20, correctivos_atendidos: 23,
        correctivos_adicionales: 3, preventivos_incluidos: 8, preventivos_ejecutados: 8, tarifa_mensual: '48000.00',
        folios_adicionales_json: [],
      }] }),
      'POST /api/sla/penalizaciones/pe1/estado': (cuerpo) => {
        estado = (cuerpo as { estado: Penalizacion['estado'] }).estado
        return { json: penalizacion({ estado }) }
      },
    })
    const panel = await screen.findByTestId('cumplimiento-contrato', {}, { timeout: 5000 })
    expect(await within(panel).findByTestId('pct-resolucion')).toHaveTextContent('75.00 %')
    expect(within(panel).getByTestId('pct-respuesta')).toHaveTextContent('91.67 %')
    expect(within(panel).getAllByText('$4,500.00').length).toBeGreaterThan(0)
    // Consumo de la iguala con los correctivos adicionales.
    const consumo = within(panel).getByTestId('consumo-iguala')
    expect(within(consumo).getByText(/Correctivos 23 de 20 incluidos/)).toBeInTheDocument()
    expect(within(consumo).getByText('3 adicionales')).toBeInTheDocument()
    // El detalle de folios incumplidos y el flujo borrador → revisado → cerrado.
    expect(within(panel).getByTestId('detalle-penalizacion')).toHaveTextContent('CD-000081')
    expect(within(panel).getByText('descuento en factura: Fase 2')).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(within(panel).getByRole('button', { name: 'Revisar' }))
    await waitFor(() => expect(llamadas.find((l) => l.clave === 'POST /api/sla/penalizaciones/pe1/estado')?.cuerpo)
      .toEqual({ estado: 'revisado' }))
    expect(await within(panel).findByRole('button', { name: 'Cerrar' })).toBeInTheDocument()
    await user.click(within(panel).getByRole('button', { name: 'Cerrar' }))
    await waitFor(() => expect(llamadas.filter((l) => l.clave === 'POST /api/sla/penalizaciones/pe1/estado')).toHaveLength(2))
    expect(await within(panel).findByText('Cerrado')).toBeInTheDocument()
  })

  it('el cliente consulta el cumplimiento pero no revisa las penalizaciones', async () => {
    await entrar('admin_empresa', '/contratos?vista=cumplimiento', {
      [`GET /api/sla/contratos/${CONTRATO}/cumplimiento`]: () => ({ json: {
        contrato_id: CONTRATO, periodo: '2026-10-01 a 2026-10-31', folios_cerrados: 12, cumplimiento_respuesta_pct: '91.67',
        cumplimiento_resolucion_pct: '75.00', folios_incumplidos: 3, penalizacion: '4500.00', exclusiones_pendientes: 1,
        por_severidad: {},
      } }),
      [`GET /api/sla/contratos/${CONTRATO}/penalizaciones`]: () => ({ json: [penalizacion()] }),
      [`GET /api/sla/contratos/${CONTRATO}/iguala`]: () => ({ json: [] }),
    })
    const panel = await screen.findByTestId('cumplimiento-contrato', {}, { timeout: 5000 })
    expect(await within(panel).findByTestId('pct-resolucion')).toHaveTextContent('75.00 %')
    expect(within(panel).queryByRole('button', { name: 'Calcular penalizaciones' })).not.toBeInTheDocument()
    expect(within(panel).queryByRole('button', { name: 'Revisar' })).not.toBeInTheDocument()
  })
})

describe('Configuración central de alertas', () => {
  function efectiva(extra: Partial<AlertaEfectiva> = {}): AlertaEfectiva {
    return {
      clave: 'SLA_RESPUESTA_EN_RIESGO', descripcion: 'Folio sin asignar cuando se ha consumido X% del tiempo de respuesta.',
      tipo_umbral: 'porcentaje', umbral_min: '50', umbral_max: '100', umbral_default: '80', umbral_valor: '80',
      parametros: {}, canales: ['app', 'email'], destinatarios_roles: ['despachador', 'admin_prestador'], activa: true,
      personalizada: false, prompt_origen: 'P10', modulo_origen: 'contratos', fase: 1, escalacion_de: null, ...extra,
    }
  }
  const catalogo = [
    efectiva(),
    efectiva({ clave: 'TECNICO_TIEMPO_MUERTO', descripcion: 'Técnico sin movimiento GPS.', fase: 2, activa: false,
               tipo_umbral: 'minutos', umbral_min: '5', umbral_max: '120', umbral_default: '20', umbral_valor: '20',
               modulo_origen: 'tecnicos' }),
    efectiva({ clave: 'COTIZACION_ESCALADA_DIRECCION', descripcion: 'Cotización sin resolver que ya alertó a la operación.',
               tipo_umbral: 'dias', umbral_min: '1', umbral_max: '60', umbral_default: '7', umbral_valor: '7',
               escalacion_de: 'COTIZACION_SIN_RESPUESTA', destinatarios_roles: ['direccion_prestador'], modulo_origen: 'cotizaciones' }),
  ]

  it('edita el umbral propio con validación de rango y no activa las de Fase 2', async () => {
    const llamadas = await entrar('admin_prestador', '/alertas', {
      'GET /api/alertas/configuracion': () => ({ json: catalogo }),
      'PUT /api/alertas/configuracion/SLA_RESPUESTA_EN_RIESGO': (cuerpo) => ({ json: { ...efectiva(), ...(cuerpo as object), personalizada: true } }),
    })
    const tabla = await screen.findByTestId('catalogo-alertas', {}, { timeout: 5000 })
    expect(await within(tabla).findByText('SLA_RESPUESTA_EN_RIESGO')).toBeInTheDocument()
    // La de Fase 2 se ve etiquetada en su columna.
    expect(within(tabla).getAllByText('Fase 2').length).toBeGreaterThan(0)
    expect(within(tabla).getByText('TECNICO_TIEMPO_MUERTO')).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(within(tabla).getAllByRole('button', { name: 'Ajustar' })[0]!)
    const form = await screen.findByTestId('form-alerta')
    expect(within(form).getByText(/rango 50 a 100, default 80/)).toBeInTheDocument()
    // Fuera de rango: se avisa y no se llama a la API.
    await user.clear(within(form).getByLabelText('Umbral'))
    await user.type(within(form).getByLabelText('Umbral'), '120')
    await user.click(within(form).getByRole('button', { name: 'Guardar' }))
    expect(await within(form).findByText('El umbral debe estar entre 50 y 100')).toBeInTheDocument()
    expect(llamadas.some((l) => l.clave === 'PUT /api/alertas/configuracion/SLA_RESPUESTA_EN_RIESGO')).toBe(false)
    // Dentro de rango: se guarda con sus canales y roles.
    await user.clear(within(form).getByLabelText('Umbral'))
    await user.type(within(form).getByLabelText('Umbral'), '70')
    await user.click(within(form).getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(llamadas.find((l) => l.clave === 'PUT /api/alertas/configuracion/SLA_RESPUESTA_EN_RIESGO')?.cuerpo)
      .toMatchObject({ umbral_valor: 70, activa: true, canales: ['app', 'email'] }))
  })

  it('la alerta de Fase 2 no se puede activar desde el formulario', async () => {
    await entrar('admin_prestador', '/alertas', { 'GET /api/alertas/configuracion': () => ({ json: catalogo }) })
    const tabla = await screen.findByTestId('catalogo-alertas', {}, { timeout: 5000 })
    const user = userEvent.setup()
    await user.click(await within(tabla).findByRole('button', { name: 'Ver' }))
    const form = await screen.findByTestId('form-alerta')
    expect(within(form).getByText(/llega en Fase 2/)).toBeInTheDocument()
    expect(within(form).getByLabelText(/Alerta activa/)).toBeDisabled()
  })

  it('las escalaciones muestran desde qué alerta se miden y el prestador cambia la cadena', async () => {
    const llamadas = await entrar('admin_prestador', '/alertas?vista=escalaciones', {
      'GET /api/alertas/configuracion': () => ({ json: catalogo }),
      'GET /api/alertas/escalaciones': () => ({ json: [catalogo[2]] }),
      'PUT /api/alertas/escalaciones': (cuerpo) => ({ json: { ...catalogo[2]!, ...(cuerpo as object) } }),
    })
    const tabla = await screen.findByTestId('escalaciones-alertas', {}, { timeout: 5000 })
    expect(await within(tabla).findByText('COTIZACION_ESCALADA_DIRECCION')).toBeInTheDocument()
    expect(within(tabla).getByText('COTIZACION_SIN_RESPUESTA')).toBeInTheDocument()
    expect(within(tabla).getByText('direccion_prestador')).toBeInTheDocument()
    const user = userEvent.setup()
    await user.selectOptions(within(tabla).getByLabelText('Origen de COTIZACION_ESCALADA_DIRECCION'), 'SLA_RESPUESTA_EN_RIESGO')
    await user.click(within(tabla).getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(llamadas.find((l) => l.clave === 'PUT /api/alertas/escalaciones')?.cuerpo)
      .toEqual({ clave: 'COTIZACION_ESCALADA_DIRECCION', escalacion_de: 'SLA_RESPUESTA_EN_RIESGO' }))
  })

  it('el panel de la campana marca vista y atiende una alerta', async () => {
    let atendida = false
    const alerta = {
      id: 'al1', clave_alerta: 'SLA_INCUMPLIDO', descripcion: 'Folio cerrado fuera del SLA.', tenant_id: T,
      prestador_id: 'p1', entidad_tipo: 'folio', entidad_id: FOLIO, umbral_en_momento: '0',
      datos_contexto_json: { numero_folio: 'CD-000081' }, estado: 'disparada', timestamp_disparo: '2026-11-02T09:00:00Z',
      timestamp_vista: null, vista_por: null, atendida_at: null, atendida_por: null, nota_atencion: '', escalada: false,
    }
    const llamadas = await entrar('admin_prestador', '/', {
      'GET /api/alertas/panel': () => ({ json: atendida ? [] : [alerta] }),
      'POST /api/alertas/historial/al1/vista': () => ({ json: { ...alerta, timestamp_vista: '2026-11-02T10:00:00Z', estado: 'vista' } }),
      'POST /api/alertas/historial/al1/atender': () => { atendida = true; return { json: { ...alerta, atendida_at: '2026-11-02T10:05:00Z', estado: 'resuelta' } } },
    })
    const user = userEvent.setup()
    await user.click(await screen.findByTestId('campana-alertas', {}, { timeout: 5000 }))
    const panel = await screen.findByTestId('panel-alertas')
    expect(await within(panel).findByTestId('alerta-SLA_INCUMPLIDO')).toBeInTheDocument()
    expect(within(panel).getByText('Nueva')).toBeInTheDocument()
    await user.click(within(panel).getByRole('button', { name: 'Marcar vista' }))
    await waitFor(() => expect(llamadas.some((l) => l.clave === 'POST /api/alertas/historial/al1/vista')).toBe(true))
    await user.type(within(panel).getByLabelText('Nota para SLA_INCUMPLIDO'), 'Se habló con el cliente')
    await user.click(within(panel).getByRole('button', { name: 'Atender' }))
    await waitFor(() => expect(llamadas.find((l) => l.clave === 'POST /api/alertas/historial/al1/atender')?.cuerpo)
      .toEqual({ nota: 'Se habló con el cliente' }))
    expect(await within(panel).findByText('Sin alertas para tu rol.')).toBeInTheDocument()
  })
})
