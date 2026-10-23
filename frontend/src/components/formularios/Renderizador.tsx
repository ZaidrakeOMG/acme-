import { useEffect, useMemo, useRef, useState } from 'react'
import { opcionesCatalogo } from '../../services/formularios/respuestas'
import { validar, visibilidad, type ContextoValidacion, type ErrorValidacion } from '../../services/formularios/validacion'
import type { Campo, ContextoRespuesta, EsquemaFormulario, Evidencia, OpcionCatalogo } from '../../types/formularios'
import { TIPOS_CALCULADOS, camposDe } from '../../types/formularios'
import { BotonGrupo, Calculado, Encuesta, EtiquetaInfo, FechaHora, ListaDesplegable, OpcionMultiple, Radio, SiNo, Slider, Texto, type PropsCampo } from './campos/basicos'
import { Archivo, Audio, Dibujo, Firma, Fotografia } from './campos/evidencias'
import { Escaner } from './campos/escaner'
import { Geolocalizacion } from './campos/geolocalizacion'

export interface PropsRenderizador {
  esquema: EsquemaFormulario
  respuestas: Record<string, unknown>
  onChange: (respuestas: Record<string, unknown>) => void
  contexto?: ContextoRespuesta
  respuestaId?: string | null
  evidencias?: Record<string, Evidencia[]>
  onEvidencias?: (campoClave: string, lista: Evidencia[]) => void
  soloLectura?: boolean
  mostrarErrores?: boolean
  iniciadoAt?: Date
  calidadDefaults?: { tamano_minimo_kb: number; resolucion_minima_ancho: number; resolucion_minima_alto: number; compresion_maxima_pct: number } | null
  /** desactiva las llamadas a catálogos del sistema (constructor sin contexto) */
  sinCatalogos?: boolean
}

type EstadoOpciones = Record<string, { opciones: OpcionCatalogo[]; aviso: string | null }>

/** Opciones de los campos enlazados a catálogo, con contexto del folio y cascada por campo padre. */
function useOpciones(esquema: EsquemaFormulario, respuestas: Record<string, unknown>, contexto: ContextoRespuesta | undefined, desactivado: boolean): EstadoOpciones {
  const [estado, setEstado] = useState<EstadoOpciones>({})
  const campos = useMemo(() => camposDe(esquema).filter((c) => c.fuente_opciones?.origen === 'catalogo'), [esquema])
  const claves = campos.map((c) => {
    const f = c.fuente_opciones!
    if (f.origen !== 'catalogo') return ''
    const padre = f.campo_padre ? respuestas[f.campo_padre] : undefined
    return JSON.stringify({ c: c.clave, catalogo: f.catalogo, padre: padre ?? null, id: f.catalogo_personalizado_id ?? null, ctx: f.filtro_contexto ? contexto : null })
  }).join('|')
  useEffect(() => {
    if (desactivado) return
    let activo = true
    for (const campo of campos) {
      const f = campo.fuente_opciones!
      if (f.origen !== 'catalogo') continue
      const padre = f.campo_padre ? respuestas[f.campo_padre] : undefined
      if (f.campo_padre && (padre === undefined || padre === null || padre === '')) {
        setEstado((s) => ({ ...s, [campo.clave]: { opciones: [], aviso: null } }))
        continue
      }
      const params: Record<string, string | undefined> = {
        catalogo: f.catalogo, padre: padre != null ? String(padre) : undefined, catalogo_personalizado_id: f.catalogo_personalizado_id ?? undefined,
        tenant_id: contexto?.tenant_id ?? undefined, un_id: f.filtro_contexto ? contexto?.un_id ?? undefined : undefined, equipo_id: f.filtro_contexto ? contexto?.equipo_id ?? undefined : undefined,
      }
      opcionesCatalogo(params).then((r) => { if (activo) setEstado((s) => ({ ...s, [campo.clave]: r })) }).catch(() => { if (activo) setEstado((s) => ({ ...s, [campo.clave]: { opciones: [], aviso: 'No se pudo cargar el catálogo' } })) })
    }
    return () => { activo = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [claves, desactivado])
  return estado
}

const COMPONENTES: Record<string, (p: PropsCampo) => React.JSX.Element> = {
  si_no: SiNo, texto: Texto, texto_amplio: Texto, radio: Radio, boton_grupo: BotonGrupo, lista_desplegable: ListaDesplegable,
  opcion_multiple: OpcionMultiple, seleccion_multiple: OpcionMultiple, slider: Slider, encuesta_satisfaccion: Encuesta, fecha_hora: FechaHora,
  etiqueta_info: EtiquetaInfo, concatenacion: Calculado, matematicas_tiempo: Calculado, sello_fecha_hora: Calculado, escaner: Escaner, geolocalizacion: Geolocalizacion,
}
const EVIDENCIA = { fotografia: Fotografia, firma: Firma, dibujo: Dibujo, archivo: Archivo, audio: Audio } as const

export function Renderizador({ esquema, respuestas, onChange, contexto, respuestaId = null, evidencias = {}, onEvidencias, soloLectura = false, mostrarErrores = false, iniciadoAt, calidadDefaults, sinCatalogos = false }: PropsRenderizador) {
  const opciones = useOpciones(esquema, respuestas, contexto, sinCatalogos)
  const visibles = useMemo(() => visibilidad(esquema, respuestas), [esquema, respuestas])
  const ctx: ContextoValidacion = useMemo(() => ({
    evidencias: Object.fromEntries(Object.entries(evidencias).map(([k, v]) => [k, v.map((e) => ({ tipo: e.tipo, id: e.id }))])),
    sistema: contexto?.sistema, iniciadoAt, hoy: new Date(),
    resolutor: (campo: Campo) => (campo.fuente_opciones?.origen === 'catalogo' && opciones[campo.clave] ? opciones[campo.clave]!.opciones.map((o) => o.valor) : null),
  }), [evidencias, contexto?.sistema, iniciadoAt, opciones])
  const { salida, errores } = useMemo(() => validar(esquema, respuestas, ctx, true), [esquema, respuestas, ctx])
  const erroresPorCampo = useMemo(() => Object.fromEntries(errores.map((e) => [e.campo, e.mensaje])), [errores])
  const anteriores = useRef(respuestas)

  // Cascada: al cambiar el padre se limpia el valor del hijo.
  useEffect(() => {
    const cambios: Record<string, unknown> = {}
    for (const campo of camposDe(esquema)) {
      const f = campo.fuente_opciones
      if (f?.origen === 'catalogo' && f.campo_padre && anteriores.current[f.campo_padre] !== respuestas[f.campo_padre] && respuestas[campo.clave] !== undefined && respuestas[campo.clave] !== null) {
        cambios[campo.clave] = null
      }
    }
    anteriores.current = respuestas
    if (Object.keys(cambios).length) onChange({ ...respuestas, ...cambios })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [respuestas])

  const cambiar = (clave: string, v: unknown) => onChange({ ...respuestas, [clave]: v })

  return (
    <div className="space-y-8">
      {esquema.secciones.map((seccion) => {
        const campos = seccion.campos.filter((c) => visibles.has(c.clave))
        if (campos.length === 0) return null
        return (
          <section key={seccion.clave} aria-labelledby={`sec-${seccion.clave}`} className="space-y-5">
            <header>
              <h2 id={`sec-${seccion.clave}`} className="text-lg font-semibold text-slate-900">{seccion.titulo}</h2>
              {seccion.descripcion && <p className="text-sm text-slate-600">{seccion.descripcion}</p>}
            </header>
            {campos.map((campo) => {
              const error = mostrarErrores ? erroresPorCampo[campo.clave] : undefined
              const props: PropsCampo = { campo, valor: respuestas[campo.clave], onChange: (v) => cambiar(campo.clave, v), opciones: opciones[campo.clave]?.opciones, aviso: opciones[campo.clave]?.aviso, soloLectura, calculado: TIPOS_CALCULADOS.has(campo.tipo) ? salida[campo.clave] : undefined }
              const Evid = EVIDENCIA[campo.tipo as keyof typeof EVIDENCIA]
              return (
                <div key={campo.clave} data-testid={`campo-${campo.clave}`} className={`rounded-lg ${error ? 'ring-2 ring-red-300 ring-offset-4' : ''}`}>
                  {campo.tipo !== 'etiqueta_info' && (
                    <label htmlFor={campo.clave} className="mb-1 block text-sm font-medium text-slate-800">
                      {campo.etiqueta}{campo.obligatorio && <span className="text-red-600"> *</span>}
                    </label>
                  )}
                  {campo.ayuda && <p className="mb-1 text-xs text-slate-500">{campo.ayuda}</p>}
                  {Evid
                    ? <Evid {...props} respuestaId={respuestaId} evidencias={evidencias[campo.clave] ?? []} onEvidencias={(l) => onEvidencias?.(campo.clave, l)} calidadDefaults={calidadDefaults} todas={evidencias} />
                    : (COMPONENTES[campo.tipo] ?? Texto)(props)}
                  {error && <p className="mt-1 text-xs text-red-700" role="alert">{error}</p>}
                </div>
              )
            })}
          </section>
        )
      })}
    </div>
  )
}

export function erroresDe(esquema: EsquemaFormulario, respuestas: Record<string, unknown>, ctx: ContextoValidacion): ErrorValidacion[] {
  return validar(esquema, respuestas, ctx, true).errores
}
