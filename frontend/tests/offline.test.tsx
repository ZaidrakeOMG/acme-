import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { IndicadorConectividad } from '../src/components/IndicadorConectividad'
import { enviarMensaje, mensajesDe } from '../src/services/chat'
import { BaseLocal, baseLocal, usarBaseLocal } from '../src/services/db'
import { usarTransporte } from '../src/services/formularios/respuestas'
import { transporteHibrido } from '../src/services/offline/transporteRespuestas'
import { MAX_INTENTOS, syncEngine } from '../src/services/syncEngine'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const T = '11111111-1111-1111-1111-111111111111'
const UN1 = 'u0000000-0000-0000-0000-000000000001'
const EQ1 = 'e0000000-0000-0000-0000-000000000001'
const TF1 = 'a0000000-0000-0000-0000-000000000001'
const FAM = 'f0000000-0000-0000-0000-000000000001'
let contador = 0

const paquete = {
  servidor_at: '2026-10-28T10:00:00Z', desde: null, rol: 'operador',
  unidades: [{ id: UN1, tenant_id: T, codigo: 'SUC-001', nombre: 'Sucursal Centro', direccion: 'Av. Juárez 100', zona_horaria: 'America/Mexico_City', estado: 'activo', grupo_id: null, updated_at: '2026-10-01T00:00:00Z', version_hash: 'a', activo: true }],
  equipos: [{ id: EQ1, tenant_id: T, un_id: UN1, tipo_equipo_id: 'te1', codigo: 'EQ-0001', nombre: 'Refrigerador vertical', familia_id: FAM, con_contrato_activo: true, estado: 'activo', updated_at: '2026-10-01T00:00:00Z', version_hash: 'b', activo: true }],
  familias_equipo: [], tipos_equipo: [],
  tipos_falla: [{ id: TF1, prestador_id: 'p1', descripcion: 'No enciende', familia_equipo_id: FAM, requiere_revision_manual: false, updated_at: '2026-10-01T00:00:00Z', version_hash: 'c', activo: true }],
  niveles_severidad: [], formularios: [], formularios_ids: [],
}

beforeEach(() => {
  contador += 1
  usarBaseLocal(`acma-prueba-${contador}`)
  syncEngine.simularSinConexion(null)
})
afterEach(() => {
  syncEngine.simularSinConexion(true) // evita reintentos programados fuera de la prueba
})

describe('Cola de sincronización', () => {
  it('es FIFO, reintenta con retraso exponencial, marca «requiere atención» y se reanuda tras recargar', async () => {
    const fallo = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('sin red'))
    await syncEngine.encolar('transicion', { folio_id: 'f1', estado: 'en_camino' }, 'primera')
    await syncEngine.encolar('transicion', { folio_id: 'f1', estado: 'en_ejecucion' }, 'segunda')
    let r = await syncEngine.procesar()
    expect(r.pendientes).toBe(2)
    let fila = (await syncEngine.pendientes()).mutaciones
    expect(fila.map((m) => m.descripcion)).toEqual(['primera', 'segunda'])
    expect(fila[0]!.intentos).toBe(1)
    expect(new Date(fila[0]!.proximo_intento!).getTime()).toBeGreaterThan(Date.now())
    // Aún no toca reintentar: procesar no reenvía.
    const llamadas = fallo.mock.calls.length
    await syncEngine.procesar()
    expect(fallo.mock.calls.length).toBe(llamadas)
    // Agotar los intentos (adelantando el reloj de cada reintento).
    for (let i = 1; i < MAX_INTENTOS; i++) {
      await baseLocal.mutaciones_pendientes.toCollection().modify({ proximo_intento: new Date(Date.now() - 1).toISOString() })
      await syncEngine.procesar()
    }
    fila = (await syncEngine.pendientes()).mutaciones
    expect(fila.every((m) => m.estado === 'atencion' && m.intentos === MAX_INTENTOS)).toBe(true)
    expect((await syncEngine.resumen()).errores).toBe(2)
    // «Recarga»: otra instancia de la base ve la misma cola persistida.
    const otra = new BaseLocal(`acma-prueba-${contador}`)
    expect((await otra.mutaciones_pendientes.orderBy('orden').toArray()).map((m) => m.descripcion)).toEqual(['primera', 'segunda'])
    otra.close()
    // Reintento manual con red: se envían en orden en un solo lote y se retiran de la cola.
    fallo.mockRestore()
    const registro = simularApi({ 'POST /api/sync/mutaciones': (cuerpo) => ({ json: (cuerpo as { mutaciones: { id_cliente: string; tipo: string }[] }).mutaciones.map((m) => ({ id_cliente: m.id_cliente, tipo: m.tipo, resultado: 'aplicada', entidad_id: 'f1', codigo: null, mensaje: '' })) }) })
    await syncEngine.reintentar(fila[0]!.id_cliente)
    await syncEngine.reintentar(fila[1]!.id_cliente)
    const enviadas = registro.filter((l) => l.clave === 'POST /api/sync/mutaciones').flatMap((l) => (l.cuerpo as { mutaciones: { payload: { estado: string } }[] }).mutaciones)
    expect(enviadas.map((m) => m.payload.estado)).toEqual(['en_camino', 'en_ejecucion'])  // cada reintento manual envía su lote, en orden
    expect((await syncEngine.pendientes()).mutaciones).toHaveLength(0)
  })

  it('el formulario de atención se guarda parcial sin red con una sola mutación por respuesta', async () => {
    usarTransporte(transporteHibrido)
    try {
      syncEngine.simularSinConexion(true)
      const r = await transporteHibrido.crear('form-1', 'folio_atencion', { tenant_id: T, un_id: UN1, equipo_id: EQ1 }, 'folio-1')
      expect(r.estado).toBe('en_progreso')
      await transporteHibrido.guardar(r.id, { diag: 'primer avance' })
      await transporteHibrido.guardar(r.id, { diag: 'segundo avance' })
      const borrador = await baseLocal.respuestas_borrador.get(r.id)
      expect(borrador?.respuestas).toEqual({ diag: 'segundo avance' })
      expect(borrador?.creada_offline).toBe(true)
      const cola = (await syncEngine.pendientes()).mutaciones
      expect(cola.map((m) => m.tipo)).toEqual(['guardar_respuesta'])
      expect(cola[0]!.payload).toMatchObject({ respuesta_id: r.id, crear: { formulario_id: 'form-1', origen: 'folio_atencion', referencia_id: 'folio-1' }, respuestas: { diag: 'segundo avance' } })
      const e = await transporteHibrido.subirEvidencia(r.id, { archivo: new Blob(['foto'], { type: 'image/jpeg' }), nombre: 'antes.jpg', campoClave: 'fotos' })
      expect(e.calidad).toEqual({ pendiente: true })
      expect(await baseLocal.evidencias_pendientes.count()).toBe(1)
      const env = await transporteHibrido.enviar(r.id)
      expect(env.estado).toBe('enviado')
      expect((await syncEngine.pendientes()).mutaciones.map((m) => m.tipo)).toEqual(['guardar_respuesta', 'enviar_respuesta'])
    } finally {
      usarTransporte(null)
    }
  })

  it('el mensaje de chat se encola con la hora de escritura y aparece como pendiente con doble timestamp', async () => {
    syncEngine.simularSinConexion(true)
    const antes = Date.now()
    const m = await enviarMensaje('chat-1', 'Ya llegué')
    expect(m.pendiente).toBe(true)
    expect(new Date(m.timestamp_dispositivo!).getTime()).toBeGreaterThanOrEqual(antes)
    const cola = (await syncEngine.pendientes()).mutaciones
    expect(cola).toHaveLength(1)
    expect(cola[0]).toMatchObject({ tipo: 'mensaje_chat', id_cliente: m.id_cliente, payload: { chat_id: 'chat-1', contenido_texto: 'Ya llegué' } })
    expect(cola[0]!.timestamp_dispositivo).toBe(m.timestamp_dispositivo)
    const lista = await mensajesDe('chat-1')
    expect(lista.filter((x) => x.pendiente)).toHaveLength(1)
  })
})

describe('Indicador de conectividad', () => {
  it('muestra sin conexión con pendientes y en línea sin pendientes', async () => {
    syncEngine.simularSinConexion(true)
    await syncEngine.encolar('mensaje_chat', { chat_id: 'c', contenido_texto: 'x' }, 'm')
    render(<MemoryRouter><IndicadorConectividad /></MemoryRouter>)
    expect(await screen.findByText('Sin conexión · 1 pendiente(s)')).toBeInTheDocument()
    expect(screen.getByTestId('indicador-conectividad')).toHaveAttribute('href', '/sincronizacion')
    await syncEngine.descartar((await syncEngine.pendientes()).mutaciones[0]!.id_cliente)
    syncEngine.simularSinConexion(false)
    expect(await screen.findByText('En línea')).toBeInTheDocument()
  })
})

describe('App del operador', () => {
  async function entrar(ruta: string, rutas: Parameters<typeof simularApi>[0] = {}) {
    localStorage.setItem('acma.sesion', '1')  // P11a: solo la marca; el refresh va en cookie httpOnly
    const llamadas = simularApi({
      'POST /api/auth/refresh': () => ({ json: TOKENS }),
      'GET /api/auth/yo': () => ({ json: perfil('operador', { tenant_id: T }) }),
      'GET /api/sync/catalogos': () => ({ json: paquete }),
      'GET /api/push/clave-publica': () => ({ json: { clave_publica: null, habilitado: false } }),
      ...rutas,
    })
    renderApp(ruta)
    return llamadas
  }

  it('captura un folio sin red con los catálogos cacheados y lo envía al reconectar', async () => {
    const llamadas = await entrar('/campo/nuevo', {
      'GET /api/folios/verificar-duplicado': () => ({ json: { existe: false, bloqueo_total: false } }),
      'GET /api/unidades-negocio': () => ({ json: paquete.unidades }),
      'POST /api/sync/mutaciones': (cuerpo) => ({ json: (cuerpo as { mutaciones: { id_cliente: string; tipo: string }[] }).mutaciones.map((m) => ({ id_cliente: m.id_cliente, tipo: m.tipo, resultado: 'aplicada', entidad_id: '0f000000-0000-0000-0000-000000000009', codigo: null, mensaje: '' })) }),
    })
    await screen.findByRole('heading', { name: 'Nuevo folio' })
    await waitFor(async () => expect(await baseLocal.catalogos_cache.count()).toBe(3))
    syncEngine.simularSinConexion(true)
    await userEvent.type(screen.getByRole('combobox', { name: 'Unidad de negocio' }), 'cen')
    await userEvent.click(await screen.findByRole('button', { name: /SUC-001/ }))
    await userEvent.selectOptions(await screen.findByLabelText('Equipo'), EQ1)
    await userEvent.selectOptions(await screen.findByLabelText('Tipo de falla'), TF1)
    await userEvent.type(screen.getByLabelText('Descripción'), 'Capturado sin señal')
    await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Sí, es esta unidad' }))
    // Sin red: no hubo POST /api/folios; el folio quedó en la cola y se muestra como pendiente.
    await screen.findByText('Pendiente de enviar')
    expect(llamadas.some((l) => l.clave === 'POST /api/folios')).toBe(false)
    const cola = (await syncEngine.pendientes()).mutaciones
    expect(cola).toHaveLength(1)
    expect(cola[0]).toMatchObject({ tipo: 'crear_folio', payload: { un_id: UN1, equipo_id: EQ1, tipo_falla_id: TF1, confirmacion_un: true, descripcion: 'Capturado sin señal' } })
    // Vuelve la red: el lote se envía con la mutación y se vacía la cola.
    syncEngine.simularSinConexion(false)
    await syncEngine.procesar()
    const lote = llamadas.find((l) => l.clave === 'POST /api/sync/mutaciones')!.cuerpo as { mutaciones: { tipo: string; payload: { descripcion: string } }[] }
    expect(lote.mutaciones[0]!.tipo).toBe('crear_folio')
    expect(lote.mutaciones[0]!.payload.descripcion).toBe('Capturado sin señal')
    expect((await syncEngine.pendientes()).mutaciones).toHaveLength(0)
  })

  it('el inicio lista solo lo que la API devuelve para su UN y no ofrece cambiar de unidad', async () => {
    await entrar('/campo', {
      'GET /api/folios': (_c, url) => {
        expect(url.searchParams.get('un_id')).toBeNull()
        return { json: [{ id: '0f1', created_at: '', updated_at: '', version_hash: null, numero_folio: 'CD-000003', tenant_id: T, prestador_id: 'p', un_id: UN1, un_nombre: 'Sucursal Centro', un_codigo: 'SUC-001', equipo_id: EQ1, equipo_codigo: 'EQ-0001', equipo_nombre: 'Refrigerador', tipo_falla_id: TF1, tipo_falla: 'No enciende', tipo_folio: 'correctivo', estado: 'asignado', prioridad: 0, descripcion: 'No enfría', tecnico_id: 't1', tecnico_nombre: 'Tomás Técnico', severidad: null, severidad_origen: 'automatica_matriz', confirmacion_un: true, monto_estimado: null, criticidad: null, capturado_por: 'op', capturado_por_nombre: 'Olga', capturado_at: '2026-10-28T09:00:00Z', fecha_falla: '', fecha_inicio_atencion: null, fecha_cierre: null, razon_cancelacion: null, flujo: null, triggers_pendientes: 0, antiguedad_horas: 1 }] }
      },
    })
    const tarjeta = await screen.findByTestId('folio-campo-CD-000003')
    expect(within(tarjeta).getByText('Tomás Técnico')).toBeInTheDocument()
    expect(within(tarjeta).getByText('Disponible en Fase 2')).toBeInTheDocument()
    expect(screen.queryByLabelText('Unidad de negocio')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Nuevo folio' })).toHaveAttribute('href', '/campo/nuevo')
  })
})
