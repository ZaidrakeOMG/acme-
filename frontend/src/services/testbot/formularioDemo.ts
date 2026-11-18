/**
 * Datos ficticios para la prueba guiada de formularios.
 * Conserva las claves, el orden y las configuraciones existentes: nunca reemplaza
 * un formulario real por uno nuevo cuando ya existe uno en el constructor.
 */
import { CONFIG_DEFECTO, NOMBRE_TIPO, type Campo, type EsquemaFormulario, type TipoCampo } from '../../types/formularios'

const ESPECIFICACIONES: { tipo: TipoCampo; etiqueta: string; obligatorio: boolean; clave: string }[] = [
  { tipo: 'si_no', etiqueta: '¿El equipo funciona correctamente?', obligatorio: true, clave: 'equipo_funciona' },
  { tipo: 'texto_amplio', etiqueta: 'Descripción de la falla', obligatorio: false, clave: 'descripcion_falla' },
  { tipo: 'texto_amplio', etiqueta: 'Observaciones del mantenimiento', obligatorio: false, clave: 'observaciones_mantenimiento' },
  { tipo: 'texto', etiqueta: 'Nombre del equipo', obligatorio: true, clave: 'nombre_equipo' },
]

export function prepararEsquemaDemo(original: EsquemaFormulario): EsquemaFormulario {
  const secciones = original.secciones.length > 0
    ? original.secciones.map((s) => ({ ...s, campos: s.campos.map((c) => ({ ...c })) }))
    : [{ clave: 'seccion_1', titulo: 'Sección 1', campos: [] as Campo[] }]
  const existentes = new Set(secciones.flatMap((s) => s.campos.map((c) => c.clave)))
  const ocupados = new Set<string>()

  for (const esperado of ESPECIFICACIONES) {
    let campoElegido: Campo | null = null
    let seccionElegida = secciones[0]!
    for (const seccion of secciones) {
      const exacto = seccion.campos.find((c) =>
        c.tipo === esperado.tipo && c.etiqueta === esperado.etiqueta && !ocupados.has(c.clave))
      if (exacto) { campoElegido = exacto; seccionElegida = seccion; break }
    }
    if (!campoElegido) {
      for (const seccion of secciones) {
        const generico = seccion.campos.find((c) =>
          c.tipo === esperado.tipo && c.etiqueta === NOMBRE_TIPO[c.tipo] && !ocupados.has(c.clave))
        if (generico) { campoElegido = generico; seccionElegida = seccion; break }
      }
    }
    if (campoElegido) {
      ocupados.add(campoElegido.clave)
      const indice = seccionElegida.campos.findIndex((c) => c.clave === campoElegido!.clave)
      seccionElegida.campos[indice] = {
        ...campoElegido,
        etiqueta: campoElegido.etiqueta === NOMBRE_TIPO[campoElegido.tipo] ? esperado.etiqueta : campoElegido.etiqueta,
        obligatorio: esperado.obligatorio || campoElegido.obligatorio,
      }
      continue
    }
    let clave = esperado.clave
    let sufijo = 2
    while (existentes.has(clave)) clave = `${esperado.clave}_${sufijo++}`
    existentes.add(clave)
    ocupados.add(clave)
    secciones[0]!.campos.push({
      clave, etiqueta: esperado.etiqueta, tipo: esperado.tipo,
      obligatorio: esperado.obligatorio, config: structuredClone(CONFIG_DEFECTO[esperado.tipo]),
      condiciones: [],
    })
  }
  return { ...original, secciones }
}

export function respuestasDemo(esquema: EsquemaFormulario): Record<string, unknown> {
  const respuestas: Record<string, unknown> = {}
  const noSoportados: string[] = []
  for (const campo of esquema.secciones.flatMap((s) => s.campos)) {
    if (campo.tipo === 'si_no') respuestas[campo.clave] = true
    else if (campo.tipo === 'texto') respuestas[campo.clave] = 'Tablero eléctrico principal DEMO'
    else if (campo.tipo === 'texto_amplio') respuestas[campo.clave] = 'Verificación ficticia ACMA: sin anomalías.'
    else if (campo.obligatorio) noSoportados.push(campo.etiqueta)
  }
  if (noSoportados.length) {
    throw new Error(`Hay campos obligatorios que requieren una prueba especializada: ${noSoportados.join(', ')}. No se inventarán firmas, fotos ni evidencias.`)
  }
  return respuestas
}
