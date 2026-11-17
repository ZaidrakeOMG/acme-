import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { pestanasDe } from '../src/pages/catalogos/Catalogos'
import type { Matriz, PerfilConTema, Rol } from '../src/types/api'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const T = '11111111-1111-1111-1111-111111111111'
const F_REFRI = 'f0000000-0000-0000-0000-000000000001'
const TE_VERT = 'e0000000-0000-0000-0000-000000000001'
const TE_CAM = 'e0000000-0000-0000-0000-000000000002'
const TF_NE = 'a0000000-0000-0000-0000-000000000001'
const N_CRIT = 'c0000000-0000-0000-0000-000000000005'
const N_ALTA = 'c0000000-0000-0000-0000-000000000004'
const P = 'p0000000-0000-0000-0000-000000000001'

const matriz: Matriz = {
  tenant_id: T,
  tipos_falla: [{ id: TF_NE, descripcion: 'No enciende', familia_equipo_id: F_REFRI, prestador_id: P }],
  tipos_equipo: [{ id: TE_VERT, nombre: 'Refrigerador vertical', familia_id: F_REFRI, en_uso: true }, { id: TE_CAM, nombre: 'Cámara', familia_id: F_REFRI, en_uso: false }],
  niveles: [{ id: N_ALTA, prestador_id: P, clave: 'alta', nombre: 'Alta', orden: 4, color_hex: '#F57C00' }, { id: N_CRIT, prestador_id: P, clave: 'critica', nombre: 'Crítica', orden: 5, color_hex: '#D32F2F' }],
  celdas: [{ tipo_falla_id: TF_NE, tipo_equipo_id: TE_VERT, nivel_severidad_id: N_CRIT }],
  faltantes_en_uso: 0,
}

const vacias = Object.fromEntries(['/api/catalogos/tecnicos', '/api/catalogos/habilidades', '/api/catalogos/grupos-tecnicos', '/api/catalogos/severidades',
  '/api/catalogos/equipos', '/api/unidades-negocio', '/api/catalogos/tipos-falla', '/api/tenants', '/api/prestadores', '/api/contratos']
  .map((r) => [`GET ${r}`, () => ({ json: [] })]))

async function entrar(rol: Rol, extra: Partial<PerfilConTema> = {}, rutas = {}) {
  localStorage.setItem('acma.sesion', '1')  // P11a: solo la marca; el refresh va en cookie httpOnly
  const llamadas = simularApi({
    'POST /api/auth/refresh': () => ({ json: TOKENS }),
    'GET /api/auth/yo': () => ({ json: perfil(rol, { tenant_id: rol === 'admin_empresa' ? T : null, ...extra }) }),
    ...vacias,
    'GET /api/catalogos/familias-equipo': () => ({ json: [{ id: F_REFRI, tenant_id: null, nombre: 'Refrigeración', descripcion: '', activa: true, es_global: true }] }),
    ...rutas,
  })
  renderApp('/catalogos')
  await screen.findByRole('heading', { name: 'Catálogos maestros' })
  return llamadas
}

describe('Catálogos', () => {
  it.each<[Rol, string[]]>([
    ['admin_prestador', ['Técnicos', 'Severidades', 'Familias y tipos', 'Equipos', 'Tipos de falla', 'Matriz de severidad', 'Importar']],
    ['admin_empresa', ['Severidades', 'Familias y tipos', 'Equipos', 'Tipos de falla', 'Matriz de severidad', 'Importar']],
    ['mesa_control', ['Técnicos', 'Severidades', 'Familias y tipos', 'Equipos', 'Tipos de falla', 'Matriz de severidad']],
    ['admin_un', ['Severidades', 'Familias y tipos', 'Equipos', 'Tipos de falla', 'Matriz de severidad']],
  ])('%s ve exactamente sus pestañas', async (rol, esperadas) => {
    await entrar(rol)
    const tabs = screen.getAllByRole('tab').map((t) => t.textContent)
    expect(tabs).toEqual(esperadas)
    expect(pestanasDe(rol).map((p) => p.nombre)).toEqual(esperadas)
  })

  it('superadmin elige un prestador antes de administrar técnicos', async () => {
    const llamadas = await entrar('superadmin', {}, {
      'GET /api/prestadores': () => ({ json: [{
        id: P, razon_social: 'Prestador de ejemplo', rfc: 'AAA010101AAA',
        estado: 'activo', created_at: '', updated_at: '', version_hash: null,
      }] }),
    })
    expect(await screen.findByText('Selecciona un prestador')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Nuevo técnico' })).not.toBeInTheDocument()
    expect(llamadas.some(l => l.clave === 'GET /api/catalogos/tecnicos')).toBe(false)
    await userEvent.selectOptions(screen.getByLabelText('Prestador'), P)
    expect(await screen.findByRole('button', { name: 'Nuevo técnico' })).toBeInTheDocument()
    await waitFor(() => {
      expect(llamadas.some(l => l.clave === 'GET /api/catalogos/tecnicos' &&
        l.url?.includes('prestador_id='))).toBe(true)
    })
  })

  it('un rol sin el módulo no entra a /catalogos', async () => {
    localStorage.setItem('acma.sesion', '1')  // P11a: solo la marca; el refresh va en cookie httpOnly
    simularApi({ 'POST /api/auth/refresh': () => ({ json: TOKENS }), 'GET /api/auth/yo': () => ({ json: perfil('operador') }) })
    renderApp('/catalogos')
    expect(await screen.findByText('Tu rol no tiene acceso a este módulo.')).toBeInTheDocument()
  })

  it('admin empresa edita una celda de la matriz y ve el color del nivel', async () => {
    let actual = matriz
    const llamadas = await entrar('admin_empresa', {}, {
      'GET /api/catalogos/matriz-severidad': () => ({ json: actual }),
      'PUT /api/catalogos/matriz-severidad/celda': (cuerpo: unknown) => {
        const c = cuerpo as { tipo_falla_id: string; tipo_equipo_id: string; nivel_severidad_id: string }
        actual = { ...actual, celdas: [{ tipo_falla_id: c.tipo_falla_id, tipo_equipo_id: c.tipo_equipo_id, nivel_severidad_id: c.nivel_severidad_id }] }
        return { json: actual }
      },
    })
    await userEvent.click(screen.getByRole('tab', { name: 'Matriz de severidad' }))
    const celda = await screen.findByLabelText('No enciende × Refrigerador vertical')
    expect(celda).toHaveValue(N_CRIT)
    expect(celda).toBeEnabled()
    await userEvent.selectOptions(celda, N_ALTA)
    await waitFor(() => expect(screen.getByLabelText('No enciende × Refrigerador vertical')).toHaveValue(N_ALTA))
    const put = llamadas.find((l) => l.clave === 'PUT /api/catalogos/matriz-severidad/celda')
    expect(put?.cuerpo).toEqual({ tipo_falla_id: TF_NE, tipo_equipo_id: TE_VERT, nivel_severidad_id: N_ALTA })
    expect(screen.getByLabelText('No enciende × Cámara')).toHaveValue('')
  })

  it('mesa de control ve la matriz sin poder editarla', async () => {
    await entrar('mesa_control', { prestador_id: P }, {
      'GET /api/tenants': () => ({ json: [{ id: T, razon_social: 'Cliente Demo', rfc: 'X', pais: 'MX', moneda: 'MXN', zona_horaria: 'z', estado: 'activo', created_at: '', updated_at: '', version_hash: null }] }),
      'GET /api/catalogos/matriz-severidad': () => ({ json: matriz }),
    })
    await userEvent.click(screen.getByRole('tab', { name: 'Matriz de severidad' }))
    await userEvent.selectOptions(await screen.findByLabelText('Cliente'), T)
    expect(await screen.findByLabelText('No enciende × Refrigerador vertical')).toBeDisabled()
  })

  it('flujo de importación: plantilla, vista previa con errores y confirmación', async () => {
    const importacion = {
      id: 'i0000000-0000-0000-0000-000000000001', catalogo: 'equipos', archivo_nombre: 'equipos.csv', total_filas: 3, filas_ok: 1, filas_error: 1,
      errores_json: [{ fila: 3, columna: 'un_codigo', motivo: 'La UN «SUC-999» no existe' }],
      duplicados_json: [{ fila: 4, columna: 'codigo', motivo: 'Ya existe en ACMA; se omite' }],
      estado: 'vista_previa', vista_previa: [{ codigo: 'EQ-0100', nombre: 'Vitrina', fila: 2 }], resultado: null,
    }
    const llamadas = await entrar('admin_empresa', {}, {
      'GET /api/catalogos/importar/catalogos': () => ({ json: [
        { clave: 'equipos', nombre: 'Equipos', propietario: 'tenant', columnas: [{ nombre: 'codigo', requerida: true, descripcion: '', ejemplo: '' }, { nombre: 'marca', requerida: false, descripcion: '', ejemplo: '' }] },
        { clave: 'tecnicos', nombre: 'Técnicos', propietario: 'prestador', columnas: [] },
      ] }),
      'POST /api/catalogos/importar/equipos': () => ({ estado: 201, json: importacion }),
      [`POST /api/catalogos/importar/${importacion.id}/confirmar`]: () => ({ json: { ...importacion, estado: 'confirmada', resultado: { creados: 1, actualizados: 0 } } }),
    })
    await userEvent.click(screen.getByRole('tab', { name: 'Importar' }))
    const selector = await screen.findByLabelText('Catálogo')
    expect(within(selector).queryByText('Técnicos')).not.toBeInTheDocument()  // catálogo del prestador: no lo importa el tenant
    await userEvent.selectOptions(selector, 'equipos')
    expect(screen.getByText('codigo*')).toBeInTheDocument()

    const validar = screen.getByRole('button', { name: 'Validar' })
    expect(validar).toBeDisabled()
    await userEvent.upload(screen.getByLabelText('Archivo'), new File(['codigo,nombre\nEQ-0100,Vitrina\n'], 'equipos.csv', { type: 'text/csv' }))
    expect(validar).toBeEnabled()
    await userEvent.click(validar)

    expect(await screen.findByText(/1 válidas/)).toBeInTheDocument()
    expect(screen.getByText('Fila 3 · un_codigo: La UN «SUC-999» no existe')).toBeInTheDocument()
    expect(screen.getByText('EQ-0100')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Confirmar 1 fila(s)' }))
    expect(await screen.findByText('Importación aplicada: 1 creados, 0 actualizados.')).toBeInTheDocument()
    expect(llamadas.some((l) => l.clave === `POST /api/catalogos/importar/${importacion.id}/confirmar`)).toBe(true)
    expect(screen.queryByRole('button', { name: /Confirmar/ })).not.toBeInTheDocument()
  })
})
