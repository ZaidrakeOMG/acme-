import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { PerfilConTema, Rol } from '../src/types/api'
import type { MinutaDetalle, MinutaResumen } from '../src/types/minutas'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const T = '11111111-1111-1111-1111-111111111111'
const UN1 = 'u0000000-0000-0000-0000-000000000001'
const MIN = 'a0000000-0000-0000-0000-00000000000a'
const H1 = 'b0000000-0000-0000-0000-00000000000b'
const H2 = 'c0000000-0000-0000-0000-00000000000c'

function resumen(extra: Partial<MinutaResumen> = {}): MinutaResumen {
  return {
    id: MIN, tenant_id: T, tenant_nombre: 'Cliente Demo', prestador_id: 'p1', un_id: UN1, un_codigo: 'SUC-001', un_nombre: 'Sucursal Centro', fecha: '2026-10-28', tipo: 'un', estado: 'enviada',
    modo: 'automatica', timestamp_generacion: '2026-10-28T19:00:00Z', timestamp_envio: '2026-10-28T19:00:30Z', validada_por: null, validada_por_nombre: null, notas_despachador: '',
    enviada_sin_validacion: false, vence_respuesta_at: '2026-10-29T19:00:00Z', respondida_at: null, hash_pdf: 'abc123def456abc123def456abc123def456abc123def456abc123def456abcd', urgente: true,
    hallazgos: 2, hallazgos_pendientes: 2, colores: { cotizaciones: 'rojo', por_presupuesto: 'verde', seguimiento_interno: 'amarillo', reprogramacion: 'verde' }, ...extra,
  }
}

function detalle(hallazgos: MinutaDetalle['secciones']['hallazgos'], extra: Partial<MinutaDetalle> = {}): MinutaDetalle {
  return {
    ...resumen(), secciones: {
      contadores: { cotizaciones: { total: 3, color: 'rojo', umbral: 'más de 7 días sin respuesta', pendientes_enviar: 1, pendientes_autorizar: 2 }, por_presupuesto: { total: 1, color: 'verde', umbral: 'más de 30 días sin revisión' },
        seguimiento_interno: { total: 2, color: 'amarillo', umbral: 'más de 15 días sin actualización' }, reprogramacion: { total: 0, color: 'verde', umbral: 'fechas vencidas' } },
      preventivos: [{ calendario_id: 'c1', folio_id: 'f1', numero_folio: 'CD-000017', un: 'SUC-001 · Sucursal Centro', equipo: 'EQ-0001 · Refrigerador', tecnico: 'Tomás Técnico', hora: '2026-10-28T17:30:00Z', fecha_programada: '2026-10-26', fecha_real: '2026-10-28', desvio_dias: 2, texto_desvio: 'realizado con 2 días de retraso' }],
      hallazgos, cotizaciones: { pendientes_enviar: [], pendientes_autorizar: [{ cotizacion_id: 'q1', numero: 'COT-00001', un: 'SUC-001', equipo: 'EQ-0001', descripcion: 'Empaque', monto: '1850.00', estado: 'enviada', dias: 3 }] },
      trabajos_especiales: { nuevos: [{ trabajo_especial_id: 't1', numero: 'TE-000001', descripcion: 'Cortina de aire', un: 'SUC-001', estado: 'creado', urgencia: true, monto: null, fecha_programada: null }], en_proceso: [], terminados: [] }, peticiones: [{ peticion_id: 'pe1', texto: 'Visita antes de las 9:00', un: 'SUC-001', origen: 'chat', capturado_por: 'Olga', numero_folio: null, timestamp: '2026-10-28T10:00:00Z' }],
      pendientes_autorizacion: [],
    },
    hallazgos_detalle: [], respuestas: [], destinatarios: [{ usuario_id: 'u1', nombre: 'Úrsula Unidad', canal: 'email', estado_entrega: 'enviada', timestamp: '2026-10-28T19:00:30Z' }],
    puede_validar: false, puede_responder: true, opciones: [], pdf_disponible: true, ...extra,
  }
}

const hallazgoPendiente = (id: string, descripcion: string): MinutaDetalle['secciones']['hallazgos'][number] =>
  ({ hallazgo_id: id, descripcion, equipo: 'EQ-0001 · Refrigerador', un: 'SUC-001 · Sucursal Centro', urgencia: 'alta', foto_url: null, tipo: 'correctivo', numero_folio: 'CD-000001', estado_respuesta: 'pendiente', opcion_respuesta: null, pendiente_de_dias_anteriores: false, timestamp: '2026-10-28T16:00:00Z' })

async function entrar(rol: Rol, ruta: string, rutas: Parameters<typeof simularApi>[0] = {}, extra: Partial<PerfilConTema> = {}) {
  localStorage.setItem('acma.refresh', TOKENS.refresh_token)
  const llamadas = simularApi({
    'POST /api/auth/refresh': () => ({ json: TOKENS }),
    'GET /api/auth/yo': () => ({ json: perfil(rol, { tenant_id: ['operador', 'admin_un', 'admin_empresa', 'supervisor_operadores'].includes(rol) ? T : null, prestador_id: ['despachador', 'admin_prestador', 'mesa_control'].includes(rol) ? 'p1' : null, ...extra }) }),
    'GET /api/notificaciones/no-leidas': () => ({ json: { no_leidas: 0 } }),
    'GET /api/unidades-negocio': () => ({ json: [] }),
    'GET /api/tenants': () => ({ json: [{ id: T, razon_social: 'Cliente Demo', rfc: 'X', pais: 'MX', moneda: 'MXN', zona_horaria: 'America/Mexico_City', estado: 'activo', created_at: '', updated_at: '', version_hash: null }] }),
    ...rutas,
  })
  renderApp(ruta)
  return llamadas
}

describe('Minuta del día', () => {
  it('el Admin UN responde cada hallazgo con una de las seis opciones y la reprogramación pide fecha y tercero', async () => {
    let respondidos = 0
    const llamadas = await entrar('admin_un', `/minutas/${MIN}`, {
      [`GET /api/minutas/${MIN}`]: () => ({ json: detalle([
        { ...hallazgoPendiente(H1, 'Empaque de la puerta vencido'), ...(respondidos >= 1 ? { estado_respuesta: 'respondido', opcion_respuesta: 'cotizacion' } : {}) },
        { ...hallazgoPendiente(H2, 'Compresor vibra'), ...(respondidos >= 2 ? { estado_respuesta: 'respondido', opcion_respuesta: 'reprogramacion' } : {}) },
      ], respondidos >= 2 ? { estado: 'respondida', hallazgos_pendientes: 0 } : {}) }),
      [`POST /api/minutas/${MIN}/hallazgos/${H1}/responder`]: () => { respondidos = 1; return { estado: 201, json: { id: 'r1', hallazgo_id: H1, opcion_elegida: 'cotizacion' } } },
      [`POST /api/minutas/${MIN}/hallazgos/${H2}/responder`]: () => { respondidos = 2; return { estado: 201, json: { id: 'r2', hallazgo_id: H2, opcion_elegida: 'reprogramacion' } } },
    })
    await screen.findByRole('heading', { name: 'Minuta de SUC-001 · Sucursal Centro' })
    // Bloque 1 con colores y Bloque 2 con las secciones literales.
    expect(within(screen.getByTestId('contador-cotizaciones')).getByText('3')).toBeInTheDocument()
    expect(screen.getByTestId('contador-cotizaciones').className).toContain('red')
    expect(screen.getByText('realizado con 2 días de retraso')).toBeInTheDocument()
    expect(screen.getByText('TE-000001')).toBeInTheDocument()
    expect(screen.getByText(/Visita antes de las 9:00/)).toBeInTheDocument()
    expect(screen.getByText('Urgente')).toBeInTheDocument()
    const user = userEvent.setup()
    // Hallazgo 1 → cotización.
    const h1 = screen.getByTestId(`hallazgo-${H1}`)
    await user.click(within(h1).getByRole('button', { name: 'Responder' }))
    const grupo = within(h1).getByRole('radiogroup', { name: 'Opciones de respuesta' })
    expect(within(grupo).getAllByRole('radio')).toHaveLength(6)
    for (const texto of ['Enterado sin observaciones', 'Cotización', 'Autorizar reparar sin cotización', 'Por presupuesto', 'Seguimiento interno', 'Reprogramación']) expect(within(grupo).getByLabelText(texto)).toBeInTheDocument()
    expect(within(h1).getByRole('button', { name: 'Enviar respuesta' })).toBeDisabled()
    await user.click(within(grupo).getByLabelText('Cotización'))
    await user.type(within(h1).getByLabelText('Notas'), 'Cotizar empaque')
    await user.click(within(h1).getByRole('button', { name: 'Enviar respuesta' }))
    await waitFor(() => expect(llamadas.some((l) => l.clave === `POST /api/minutas/${MIN}/hallazgos/${H1}/responder`)).toBe(true))
    expect(llamadas.find((l) => l.clave === `POST /api/minutas/${MIN}/hallazgos/${H1}/responder`)!.cuerpo).toMatchObject({ opcion: 'cotizacion', notas: 'Cotizar empaque', canal: 'app', fecha_tentativa: null })
    expect(await screen.findByText('Hallazgo respondido: Cotización')).toBeInTheDocument()
    expect(within(screen.getByTestId(`hallazgo-${H1}`)).getByText('Cotización')).toBeInTheDocument()
    // Hallazgo 2 → reprogramación con fecha, tercero y trabajo coordinado variante A.
    const h2 = screen.getByTestId(`hallazgo-${H2}`)
    await user.click(within(h2).getByRole('button', { name: 'Responder' }))
    await user.click(within(h2).getByLabelText('Reprogramación'))
    await user.type(within(h2).getByLabelText('Fecha acordada con el tercero'), '2026-11-15')
    await user.type(within(h2).getByLabelText('Nombre del tercero'), 'Plomería del Centro')
    await user.click(within(h2).getByRole('checkbox'))
    await user.click(within(h2).getByRole('button', { name: 'Enviar respuesta' }))
    await waitFor(() => expect(llamadas.find((l) => l.clave === `POST /api/minutas/${MIN}/hallazgos/${H2}/responder`)).toBeTruthy())
    expect(llamadas.find((l) => l.clave === `POST /api/minutas/${MIN}/hallazgos/${H2}/responder`)!.cuerpo).toMatchObject({ opcion: 'reprogramacion', fecha_tentativa: '2026-11-15', proveedor: 'Plomería del Centro', trabajo_coordinado: true, variante: 'A' })
    await waitFor(() => expect(screen.getByText('Respondida')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Responder' })).not.toBeInTheDocument()
  })

  it('el despachador ve la bandeja de validación, anota y aprueba el envío', async () => {
    let validada = false
    const llamadas = await entrar('despachador', '/minutas', {
      'GET /api/minutas': () => ({ json: [resumen({ estado: validada ? 'enviada' : 'pendiente_validacion', modo: 'con_validacion', timestamp_envio: null })] }),
      [`GET /api/minutas/${MIN}`]: () => ({ json: detalle([hallazgoPendiente(H1, 'Hallazgo')], { estado: validada ? 'enviada' : 'pendiente_validacion', modo: 'con_validacion', puede_validar: !validada, puede_responder: false, notas_despachador: validada ? 'Revisada por el despachador' : '', validada_por_nombre: validada ? 'Persona Prueba' : null }) }),
      [`POST /api/minutas/${MIN}/validar`]: () => { validada = true; return { json: detalle([hallazgoPendiente(H1, 'Hallazgo')], { estado: 'enviada', puede_validar: false, notas_despachador: 'Revisada por el despachador' }) } },
    })
    await screen.findByRole('heading', { name: 'Minuta del día' })
    const bandeja = await screen.findByTestId('bandeja-validacion')
    expect(within(bandeja).getByText(/1 minuta\(s\) pendientes de tu validación/)).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(within(bandeja).getByRole('link'))
    await screen.findByText('Validación del despachador (§7.2)')
    await user.type(screen.getByLabelText('Notas del despachador'), 'Revisada por el despachador')
    await user.click(screen.getByRole('button', { name: 'Aprobar y enviar' }))
    expect(await screen.findByText('Minuta validada y enviada al cliente')).toBeInTheDocument()
    expect(llamadas.find((l) => l.clave === `POST /api/minutas/${MIN}/validar`)!.cuerpo).toEqual({ notas: 'Revisada por el despachador' })
    expect(screen.getByText(/Notas del despachador: Revisada/)).toBeInTheDocument()
    expect(screen.queryByText('Validación del despachador (§7.2)')).not.toBeInTheDocument()
  })
})
