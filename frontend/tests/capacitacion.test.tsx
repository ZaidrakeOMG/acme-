import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { PerfilConTema, Rol, Tecnico } from '../src/types/api'
import type { Curso, Expediente, TecnicoDelCliente, Vencimiento } from '../src/types/capacitacion'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const TEC = 't0000000-0000-0000-0000-000000000001'
const CURSO = 'c0000000-0000-0000-0000-000000000001'

const tecnico: Tecnico = {
  id: TEC, prestador_id: 'p1', usuario_id: 'u1', nombre: 'Tomás Técnico', email: 'tecnico@acma.dev',
  numero_empleado: 'EMP-001', telefono: null, vehiculo_placas: 'ACM-001', estado: 'activo',
  fecha_ingreso: '2025-01-15', habilidades: [], tenants_habilitados: [], grupo_id: null,
}

const cursos: Curso[] = [
  { id: CURSO, prestador_id: 'p1', nombre: 'Manejo de refrigerantes (NOM-040)', proveedor: 'Instituto Demo',
    duracion_horas: '16.0', vigencia_meses: 24, habilidad_id: 'h1', tipo: 'certificacion',
    norma_referencia: 'NOM-040-SEMARNAT', descripcion: '', activo: true },
  { id: 'c2', prestador_id: null, nombre: 'Trabajo en alturas', proveedor: null, duracion_horas: '8.0',
    vigencia_meses: null, habilidad_id: null, tipo: 'curso', norma_referencia: 'NOM-009-STPS',
    descripcion: '', activo: true },
]

/** Expediente con un caso de cada color del semáforo, que es lo que se mira al elegir a quién asignar. */
function expediente(extra: Partial<Expediente> = {}): Expediente {
  return {
    tecnico_id: TEC, tecnico_nombre: 'Tomás Técnico', numero_empleado: 'EMP-001', dias_anticipacion: 30,
    cursos: [
      { id: 'tc1', curso_id: CURSO, curso: 'Manejo de refrigerantes (NOM-040)', tipo: 'certificacion',
        proveedor: 'Instituto Demo', norma_referencia: 'NOM-040-SEMARNAT', fecha_inicio: '2026-01-10',
        fecha_fin: '2026-01-12', calificacion: '95.0', aprobado: true, folio_constancia: 'CR-001',
        vigente_hasta: '2028-01-12', estado: 'vigente', dias_para_vencer: 432, tiene_certificado: true,
        notas: '', habilidad: 'Refrigeración' },
      { id: 'tc2', curso_id: 'c2', curso: 'Trabajo en alturas', tipo: 'curso', proveedor: null,
        norma_referencia: 'NOM-009-STPS', fecha_inicio: null, fecha_fin: '2025-11-20', calificacion: null,
        aprobado: true, folio_constancia: null, vigente_hasta: '2026-11-20', estado: 'por_vencer',
        dias_para_vencer: 14, tiene_certificado: false, notas: '', habilidad: null },
      { id: 'tc3', curso_id: 'c3', curso: 'Soldadura autógena', tipo: 'certificacion', proveedor: null,
        norma_referencia: null, fecha_inicio: null, fecha_fin: '2024-03-01', calificacion: null,
        aprobado: true, folio_constancia: null, vigente_hasta: '2026-03-01', estado: 'vencido',
        dias_para_vencer: -250, tiene_certificado: false, notas: '', habilidad: 'Soldadura' },
    ],
    habilidades: [
      { habilidad_id: 'h1', habilidad: 'Refrigeración', clave: 'refrigeracion', certificada: true,
        origen: 'curso', fecha_certificacion: '2026-01-12', vigencia_hasta: '2028-01-12', estado: 'vigente' },
      { habilidad_id: 'h3', habilidad: 'Soldadura', clave: 'soldadura', certificada: false, origen: 'curso',
        fecha_certificacion: '2024-03-01', vigencia_hasta: '2026-03-01', estado: 'vencido' },
    ],
    ...extra,
  }
}

const vencimientos: Vencimiento[] = [
  { tecnico_curso_id: 'tc2', tecnico_id: TEC, tecnico_nombre: 'Tomás Técnico', curso: 'Trabajo en alturas',
    tipo: 'curso', norma_referencia: 'NOM-009-STPS', vigente_hasta: '2026-11-20', dias: 14,
    estado: 'por_vencer', habilidad_id: null },
]

async function entrar(rol: Rol, ruta: string, rutas: Parameters<typeof simularApi>[0] = {},
                      extra: Partial<PerfilConTema> = {}) {
  localStorage.setItem('acma.sesion', '1')
  const llamadas = simularApi({
    'POST /api/auth/refresh': () => ({ json: TOKENS }),
    'GET /api/auth/yo': () => ({ json: perfil(rol, { prestador_id: 'p1', ...extra }) }),
    'GET /api/notificaciones/no-leidas': () => ({ json: { no_leidas: 0 } }),
    'GET /api/catalogos/tecnicos': () => ({ json: [tecnico] }),
    'GET /api/catalogos/habilidades': () => ({ json: [] }),
    'GET /api/capacitacion/cursos': () => ({ json: cursos }),
    'GET /api/capacitacion/vencimientos': () => ({ json: vencimientos }),
    [`GET /api/capacitacion/tecnicos/${TEC}/expediente`]: () => ({ json: expediente() }),
    'GET /api/capacitacion/alertas/configuracion': () => ({
      json: { prestador_id: 'p1', dias_anticipacion: 30, notificar_cliente: true, activa: true } }),
    ...rutas,
  })
  renderApp(ruta)
  return llamadas
}

describe('Capacitación y certificaciones (F2-01)', () => {
  it('el semáforo de vigencia dice el estado con texto, no solo con color', async () => {
    await entrar('admin_prestador', `/capacitacion?tecnico=${TEC}`)
    await screen.findByText('Cursos y certificaciones de Tomás Técnico')
    expect(screen.getAllByText('Vigente').length).toBeGreaterThan(0)
    expect(screen.getByText('Por vencer · 14 día(s)')).toBeInTheDocument()
    expect(screen.getByText('Vencida · hace 250 día(s)')).toBeInTheDocument()
    // Y la habilidad que perdió su certificación se marca como tal: es la que bloquea asignaciones.
    const habilidades = screen.getByTestId('habilidades-derivadas')
    expect(within(habilidades).getByText('No certificada')).toBeInTheDocument()
  })

  it('registra el curso con su constancia en multipart y refresca el expediente', async () => {
    let enviado: FormData | null = null
    await entrar('admin_prestador', `/capacitacion?tecnico=${TEC}`, {
      [`POST /api/capacitacion/tecnicos/${TEC}/cursos`]: (_c, url) => {
        void url
        return { estado: 201, json: expediente() }
      },
    })
    // El cuerpo multipart no pasa por `simularApi`, así que se observa el FormData desde el propio fetch.
    const original = globalThis.fetch
    globalThis.fetch = (async (entrada: RequestInfo | URL, init?: RequestInit) => {
      if (init?.body instanceof FormData) enviado = init.body
      return original(entrada, init)
    }) as typeof fetch

    await screen.findByText('Cursos y certificaciones de Tomás Técnico')
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Registrar curso' }))
    const dialogo = await screen.findByRole('dialog', { name: 'Registrar curso o certificación' })
    await user.selectOptions(within(dialogo).getByLabelText('Curso'), CURSO)
    expect(within(dialogo).getByText('Vigencia del curso: 24 meses desde la fecha de término.')).toBeInTheDocument()
    await user.upload(within(dialogo).getByLabelText('Constancia'),
      new File(['%PDF-1.4 demo'], 'constancia.pdf', { type: 'application/pdf' }))
    await user.click(within(dialogo).getByRole('button', { name: 'Guardar' }))

    await waitFor(() => expect(enviado).not.toBeNull())
    expect(enviado!.get('curso_id')).toBe(CURSO)
    expect((enviado!.get('certificado') as File).name).toBe('constancia.pdf')
    // «Aprobado» marcado es el caso normal: no se manda el campo, el servidor lo toma como aprobado.
    expect(enviado!.get('aprobado')).toBeNull()
    await screen.findByText('Curso registrado')
  })

  it('la vista del cliente solo muestra certificaciones vigentes de quien atiende sus unidades', async () => {
    const tecnicos: TecnicoDelCliente[] = [{
      tecnico_id: TEC, nombre: 'Tomás Técnico',
      certificaciones: [{ nombre: 'Manejo de refrigerantes (NOM-040)', tipo: 'certificacion',
        norma_referencia: 'NOM-040-SEMARNAT', proveedor: 'Instituto Demo', vigente_hasta: '2028-01-12',
        vigencia: 'vigente hasta 2028-01-12' }],
    }]
    await entrar('admin_empresa', '/capacitacion', {
      'GET /api/capacitacion/tecnicos-de-mis-unidades': () => ({ json: tecnicos }),
    }, { prestador_id: null, tenant_id: '11111111-1111-1111-1111-111111111111' })
    await screen.findByRole('heading', { name: 'Certificaciones del personal que me atiende' })
    await screen.findByText('Manejo de refrigerantes (NOM-040)')
    expect(within(screen.getByTestId('tecnicos-del-cliente')).getByText('Tomás Técnico')).toBeInTheDocument()
    // Sin expedientes ni pestañas de gestión: el cliente no ve el historial completo del técnico.
    expect(screen.queryByRole('tab', { name: 'Expedientes' })).not.toBeInTheDocument()
  })
})
