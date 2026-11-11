import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { PerfilConTema, Rol } from '../src/types/api'
import type { FolioDetalle, FolioResumen } from '../src/types/folios'
import type { FilaCalendario, Plan } from '../src/types/preventivos'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const T = '11111111-1111-1111-1111-111111111111'
const UN1 = 'u0000000-0000-0000-0000-000000000001'
const EQ1 = 'e0000000-0000-0000-0000-000000000001'
const PLAN = 'a0000000-0000-0000-0000-00000000000a'
const FOLIO = '0f000000-0000-0000-0000-000000000001'

function fila(extra: Partial<FilaCalendario> = {}): FilaCalendario {
  return {
    id: 'c0000000-0000-0000-0000-000000000001', created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z', version_hash: null, prestador_id: 'p1', tenant_id: T,
    un_id: UN1, un_codigo: 'SUC-001', un_nombre: 'Sucursal Centro', equipo_id: EQ1, equipo_codigo: 'EQ-0001', equipo_nombre: 'Refrigerador vertical', plan_id: PLAN,
    plan_nombre: 'Mantenimiento trimestral de refrigeradores', tecnico_id: null, tecnico_nombre: null, fecha_programada: '2026-11-18', fecha_programada_original: '2026-11-18',
    fecha_real: null, desvio_dias: null, texto_desvio: 'pendiente de ejecución', estado: 'programado', folio_id: null, numero_folio: null, estado_folio: null, formulario_id: null,
    origen: 'plan', descripcion: '', cargado_por: null, reprogramado_desde_id: null, ...extra,
  }
}

const plan: Plan = {
  id: PLAN, created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z', version_hash: null, prestador_id: 'p1', tenant_id: null, tipo_equipo_id: 'te1',
  tipo_equipo_nombre: 'Refrigerador vertical', nombre: 'Mantenimiento trimestral de refrigeradores', descripcion: 'Cada 3 meses', version: 1, estado: 'activo', tiempo_ventana_dias: 7,
  formulario_id: null, formulario_nombre: null, nivel_severidad_id: null, created_by: null,
  triggers: [{ id: 't1', tipo_trigger: 'tiempo_fijo', parametros_json: { cada: 3, unidad: 'meses' }, logica_combinacion: null }],
  tareas: [{ id: 'ta1', orden: 1, descripcion: 'Limpieza de condensador', tiempo_estimado_min: 30, habilidad_requerida_id: null }],
  materiales: [{ id: 'm1', articulo_id: null, descripcion: 'Limpiador de serpentín', cantidad_estandar: '1.00', unidad: 'litro' }],
  equipos: [{ id: 'ep1', equipo_id: EQ1, tenant_id: T, activo: true, fecha_proxima_ejecucion: '2026-11-18', fecha_ultima_ejecucion: null, fecha_alta: '2026-08-18' }],
}

function folioPreventivo(extra: Partial<FolioResumen> = {}): FolioResumen {
  return {
    id: FOLIO, created_at: '2026-10-27T10:00:00Z', updated_at: '2026-10-27T10:00:00Z', version_hash: null, numero_folio: 'CD-000120', tenant_id: T, prestador_id: 'p1', un_id: UN1,
    un_nombre: 'Sucursal Centro', un_codigo: 'SUC-001', equipo_id: EQ1, equipo_codigo: 'EQ-0001', equipo_nombre: 'Refrigerador vertical', tipo_falla_id: null, tipo_falla: null,
    tipo_folio: 'preventivo', estado: 'en_ejecucion', prioridad: 0, descripcion: 'Mantenimiento preventivo: Mantenimiento trimestral de refrigeradores', tecnico_id: '00000000-0000-0000-0000-000000000001',
    tecnico_nombre: 'Persona Prueba', severidad: null, severidad_origen: 'automatica_matriz', confirmacion_un: true, monto_estimado: null, criticidad: 'B', capturado_por: 'sys',
    capturado_por_nombre: 'Sistema', capturado_at: '2026-10-27T10:00:00Z', fecha_falla: '2026-11-18T00:00:00Z', fecha_inicio_atencion: '2026-11-18T09:00:00Z', fecha_cierre: null,
    razon_cancelacion: null, flujo: null, triggers_pendientes: 0, antiguedad_horas: 2, plan_id: PLAN, calendario_id: 'c1', plan_nombre: 'Mantenimiento trimestral de refrigeradores', ...extra,
  }
}

function detalle(f: FolioResumen): FolioDetalle {
  return {
    folio: f,
    captura: { capturado_por: 'sys', capturado_por_nombre: 'Sistema', capturado_at: f.capturado_at, un: { id: UN1, codigo: 'SUC-001', nombre: 'Sucursal Centro', direccion: 'Av. Juárez 100' }, equipo: { id: EQ1, codigo: 'EQ-0001', nombre: 'Refrigerador vertical' },
      tipo_falla: null, descripcion: f.descripcion, geolat_captura: null, geolng_captura: null, confirmacion_un: true, confirmacion_un_timestamp: null, confirmacion_un_geolat: null, confirmacion_un_geolng: null,
      folio_duplicado_justificacion: null, folio_duplicado_ref_id: null, folio_duplicado_ref_numero: null },
    formulario_captura: null, asignacion: { tecnico_id: f.tecnico_id, tecnico_nombre: f.tecnico_nombre, asignado_at: null, vehiculo: null, orden_en_ruta: null, ventana_inicio: null, ventana_fin: null },
    historial: [], reasignaciones: [], hallazgos: [], derivaciones: [], clasificacion: null, evidencias: [], formulario_atencion: null, refacciones: [], sla: null, encuesta: null, triggers_revision: [], aprobacion: null, decisiones: [], chat: [], financiero: {},
    acciones: ['cerrado', 'pendiente_refaccion'], puede_aprobar: false,
  }
}

async function entrar(rol: Rol, ruta: string, rutas: Parameters<typeof simularApi>[0] = {}, extra: Partial<PerfilConTema> = {}) {
  localStorage.setItem('acma.sesion', '1')  // P11a: solo la marca; el refresh va en cookie httpOnly
  const llamadas = simularApi({
    'POST /api/auth/refresh': () => ({ json: TOKENS }),
    'GET /api/auth/yo': () => ({ json: perfil(rol, { prestador_id: ['despachador', 'admin_prestador', 'mesa_control', 'tecnico'].includes(rol) ? 'p1' : null, ...extra }) }),
    'GET /api/tenants': () => ({ json: [{ id: T, razon_social: 'Cliente Demo', rfc: 'CDE200101XY2', pais: 'MX', moneda: 'MXN', zona_horaria: 'America/Mexico_City', estado: 'activo', created_at: '', updated_at: '', version_hash: null }] }),
    'GET /api/preventivos/calendario/publicaciones': () => ({ json: [] }),
    'GET /api/configuracion/mis-permisos': () => ({ json: [] }),
    ...rutas,
  })
  renderApp(ruta)
  return llamadas
}

describe('Preventivos', () => {
  it('el calendario carga el mes, muestra el desvío literal y publica el mes', async () => {
    const llamadas = await entrar('despachador', '/preventivos/calendario', {
      'GET /api/preventivos/calendario': (_c, url) => ({ json: url.searchParams.get('mes') ? [
        fila(),
        fila({ id: 'c0000000-0000-0000-0000-000000000002', estado: 'ejecutado', fecha_programada: '2026-11-05', fecha_real: '2026-11-07', desvio_dias: 2, texto_desvio: 'realizado con 2 días de retraso', folio_id: FOLIO, numero_folio: 'CD-000120', estado_folio: 'cerrado' }),
      ] : [] }),
      'POST /api/preventivos/calendario/publicar': (_c, url) => ({ json: { id: 'pub1', prestador_id: 'p1', tenant_id: T, mes: `${url.searchParams.get('mes')}-01`, publicado_por: 'd', publicado_at: '2026-10-28T10:00:00Z', total_preventivos: 2 } }),
    })
    await screen.findByRole('heading', { name: 'Calendario de preventivos' })
    const user = userEvent.setup()
    expect((screen.getByLabelText('Mes') as HTMLInputElement).value).toMatch(/^\d{4}-\d{2}$/)  // mes actual por defecto
    expect((await screen.findAllByText('Mantenimiento trimestral de refrigeradores')).length).toBe(2)
    expect(screen.getByTestId('desvio-c0000000-0000-0000-0000-000000000002')).toHaveTextContent('realizado con 2 días de retraso')
    expect(screen.getByText('Mes sin publicar')).toBeInTheDocument()
    expect(within(screen.getByTestId('resumen-mes')).getByText('Ejecutado:').parentElement).toHaveTextContent('Ejecutado: 1')
    await user.click(screen.getByRole('button', { name: 'Publicar el mes' }))
    expect(await screen.findByText(/Calendario de \d{4}-\d{2} publicado: 2 preventivo/)).toBeInTheDocument()
    const publicar = llamadas.find((l) => l.clave === 'POST /api/preventivos/calendario/publicar')
    expect(publicar).toBeTruthy()
  })

  it('el editor de planes arma la condición en lenguaje claro y envía tareas y materiales', async () => {
    const llamadas = await entrar('admin_prestador', '/preventivos/planes', {
      'GET /api/planes': () => ({ json: [plan] }),
      'GET /api/catalogos/tipos-equipo': () => ({ json: [{ id: 'te1', familia_id: 'f1', tenant_id: null, nombre: 'Refrigerador vertical', descripcion: '', activa: true, es_global: true }] }),
      'GET /api/catalogos/habilidades': () => ({ json: [{ id: 'h1', prestador_id: 'p1', clave: 'refrigeracion', nombre: 'Refrigeración comercial', descripcion: '', activa: true }] }),
      'GET /api/formularios': () => ({ json: [] }),
      'POST /api/planes': (cuerpo) => ({ estado: 201, json: { ...plan, id: 'nuevo', ...(cuerpo as object) } }),
    })
    await screen.findByRole('heading', { name: 'Planes de mantenimiento' })
    expect(await screen.findByText('Mantenimiento trimestral de refrigeradores')).toBeInTheDocument()
    expect(screen.getByText('cada 3 meses')).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Nuevo plan' }))
    const dialogo = await screen.findByRole('dialog')
    // F2-04: los seis tipos de §6.9.1 están disponibles; la condición nace como «Cada 30 días».
    const tipoT1 = within(dialogo).getByLabelText('Tipo de la condición t1') as HTMLSelectElement
    expect([...tipoT1.options].map((o) => o.value)).toEqual(['tiempo_fijo', 'calendario', 'medidor_umbral', 'medidor_intervalo', 'evento', 'combinado'])
    expect(within(dialogo).getByTestId('resumen-t1')).toHaveTextContent('Cada 30 días')
    await user.type(within(dialogo).getByLabelText('Nombre'), 'Plan de prueba')
    await user.selectOptions(within(dialogo).getByLabelText('Tipo de equipo'), 'te1')
    await user.selectOptions(tipoT1, 'calendario')
    expect(within(dialogo).getByTestId('resumen-t1')).toHaveTextContent('Cada 15/1')
    await user.click(within(dialogo).getByRole('button', { name: '+ Tarea' }))
    await user.type(within(dialogo).getByLabelText('Tarea 1'), 'Revisar luminarias')
    await user.selectOptions(within(dialogo).getByLabelText('Habilidad tarea 1'), 'h1')
    await user.click(within(dialogo).getByRole('button', { name: '+ Material' }))
    await user.type(within(dialogo).getByLabelText('Material 1'), 'Tubo LED')
    await user.click(within(dialogo).getByRole('button', { name: 'Crear plan' }))
    await waitFor(() => expect(llamadas.some((l) => l.clave === 'POST /api/planes')).toBe(true))
    const cuerpo = llamadas.find((l) => l.clave === 'POST /api/planes')!.cuerpo as { triggers: { tipo_trigger: string; parametros_json: Record<string, unknown> }[]; tareas: { descripcion: string; habilidad_requerida_id: string | null; orden: number }[]; materiales: { descripcion: string }[] }
    expect(cuerpo.triggers).toEqual([{ clave: 't1', tipo_trigger: 'calendario', logica_combinacion: null, parametros_json: { mes: 1, dia: 15 } }])
    expect(cuerpo.tareas).toEqual([{ orden: 1, descripcion: 'Revisar luminarias', tiempo_estimado_min: 15, habilidad_requerida_id: 'h1' }])
    expect(cuerpo.materiales[0]?.descripcion).toBe('Tubo LED')
  })

  it('el técnico ve la etiqueta Preventivo, la lista de tareas del plan y los materiales', async () => {
    await entrar('tecnico', `/campo/folio/${FOLIO}`, {
      [`GET /api/folios/${FOLIO}`]: () => ({ json: detalle(folioPreventivo()) }),
      'GET /api/folios/transiciones': () => ({ json: [] }),
      'GET /api/formularios/resolver': () => ({ estado: 404, json: { codigo: 'NO_ENCONTRADO', mensaje: 'Sin formulario', detalles: [] } }),
      [`GET /api/preventivos/${FOLIO}/plan`]: () => ({ json: { tareas: plan.tareas, materiales: plan.materiales } }),
      [`GET /api/folios/${FOLIO}/chats`]: () => ({ json: [] }),
    })
    expect(await screen.findByText('Preventivo')).toBeInTheDocument()
    expect(screen.getByText('Plan: Mantenimiento trimestral de refrigeradores')).toBeInTheDocument()
    const panel = await screen.findByTestId('plan-tecnico')
    expect(within(panel).getByText('0/1 listas')).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(within(panel).getByRole('checkbox'))
    expect(within(panel).getByText('1/1 listas')).toBeInTheDocument()
    expect(within(panel).getByText('1.00 litro · Limpiador de serpentín')).toBeInTheDocument()
    await user.click(within(panel).getByRole('button', { name: 'Usar como refacción' }))
    expect(screen.getByLabelText('Refacción')).toHaveValue('Limpiador de serpentín')
  })

  it('el despachador solicita reprogramación desde el folio preventivo y el Admin UN la autoriza', async () => {
    const f = folioPreventivo({ estado: 'autorizado', tecnico_id: null, tecnico_nombre: null })
    let autorizaciones: unknown[] = []
    const llamadas = await entrar('despachador', `/folios/${FOLIO}`, {
      [`GET /api/folios/${FOLIO}`]: () => ({ json: { ...detalle(f), acciones: ['asignado', 'cancelado'] } }),
      'GET /api/folios/transiciones': () => ({ json: [{ origen: 'autorizado', destino: 'asignado', roles: ['despachador'] }] }),
      'GET /api/preventivos/autorizaciones': () => ({ json: autorizaciones }),
      [`POST /api/preventivos/${FOLIO}/solicitar-reprogramacion`]: (cuerpo) => {
        const c = cuerpo as { razon: string; fecha_nueva: string }
        autorizaciones = [{ id: 'au1', folio_id: FOLIO, tenant_id: T, prestador_id: 'p1', calendario_id: 'c1', tipo: 'reprogramacion', solicitado_por: 'd', solicitado_por_nombre: 'Persona Prueba', autorizado_por: null, autorizado_por_nombre: null,
          fecha_solicitud: '2026-10-28T10:00:00Z', fecha_autorizacion: null, razon: c.razon, fecha_nueva: c.fecha_nueva, estado: 'pendiente', canal: 'app', notas_respuesta: '', numero_folio: 'CD-000120', estado_folio: 'autorizado', fecha_programada: '2026-11-18', puede_resolver: false }]
        return { estado: 201, json: autorizaciones[0] }
      },
      [`GET /api/folios/${FOLIO}/chats`]: () => ({ json: [] }),
    })
    await screen.findByRole('heading', { name: 'CD-000120' })
    expect(screen.getByText('Preventivo · Mantenimiento trimestral de refrigeradores')).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Solicitar reprogramación' }))
    await user.type(screen.getByLabelText('Razón de la reprogramación'), 'La sucursal tendrá inventario')
    await user.type(screen.getByLabelText('Fecha nueva'), '2026-11-25')
    await user.click(screen.getByRole('button', { name: 'Enviar solicitud' }))
    expect(await screen.findByText('Reprogramación → 2026-11-25 · pendiente')).toBeInTheDocument()
    expect(llamadas.find((l) => l.clave === `POST /api/preventivos/${FOLIO}/solicitar-reprogramacion`)!.cuerpo).toEqual({ razon: 'La sucursal tendrá inventario', fecha_nueva: '2026-11-25' })
    expect(screen.queryByRole('button', { name: 'Solicitar cancelación' })).not.toBeInTheDocument()
  })

  it('la bandeja de autorizaciones deja autorizar al Admin UN', async () => {
    const llamadas = await entrar('admin_un', '/preventivos/autorizaciones', {
      'GET /api/preventivos/autorizaciones': () => ({ json: [{ id: 'au1', folio_id: FOLIO, tenant_id: T, prestador_id: 'p1', calendario_id: 'c1', tipo: 'cancelacion', solicitado_por: 'd', solicitado_por_nombre: 'Diego Despachador', autorizado_por: null, autorizado_por_nombre: null,
        fecha_solicitud: '2026-10-28T10:00:00Z', fecha_autorizacion: null, razon: 'El equipo se reemplaza', fecha_nueva: null, estado: 'pendiente', canal: 'app', notas_respuesta: '', numero_folio: 'CD-000120', estado_folio: 'autorizado', fecha_programada: '2026-11-18', puede_resolver: true }] }),
      'POST /api/preventivos/autorizaciones/au1/autorizar': (cuerpo) => ({ json: { estado: 'autorizada', ...(cuerpo as object) } }),
    }, { tenant_id: T })
    await screen.findByRole('heading', { name: 'Autorizaciones de preventivos' })
    expect(await screen.findByText('El equipo se reemplaza')).toBeInTheDocument()
    window.prompt = () => 'Confirmado con la sucursal'
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Autorizar' }))
    expect(await screen.findByText('Cancelación del folio CD-000120 autorizada')).toBeInTheDocument()
    expect(llamadas.find((l) => l.clave === 'POST /api/preventivos/autorizaciones/au1/autorizar')!.cuerpo).toEqual({ notas: 'Confirmado con la sucursal', canal: 'app' })
  })
})
