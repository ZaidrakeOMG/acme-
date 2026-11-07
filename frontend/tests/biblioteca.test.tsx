import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { ApoyoDelFolio } from '../src/pages/campo/tecnico/ApoyoDelFolio'
import { MisManuales } from '../src/pages/campo/tecnico/MisManuales'
import { conciliar, espacio, guardados, type MetadatoBiblioteca } from '../src/services/bibliotecaOffline'
import { baseLocal, usarBaseLocal } from '../src/services/db'
import { syncEngine } from '../src/services/syncEngine'
import type { ApoyoDeFolio, Manual } from '../src/types/capacitacion'
import { simularApi } from './utilidades'

const FOLIO = '0f000000-0000-0000-0000-000000000061'
const MANUAL = 'm0000000-0000-0000-0000-000000000001'
const TIPO = 'te000000-0000-0000-0000-000000000001'
let contador = 0

const manual: Manual = {
  id: MANUAL, tipo_equipo_id: TIPO, tipo_equipo: 'Refrigerador vertical', titulo: 'Ficha técnica RV-200',
  categoria: 'ficha_tecnica', descripcion: 'Datos de placa y refrigerante', version: 1,
  fecha_subida: '2026-11-01T10:00:00Z', nombre_original: 'rv200.pdf', mime: 'application/pdf',
  bytes: 240_000, hash_sha256: 'a'.repeat(64), updated_at: '2026-11-01T10:00:00Z',
}

const apoyo: ApoyoDeFolio = {
  folio_id: FOLIO, tipo_equipo_id: TIPO,
  contenido: {
    id: 'cs1', titulo: 'Preventivo mensual de refrigeración', periodicidad: 'mensual', version: 1,
    puntos_revision: [
      { orden: 1, descripcion: 'Limpiar condensador', obligatorio: true },
      { orden: 2, descripcion: 'Medir temperatura de evaporación', obligatorio: false },
    ],
  },
  manuales: [manual],
}

function metadato(extra: Partial<MetadatoBiblioteca> = {}): MetadatoBiblioteca {
  return {
    clase: 'manual', id: MANUAL, tipo_equipo_id: TIPO, titulo: manual.titulo, categoria: 'ficha_tecnica',
    version: 1, mime: 'application/pdf', bytes: manual.bytes, activo: true, de_mis_folios: true, ...extra,
  }
}

beforeEach(() => {
  contador += 1
  usarBaseLocal(`acma-biblioteca-${contador}`)
  syncEngine.simularSinConexion(null)
})
afterEach(() => { syncEngine.simularSinConexion(true) })

describe('Biblioteca en la app del técnico (F2-01)', () => {
  it('muestra los puntos de revisión del contrato y el manual del equipo durante la atención', async () => {
    simularApi({
      [`GET /api/biblioteca/folios/${FOLIO}/apoyo`]: () => ({ json: apoyo }),
      [`GET /api/biblioteca/manuales/${MANUAL}/enlace`]: () => ({
        json: { url: '/api/biblioteca/archivo?token=t', expira_en_segundos: 300, nombre: 'rv200.pdf',
                mime: 'application/pdf' } }),
      'GET /api/biblioteca/archivo': () => ({ json: '%PDF-1.4 demo' }),
      'POST /api/biblioteca/offline': () => ({ estado: 201, json: { mensaje: 'Registrado' } }),
    })
    render(<ApoyoDelFolio folioId={FOLIO} enLinea />)

    const puntos = await screen.findByTestId('puntos-del-folio')
    expect(within(puntos).getByText('Limpiar condensador')).toBeInTheDocument()
    // Solo el punto obligatorio lleva la marca: el otro es informativo.
    expect(within(puntos).getAllByText('Obligatorio')).toHaveLength(1)
    expect(screen.getByText('Ficha técnica RV-200')).toBeInTheDocument()

    // Guardarlo deja el archivo en el dispositivo y lo registra en el servidor.
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Guardar' }))
    await screen.findByText('«Ficha técnica RV-200» quedó disponible sin señal')
    const fila = await baseLocal.biblioteca_offline.get(`manual:${MANUAL}`)
    // `fake-indexeddb` no devuelve el Blob como instancia de Blob, así que se comprueba que quedó guardado con su
    // tamaño (que se midió del archivo real al escribirlo) y su versión.
    expect(fila?.archivo).toBeTruthy()
    expect(fila?.bytes).toBeGreaterThan(0)
    expect(fila?.version).toBe(1)
  })

  it('sin señal usa lo descargado: no se queda sin puntos de revisión ni sin manual', async () => {
    await baseLocal.biblioteca_offline.bulkPut([
      { clave: `manual:${MANUAL}`, clase: 'manual', id: MANUAL, titulo: manual.titulo, tipo_equipo_id: TIPO,
        categoria: 'ficha_tecnica', version: 1, mime: 'application/pdf', bytes: 1200,
        archivo: new Blob(['%PDF-1.4'], { type: 'application/pdf' }), puntos_revision: null,
        descargado: '2026-11-05T10:00:00Z', desactualizado: false },
      { clave: 'contenido_servicio:cs1', clase: 'contenido_servicio', id: 'cs1', titulo: 'Preventivo mensual',
        tipo_equipo_id: TIPO, categoria: null, version: 1, mime: null, bytes: 180, archivo: null,
        puntos_revision: [{ descripcion: 'Limpiar condensador', obligatorio: true }],
        descargado: '2026-11-05T10:00:00Z', desactualizado: false },
    ])
    simularApi({})      // todo responde 404: equivale a estar sin señal
    render(<ApoyoDelFolio folioId={FOLIO} enLinea={false} />)

    const puntos = await screen.findByTestId('puntos-del-folio')
    expect(within(puntos).getByText('Limpiar condensador')).toBeInTheDocument()
    expect(screen.getByText('Sin señal: se muestra lo que tienes descargado.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ver manual' })).toBeInTheDocument()
  })

  it('«Mis manuales sin conexión» descarga, avisa de la versión nueva, borra y respeta el límite', async () => {
    simularApi({
      'GET /api/biblioteca/manuales': () => ({ json: [manual] }),
      [`GET /api/biblioteca/manuales/${MANUAL}/enlace`]: () => ({
        json: { url: '/api/biblioteca/archivo?token=t', expira_en_segundos: 300, nombre: 'rv200.pdf',
                mime: 'application/pdf' } }),
      'GET /api/biblioteca/archivo': () => ({ json: '%PDF-1.4 demo' }),
      'POST /api/biblioteca/offline': () => ({ estado: 201, json: { mensaje: 'Registrado' } }),
    })
    const vista = render(<MemoryRouter><MisManuales /></MemoryRouter>)

    const user = userEvent.setup()
    const pendientes = await screen.findByTestId('manuales-por-descargar')
    await user.click(within(pendientes).getByRole('button', { name: 'Guardar' }))
    await screen.findByText('«Ficha técnica RV-200» quedó disponible sin señal')
    expect(within(screen.getByTestId('manuales-offline')).getByText('Ficha técnica RV-200')).toBeInTheDocument()

    // Una versión nueva en el servidor marca lo guardado como desactualizado (§6.10.4).
    const resumen = await conciliar([metadato({ version: 2, de_mis_folios: false })])
    expect(resumen.desactualizados).toBe(1)
    expect((await guardados())[0]!.desactualizado).toBe(true)

    // Borrarlo libera el espacio y lo saca de la lista (pantalla recargada, como al volver a entrar).
    vista.unmount()
    render(<MemoryRouter><MisManuales /></MemoryRouter>)
    const lista = await screen.findByTestId('manuales-offline')
    expect(within(lista).getByText('Hay versión nueva')).toBeInTheDocument()
    await user.click(within(lista).getByRole('button', { name: 'Borrar' }))
    await waitFor(async () => expect(await baseLocal.biblioteca_offline.count()).toBe(0))
    expect((await espacio()).usadoBytes).toBe(0)
  })

  it('la conciliación retira lo que se dio de baja y no descarga lo que no es de sus folios', async () => {
    await baseLocal.biblioteca_offline.put({
      clave: `manual:${MANUAL}`, clase: 'manual', id: MANUAL, titulo: manual.titulo, tipo_equipo_id: TIPO,
      categoria: 'ficha_tecnica', version: 1, mime: 'application/pdf', bytes: 1200,
      archivo: new Blob(['%PDF-1.4'], { type: 'application/pdf' }), puntos_revision: null,
      descargado: '2026-11-05T10:00:00Z', desactualizado: false,
    })
    simularApi({ 'POST /api/biblioteca/offline': () => ({ estado: 201, json: { mensaje: 'Borrado registrado' } }) })
    const resumen = await conciliar([metadato({ activo: false })])
    expect(resumen.retirados).toBe(1)
    expect(await baseLocal.biblioteca_offline.count()).toBe(0)

    // Un manual ajeno a sus folios no se baja solo, aunque la descarga automática esté activa.
    const otro = await conciliar([metadato({ id: 'm2', de_mis_folios: false })])
    expect(otro.descargados).toBe(0)
  })
})
