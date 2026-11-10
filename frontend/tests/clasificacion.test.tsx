import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { PerfilConTema, Rol } from '../src/types/api'
import type { FolioResumen } from '../src/types/folios'
import type { Notificacion, PendienteClasificacion } from '../src/types/minutas'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const T = '11111111-1111-1111-1111-111111111111'
const FOLIO = '0f000000-0000-0000-0000-000000000009'

const folio: FolioResumen = {
  id: FOLIO, created_at: '2026-10-28T10:00:00Z', updated_at: '2026-10-28T10:00:00Z', version_hash: null, numero_folio: 'CD-000031', tenant_id: T, prestador_id: 'p1', un_id: 'u1', un_nombre: 'Sucursal Centro',
  un_codigo: 'SUC-001', equipo_id: 'e3', equipo_codigo: 'EQ-0003', equipo_nombre: 'Minisplit', tipo_falla_id: 'tf', tipo_falla: 'Gotea agua', tipo_folio: 'correctivo', estado: 'en_revision', prioridad: 0,
  descripcion: 'El minisplit gotea sobre el mostrador', tecnico_id: null, tecnico_nombre: null, severidad: { id: 's2', clave: 'baja', nombre: 'Baja', orden: 2, color_hex: '#4CAF50' }, severidad_origen: 'automatica_matriz',
  confirmacion_un: true, monto_estimado: null, criticidad: 'C', capturado_por: 'op', capturado_por_nombre: 'Olga', capturado_at: '2026-10-28T10:00:00Z', fecha_falla: '2026-10-28T10:00:00Z', fecha_inicio_atencion: null,
  fecha_cierre: null, razon_cancelacion: null, flujo: null, triggers_pendientes: 1, antiguedad_horas: 3,
}
const pendiente: PendienteClasificacion = { folio, pendiente_desde: '2026-10-28T10:00:00Z', plazo_at: '2026-10-29T10:00:00Z', horas_restantes: 20.5, vencido: false, opciones: [] }

async function entrar(rol: Rol, ruta: string, rutas: Parameters<typeof simularApi>[0] = {}, extra: Partial<PerfilConTema> = {}) {
  localStorage.setItem('acma.sesion', '1')  // P11a: solo la marca; el refresh va en cookie httpOnly
  const llamadas = simularApi({
    'POST /api/auth/refresh': () => ({ json: TOKENS }),
    'GET /api/auth/yo': () => ({ json: perfil(rol, { tenant_id: T, ...extra }) }),
    'GET /api/notificaciones/no-leidas': () => ({ json: { no_leidas: 1 } }),
    ...rutas,
  })
  renderApp(ruta)
  return llamadas
}

describe('Clasificación de folios no críticos', () => {
  it('muestra los pendientes con plazo y clasifica con reprogramación pidiendo fecha tentativa', async () => {
    let clasificado = false
    const llamadas = await entrar('admin_un', '/clasificacion', {
      'GET /api/clasificacion/pendientes': () => ({ json: clasificado ? [] : [pendiente] }),
      [`POST /api/clasificacion/${FOLIO}`]: () => { clasificado = true; return { estado: 201, json: { folio_id: FOLIO, opcion_clasificacion: 'reprogramacion' } } },
    })
    const tarjeta = await screen.findByTestId('pendiente-CD-000031')
    expect(within(tarjeta).getByText('Quedan 21 h')).toBeInTheDocument()
    expect(within(tarjeta).getByText('Baja')).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(within(tarjeta).getByRole('button', { name: 'Clasificar' }))
    const opciones = within(tarjeta).getByRole('radiogroup', { name: 'Opciones de clasificación' })
    expect(within(opciones).getAllByRole('radio')).toHaveLength(5)
    expect(within(tarjeta).getByRole('button', { name: 'Confirmar' })).toBeDisabled()
    await user.click(within(opciones).getByLabelText('Pendiente por reprogramación'))
    expect(within(tarjeta).getByRole('button', { name: 'Confirmar' })).toBeDisabled()  // falta la fecha tentativa
    await user.type(within(tarjeta).getByLabelText('Fecha tentativa'), '2026-11-20')
    await user.type(within(tarjeta).getByLabelText('Notas'), 'Lo ve el plomero')
    await user.click(within(tarjeta).getByRole('button', { name: 'Confirmar' }))
    await waitFor(() => expect(llamadas.some((l) => l.clave === `POST /api/clasificacion/${FOLIO}`)).toBe(true))
    expect(llamadas.find((l) => l.clave === `POST /api/clasificacion/${FOLIO}`)!.cuerpo).toEqual({ opcion: 'reprogramacion', fecha_tentativa: '2026-11-20', notas: 'Lo ve el plomero' })
    expect(await screen.findByText(/CD-000031 clasificado: Pendiente por reprogramación/)).toBeInTheDocument()
    expect(await screen.findByText('No tienes folios pendientes de clasificar.')).toBeInTheDocument()
  })

  it('el Admin empresa ve la calificación del período con sus eventos', async () => {
    await entrar('admin_empresa', '/clasificacion?vista=calificacion', {
      'GET /api/clasificacion/pendientes': () => ({ json: [] }),
      'GET /api/clasificacion/calificaciones': () => ({ json: [{ id: 'k1', usuario_id: 'u', usuario_nombre: 'Úrsula Unidad', un_id: 'u1', un_codigo: 'SUC-001', periodo: '2026-10', puntos_total: 100, folios_clasificados_tiempo: 3, folios_tardios: 1, folios_sin_clasificar: 0, minutas_respondidas: 2, minutas_tardias: 1, calificacion_final: '82.00', eventos_json: [{ tipo: 'clasificacion_tardia', descuento: 8, folio_id: 'f', horas_retraso: '4.00' }, { tipo: 'minuta_sin_respuesta', descuento: 10 }], calculada_at: '2026-10-28T06:30:00Z', cerrada: false }] }),
    })
    expect(await screen.findByText('82.00 / 100')).toBeInTheDocument()
    expect(screen.getByText('3 a tiempo · 1 tardíos · 0 sin clasificar')).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Eventos' }))
    expect(await screen.findByText(/clasificacion tardia · −8 puntos · 4.00 h de retraso/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Recalcular el período actual' })).toBeInTheDocument()
  })

  it('la campana muestra las no leídas y la bandeja permite marcar como leída', async () => {
    const notificacion: Notificacion = { id: 'n1', evento: 'clasificacion.pendiente', canal: 'app', asunto: 'Folio CD-000031 no crítico: clasifícalo en 24 h', cuerpo: 'El minisplit gotea', datos: { folio_id: FOLIO }, estado: 'enviada', timestamp: '2026-10-28T10:00:00Z', leida_at: null, url: '/clasificacion' }
    let leida = false
    const llamadas = await entrar('admin_un', '/notificaciones', {
      'GET /api/notificaciones': () => ({ json: [{ ...notificacion, leida_at: leida ? '2026-10-28T11:00:00Z' : null }] }),
      // F2-02: la pantalla dibuja una casilla por cada canal que devuelve el servidor, ya no los tres fijos.
      'GET /api/notificaciones/eventos': () => ({ json: { eventos: [{ clave: 'minuta.enviada', nombre: 'Minuta del día enviada', canales_default: ['app', 'push', 'email'] }], canales: [{ clave: 'app', nombre: 'Bandeja en la app', disponible: true }, { clave: 'push', nombre: 'Push', disponible: true }, { clave: 'email', nombre: 'Correo', disponible: true }] } }),
      'GET /api/notificaciones/preferencias': () => ({ json: [{ evento: 'minuta.enviada', canales: ['app'] }] }),
      'GET /api/usuarios/me/telefono': () => ({ json: { telefono_mascara: null, tiene_telefono: false, verificado: false, verificado_at: null, whatsapp: { consentimiento_at: null, baja_at: null, activo: false }, sms: { consentimiento_at: null, baja_at: null, activo: false }, aviso_privacidad: 'Aviso de prueba' } }),
      'POST /api/notificaciones/leidas': () => { leida = true; return { json: { marcadas: 1 } } },
      'PUT /api/notificaciones/preferencias': (cuerpo) => ({ json: cuerpo }),
    })
    expect(await screen.findByLabelText('Notificaciones: 1 sin leer')).toBeInTheDocument()
    const bandeja = await screen.findByTestId('bandeja')
    expect(within(bandeja).getByText('Folio CD-000031 no crítico: clasifícalo en 24 h')).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(within(bandeja).getByRole('button', { name: 'Leída' }))
    await waitFor(() => expect(llamadas.find((l) => l.clave === 'POST /api/notificaciones/leidas')!.cuerpo).toEqual({ ids: ['n1'] }))
    await waitFor(() => expect(within(screen.getByTestId('bandeja')).queryByRole('button', { name: 'Leída' })).not.toBeInTheDocument())
    // Preferencias: activar el correo para la minuta.
    const prefs = screen.getByTestId('preferencias')
    expect(within(prefs).getByLabelText('Minuta del día enviada por app')).toBeChecked()
    expect(within(prefs).getByLabelText('Minuta del día enviada por email')).not.toBeChecked()
    await user.click(within(prefs).getByLabelText('Minuta del día enviada por email'))
    await waitFor(() => expect(llamadas.find((l) => l.clave === 'PUT /api/notificaciones/preferencias')!.cuerpo).toEqual({ evento: 'minuta.enviada', canales: ['app', 'email'] }))
  })
})
