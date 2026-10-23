import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { beforeEach, describe, expect, it } from 'vitest'
import { Renderizador } from '../src/components/formularios/Renderizador'
import { limpiarCacheOpciones } from '../src/services/formularios/respuestas'
import { validar, visibilidad } from '../src/services/formularios/validacion'
import type { EsquemaFormulario, Evidencia } from '../src/types/formularios'
import { NOMBRE_TIPO, TIPOS_CAMPO } from '../src/types/formularios'
import { perfil, renderApp, simularApi, TOKENS } from './utilidades'

const F_REFRI = 'f0000000-0000-0000-0000-000000000001'
const F_ILUM = 'f0000000-0000-0000-0000-000000000002'
const FORM_ID = '10000000-0000-0000-0000-000000000001'

/** Misma regla de clave que el constructor: slug del nombre del tipo. */
function campoClave(tipo: string): string {
  return NOMBRE_TIPO[tipo as keyof typeof NOMBRE_TIPO].toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 40)
}

async function entrar(rol: Parameters<typeof perfil>[0], rutas = {}, ruta = '/formularios/constructor') {
  localStorage.setItem('acma.refresh', TOKENS.refresh_token)
  const llamadas = simularApi({
    'POST /api/auth/refresh': () => ({ json: TOKENS }),
    'GET /api/auth/yo': () => ({ json: perfil(rol, { prestador_id: 'p0000000-0000-0000-0000-000000000001' }) }),
    'GET /api/tenants': () => ({ json: [] }),
    'GET /api/formularios/catalogos-personalizados': () => ({ json: [] }),
    ...rutas,
  })
  renderApp(ruta)
  return llamadas
}

describe('Constructor', () => {
  it('agrega y configura un campo de cada uno de los 22 tipos', { timeout: 40000 }, async () => {
    await entrar('admin_prestador')
    await screen.findByRole('heading', { name: 'Nuevo formulario' })
    for (const tipo of TIPOS_CAMPO) {
      await userEvent.click(screen.getByTestId(`paleta-${tipo}`))
      expect(await screen.findByRole('heading', { name: `Propiedades · ${NOMBRE_TIPO[tipo]}` })).toBeInTheDocument()
      expect(screen.getByTestId('editor-config')).toBeInTheDocument()
      const etiqueta = screen.getByLabelText('Etiqueta') as HTMLInputElement
      await userEvent.clear(etiqueta)
      await userEvent.type(etiqueta, `Campo ${tipo}`)
      expect(screen.getByTestId(`lienzo-${campoClave(tipo)}`)).toHaveTextContent(`Campo ${tipo}`)
    }
    expect(screen.getAllByTestId(/^lienzo-/)).toHaveLength(22)
    // Parámetros específicos de §4.3 presentes en el panel.
    await userEvent.click(screen.getByTestId(`lienzo-${campoClave('fotografia')}`))
    expect(screen.getByLabelText('Fotos mínimas')).toBeInTheDocument()
    expect(screen.getByLabelText('Compresión máxima (%)')).toBeInTheDocument()
    expect(screen.getByLabelText('Origen')).toBeInTheDocument()
    await userEvent.click(screen.getByTestId(`lienzo-${campoClave('geolocalizacion')}`))
    expect(screen.getByLabelText('Radio de ajuste manual (m)')).toHaveValue(50)
    await userEvent.click(screen.getByTestId(`lienzo-${campoClave('boton_grupo')}`))
    expect(screen.getByLabelText('Opción 1 color')).toBeInTheDocument()
    await userEvent.click(screen.getByTestId(`lienzo-${campoClave('lista_desplegable')}`))
    await userEvent.selectOptions(screen.getByLabelText('Origen'), 'catalogo')
    expect(screen.getByLabelText('Cascada: campo padre que filtra')).toBeInTheDocument()
  })

  it('el editor de condiciones oculta y muestra campos en la vista previa', async () => {
    await entrar('admin_prestador')
    await screen.findByRole('heading', { name: 'Nuevo formulario' })
    await userEvent.click(screen.getByTestId('paleta-si_no'))
    await userEvent.click(screen.getByTestId('paleta-texto'))
    await userEvent.click(screen.getByRole('button', { name: '+ condición' }))
    await userEvent.selectOptions(screen.getByLabelText('Condición 1 campo'), campoClave('si_no'))
    await userEvent.selectOptions(screen.getByLabelText('Condición 1 valor'), 'false')
    expect(screen.getByTestId(`lienzo-${campoClave('texto')}`)).toHaveTextContent('1 cond.')
    await userEvent.click(screen.getByRole('button', { name: 'Vista previa' }))
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).queryByTestId(`campo-${campoClave('texto')}`)).not.toBeInTheDocument()
    await userEvent.click(within(dialogo).getByRole('button', { name: 'No' }))
    expect(within(dialogo).getByTestId(`campo-${campoClave('texto')}`)).toBeInTheDocument()
    await userEvent.click(within(dialogo).getByRole('button', { name: 'Sí' }))
    expect(within(dialogo).queryByTestId(`campo-${campoClave('texto')}`)).not.toBeInTheDocument()
  })

  it('guarda y publica el formulario', async () => {
    const guardado = { id: FORM_ID, prestador_id: 'p', tenant_id: null, nombre: 'Nuevo formulario', descripcion: '', tipo: 'libre', rol_destino: ['tecnico'], estado: 'borrador', version_publicada_id: null, es_plantilla_base: false, clonado_de_id: null, version_actual: 1, numero_version_publicada: null, esquema_json: { version_contrato: 1, secciones: [{ clave: 'seccion_1', titulo: 'Sección 1', campos: [] }] }, puede_editar: true, created_at: '', updated_at: '' }
    const llamadas = await entrar('admin_prestador', {
      'POST /api/formularios': () => ({ estado: 201, json: guardado }),
      [`GET /api/formularios/${FORM_ID}`]: () => ({ json: guardado }),
      [`PUT /api/formularios/${FORM_ID}`]: () => ({ json: guardado }),
      [`POST /api/formularios/${FORM_ID}/publicar`]: () => ({ json: { ...guardado, estado: 'publicado', numero_version_publicada: 1 } }),
    })
    await screen.findByRole('heading', { name: 'Nuevo formulario' })
    await userEvent.click(screen.getByTestId('paleta-texto'))
    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }))
    expect(await screen.findByText('Guardado como v1 (borrador)')).toBeInTheDocument()
    const post = llamadas.find((l) => l.clave === 'POST /api/formularios')?.cuerpo as { esquema: EsquemaFormulario; rol_destino: string[] }
    expect(post.esquema.secciones[0]!.campos[0]!.tipo).toBe('texto')
    expect(post.rol_destino).toEqual(['tecnico'])
    await userEvent.click(screen.getByRole('button', { name: 'Publicar' }))
    await userEvent.type(screen.getByLabelText('Notas de versión'), 'Primera versión')
    await userEvent.click(screen.getByRole('button', { name: 'Guardar y publicar' }))
    expect(await screen.findByText('Publicada la versión 1')).toBeInTheDocument()
    expect(llamadas.find((l) => l.clave === `POST /api/formularios/${FORM_ID}/publicar`)?.cuerpo).toEqual({ notas_version: 'Primera versión' })
  })
})

describe('Renderizador', () => {
  beforeEach(() => limpiarCacheOpciones())
  const esquema: EsquemaFormulario = { version_contrato: 1, secciones: [{ clave: 's', titulo: 'Datos', campos: [
    { clave: 'nombre', tipo: 'texto', etiqueta: 'Nombre', obligatorio: true, config: { longitud_min: 3, longitud_max: 50, formato: 'libre', regex: null, mensaje_formato: null }, condiciones: [] },
    { clave: 'fotos', tipo: 'fotografia', etiqueta: 'Fotos', obligatorio: true, config: { origen: 'camara', calidad: { tamano_minimo_kb: null, resolucion_minima_ancho: null, resolucion_minima_alto: null, compresion_maxima_pct: null }, cantidad_min: 2, cantidad_max: 3, etiquetas_secuencia: [], permitir_anotacion: true, vista_previa_confirmacion: true }, condiciones: [] },
    { clave: 'familia', tipo: 'radio', etiqueta: 'Familia', obligatorio: true, config: { disposicion: 'vertical' }, condiciones: [], fuente_opciones: { origen: 'catalogo', catalogo: 'familias_equipo', filtro_contexto: false, campo_padre: null } },
    { clave: 'falla', tipo: 'lista_desplegable', etiqueta: 'Tipo de falla', obligatorio: true, config: { busqueda: false, seleccion: 'unica', disponible_offline: true }, condiciones: [], fuente_opciones: { origen: 'catalogo', catalogo: 'tipos_falla', filtro_contexto: true, campo_padre: 'familia' } },
  ] }] }
  const fallas: Record<string, { valor: string; etiqueta: string }[]> = {
    [F_REFRI]: [{ valor: 'ne', etiqueta: 'No enfría' }, { valor: 'ru', etiqueta: 'Ruido inusual' }],
    [F_ILUM]: [{ valor: 'pa', etiqueta: 'Parpadea' }],
  }

  function Envoltorio({ evidencias = {} }: { evidencias?: Record<string, { tipo: string }[]> }) {
    const [valores, setValores] = useState<Record<string, unknown>>({})
    const [enviado, setEnviado] = useState<string | null>(null)
    return (
      <div>
        <Renderizador esquema={esquema} respuestas={valores} onChange={setValores} mostrarErrores={enviado !== null} evidencias={evidencias as unknown as Record<string, Evidencia[]>} contexto={{ tenant_id: 't' }} />
        <button onClick={() => { const { errores } = validar(esquema, valores, { evidencias }, true); setEnviado(errores.length ? `bloqueado:${errores.map((e) => e.campo).join(',')}` : 'enviado') }}>Enviar</button>
        {enviado && <p data-testid="resultado">{enviado}</p>}
      </div>
    )
  }

  it('bloquea el envío con obligatorios vacíos y fotos por debajo del mínimo', async () => {
    simularApi({
      'GET /api/formularios/opciones': (_c, url) => ({ json: { opciones: url.searchParams.get('catalogo') === 'familias_equipo' ? [{ valor: F_REFRI, etiqueta: 'Refrigeración' }] : fallas[url.searchParams.get('padre') ?? ''] ?? [], aviso: null } }),
    })
    render(<Envoltorio evidencias={{ fotos: [{ tipo: 'foto' }] }} />)
    await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
    expect(screen.getByTestId('resultado')).toHaveTextContent('bloqueado:nombre,fotos,familia,falla')
    expect(screen.getByText('Este campo es obligatorio')).toBeInTheDocument()
    expect(screen.getByText('Se requieren al menos 2 foto(s); hay 1')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/Nombre/), 'Compresor')
    await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
    expect(screen.getByTestId('resultado')).toHaveTextContent('bloqueado:fotos,familia,falla')
  })

  it('cascada familia → tipo de falla: el hijo se filtra por el padre y se limpia al cambiarlo', async () => {
    simularApi({
      'GET /api/formularios/opciones': (_c, url) => {
        if (url.searchParams.get('catalogo') === 'familias_equipo') return { json: { opciones: [{ valor: F_REFRI, etiqueta: 'Refrigeración' }, { valor: F_ILUM, etiqueta: 'Iluminación' }], aviso: null } }
        return { json: { opciones: fallas[url.searchParams.get('padre') ?? ''] ?? [], aviso: null } }
      },
    })
    render(<Envoltorio />)
    const selectFalla = await screen.findByLabelText(/Tipo de falla/)
    expect(within(selectFalla).getAllByRole('option')).toHaveLength(1)  // sin padre: solo "Selecciona…"
    await userEvent.click(await screen.findByLabelText('Refrigeración'))
    await waitFor(() => expect(within(screen.getByLabelText(/Tipo de falla/)).getByRole('option', { name: 'No enfría' })).toBeInTheDocument())
    await userEvent.selectOptions(screen.getByLabelText(/Tipo de falla/), 'ne')
    expect(screen.getByLabelText(/Tipo de falla/)).toHaveValue('ne')
    await userEvent.click(screen.getByLabelText('Iluminación'))
    await waitFor(() => expect(within(screen.getByLabelText(/Tipo de falla/)).getByRole('option', { name: 'Parpadea' })).toBeInTheDocument())
    expect(screen.getByLabelText(/Tipo de falla/)).toHaveValue('')
    expect(within(screen.getByLabelText(/Tipo de falla/)).queryByRole('option', { name: 'No enfría' })).not.toBeInTheDocument()
  })
})

describe('Motor de validación (espejo del servidor)', () => {
  it('visibilidad en cadena y cálculos', () => {
    const e: EsquemaFormulario = { version_contrato: 1, secciones: [{ clave: 's', titulo: 'S', campos: [
      { clave: 'enciende', tipo: 'si_no', etiqueta: 'E', obligatorio: true, config: {}, condiciones: [] },
      { clave: 'detalle', tipo: 'texto', etiqueta: 'D', obligatorio: true, config: { longitud_min: 0, longitud_max: 100, formato: 'libre', regex: null, mensaje_formato: null }, condiciones: [{ campo_origen: 'enciende', operador: 'igual', valor: false, accion: 'mostrar' }] },
      { clave: 'nivel', tipo: 'slider', etiqueta: 'N', obligatorio: false, config: { minimo: 0, maximo: 10, incremento: 1, etiqueta_min: null, etiqueta_max: null, modo_rango: false }, condiciones: [{ campo_origen: 'detalle', operador: 'contiene', valor: 'grave', accion: 'mostrar' }] },
      { clave: 'ini', tipo: 'fecha_hora', etiqueta: 'I', obligatorio: false, config: { modo: 'ambos', fecha_minima: null, fecha_maxima: null, intervalo_minutos: 1, defecto_hoy_mas_dias: null, vinculo: null }, condiciones: [] },
      { clave: 'fin', tipo: 'fecha_hora', etiqueta: 'F', obligatorio: false, config: { modo: 'ambos', fecha_minima: null, fecha_maxima: null, intervalo_minutos: 1, defecto_hoy_mas_dias: null, vinculo: { rol: 'fin', campo_par: 'ini' } }, condiciones: [] },
      { clave: 'dur', tipo: 'matematicas_tiempo', etiqueta: 'Dur', obligatorio: false, config: { inicio: { origen: 'campo', valor: 'ini' }, fin: { origen: 'campo', valor: 'fin' }, unidad: 'compuesto' }, condiciones: [] },
      { clave: 'ref', tipo: 'concatenacion', etiqueta: 'R', obligatorio: false, config: { partes: [{ tipo: 'texto', valor: 'R' }, { tipo: 'campo', valor: 'detalle' }], separador: '-', mayusculas: true }, condiciones: [] },
    ] }] }
    expect(visibilidad(e, { enciende: true, detalle: 'grave' })).toEqual(new Set(['enciende', 'ini', 'fin', 'dur', 'ref']))
    expect(validar(e, { enciende: true }).errores).toEqual([])
    expect(validar(e, { enciende: false }).errores).toEqual([{ campo: 'detalle', mensaje: 'Este campo es obligatorio' }])
    const { salida, errores } = validar(e, { enciende: false, detalle: 'falla grave', nivel: 9, ini: '2026-10-23T09:00', fin: '2026-10-24T10:30' })
    expect(errores).toEqual([])
    expect(salida.dur).toEqual({ minutos: 1530, unidad: 'compuesto', texto: '1d 1h 30min' })
    expect(salida.ref).toBe('R-FALLA GRAVE')
    expect(validar(e, { enciende: false, detalle: 'x', ini: '2026-10-23T09:00', fin: '2026-10-23T08:00' }).errores).toEqual([{ campo: 'fin', mensaje: 'La fecha de fin no puede ser anterior a la de inicio' }])
  })
})
