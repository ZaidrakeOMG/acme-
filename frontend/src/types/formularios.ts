/**
 * Contrato del esquema JSON de formularios (§4.3, §6.8.3c). Espejo exacto de backend/schemas/formularios.py.
 */
import type { Rol } from './api'

export const TIPOS_CAMPO = [
  'si_no', 'opcion_multiple', 'texto', 'texto_amplio', 'fotografia', 'firma', 'dibujo', 'radio', 'boton_grupo',
  'lista_desplegable', 'seleccion_multiple', 'concatenacion', 'archivo', 'escaner', 'etiqueta_info', 'audio',
  'fecha_hora', 'sello_fecha_hora', 'matematicas_tiempo', 'slider', 'encuesta_satisfaccion', 'geolocalizacion',
] as const
export type TipoCampo = (typeof TIPOS_CAMPO)[number]

export const TIPOS_CON_DEFECTO = new Set<TipoCampo>(['si_no', 'radio', 'boton_grupo', 'lista_desplegable', 'opcion_multiple', 'slider', 'fecha_hora', 'texto', 'texto_amplio', 'seleccion_multiple'])
export const TIPOS_CON_OPCIONES = new Set<TipoCampo>(['opcion_multiple', 'radio', 'boton_grupo', 'lista_desplegable', 'seleccion_multiple'])
export const TIPOS_EVIDENCIA = new Set<TipoCampo>(['fotografia', 'firma', 'dibujo', 'archivo', 'audio'])
export const TIPOS_CALCULADOS = new Set<TipoCampo>(['concatenacion', 'matematicas_tiempo', 'sello_fecha_hora'])
export const TIPOS_SIN_DATO = new Set<TipoCampo>(['etiqueta_info'])

export const CATALOGOS_SISTEMA = ['equipos_tenant', 'unidades_negocio', 'tecnicos_prestador', 'tipos_falla', 'tipos_equipo', 'familias_equipo', 'materiales', 'proveedores_externos', 'catalogo_personalizado'] as const
export type CatalogoSistema = (typeof CATALOGOS_SISTEMA)[number]

export type Operador = 'igual' | 'distinto' | 'contiene' | 'vacio' | 'no_vacio' | 'en_rango' | 'opcion_seleccionada'

export interface Condicion {
  campo_origen: string
  operador: Operador
  valor?: unknown
  accion: 'mostrar' | 'ocultar'
}

export interface Opcion {
  valor: string
  etiqueta: string
  color?: string | null
  grupo?: string | null
  descripcion?: string | null
}

export interface FuenteFija {
  origen: 'fija'
  opciones: Opcion[]
}

export interface FuenteCatalogo {
  origen: 'catalogo'
  catalogo: CatalogoSistema
  catalogo_personalizado_id?: string | null
  filtro_contexto: boolean
  campo_padre?: string | null
}

export type FuenteOpciones = FuenteFija | FuenteCatalogo

// ------------------------------------------------------------ config por tipo

export interface ConfigSiNo { etiqueta_si: string; etiqueta_no: string; modo_defecto: 'sin_defecto' | 'con_defecto' }
export interface ConfigOpcionMultiple { min_selecciones: number; max_selecciones: number | null }
export interface ConfigTexto { longitud_min: number; longitud_max: number; formato: 'libre' | 'numeros' | 'letras' | 'regex'; regex: string | null; mensaje_formato: string | null }
export interface ConfigTextoAmplio extends ConfigTexto { lineas_visibles: number }
export interface CalidadFoto { tamano_minimo_kb: number | null; resolucion_minima_ancho: number | null; resolucion_minima_alto: number | null; compresion_maxima_pct: number | null }
export interface ConfigFotografia { origen: 'camara' | 'camara_galeria'; calidad: CalidadFoto; cantidad_min: number; cantidad_max: number; etiquetas_secuencia: string[]; permitir_anotacion: boolean; vista_previa_confirmacion: boolean }
export interface ConfigFirma { pantalla_completa: boolean; texto_conformidad: string | null }
export interface ConfigDibujo { imagen_referencia: { tipo: 'ninguna' | 'url' | 'campo_fotografia'; valor: string | null }; permitir_color: boolean; permitir_grosor: boolean }
export interface ConfigRadio { disposicion: 'vertical' | 'horizontal' }
export interface ConfigBotonGrupo { tamano: 'normal' | 'grande' }
export interface ConfigListaDesplegable { busqueda: boolean; seleccion: 'unica' | 'multiple'; disponible_offline: boolean }
export interface PlantillaCombinacion { nombre: string; valores: string[]; cantidades: Record<string, number> }
export interface ConfigSeleccionMultiple extends ConfigOpcionMultiple { contador_por_opcion: boolean; contador_min: number; contador_max: number | null; grupos_colapsables: boolean; plantillas_combinaciones: PlantillaCombinacion[] }
export interface ConfigConcatenacion { partes: { tipo: 'texto' | 'campo'; valor: string }[]; separador: string; mayusculas: boolean }
export interface ConfigArchivo { tipos_permitidos: ('pdf' | 'imagen' | 'hoja_calculo' | 'documento' | 'cualquiera')[]; tamano_maximo_mb: number; cantidad_max: number; permitir_anotacion_imagen: boolean }
export interface ConfigEscaner { formatos: ('qr' | 'ean' | 'code128' | 'datamatrix')[]; precargar_equipo: boolean; permitir_captura_manual: boolean }
export interface ConfigEtiquetaInfo { contenido: string; icono: 'ninguno' | 'info' | 'advertencia' | 'peligro'; enlace: { url: string; texto: string } | null }
export interface ConfigAudio { duracion_maxima_seg: number; transcripcion: boolean }
export interface ConfigFechaHora { modo: 'fecha' | 'hora' | 'ambos'; fecha_minima: string | null; fecha_maxima: string | null; intervalo_minutos: number; defecto_hoy_mas_dias: number | null; vinculo: { rol: 'inicio' | 'fin'; campo_par: string } | null }
export interface ConfigSelloFechaHora { trigger: 'al_abrir' | 'al_llegar_seccion' | 'al_enviar' | 'por_condicion' }
export interface FuenteTiempo { origen: 'campo' | 'sistema'; valor: string }
export interface ConfigMatematicasTiempo { inicio: FuenteTiempo; fin: FuenteTiempo; unidad: 'minutos' | 'horas' | 'dias' | 'compuesto' }
export interface ConfigSlider { minimo: number; maximo: number; incremento: number; etiqueta_min: string | null; etiqueta_max: string | null; modo_rango: boolean }
export interface ConfigEncuesta { modalidad: 'estrellas' | 'numerica' | 'emojis'; escala_max: number; etiqueta_min: string | null; etiqueta_max: string | null; umbral_bajo: number | null }
export interface ConfigGeolocalizacion { radio_ajuste_m: number; geofencing_radio_m: number; alertar_fuera_un: boolean }

export type ConfigCampo = Partial<ConfigSiNo & ConfigOpcionMultiple & ConfigTextoAmplio & ConfigFotografia & ConfigFirma & ConfigDibujo & ConfigRadio & ConfigBotonGrupo & ConfigListaDesplegable & ConfigSeleccionMultiple & ConfigConcatenacion & ConfigArchivo & ConfigEscaner & ConfigEtiquetaInfo & ConfigAudio & ConfigFechaHora & ConfigSelloFechaHora & ConfigMatematicasTiempo & ConfigSlider & ConfigEncuesta & ConfigGeolocalizacion>

/** Config por defecto de cada tipo (mismos valores que los modelos Pydantic). */
export const CONFIG_DEFECTO: Record<TipoCampo, ConfigCampo> = {
  si_no: { etiqueta_si: 'Sí', etiqueta_no: 'No', modo_defecto: 'sin_defecto' },
  opcion_multiple: { min_selecciones: 0, max_selecciones: null },
  texto: { longitud_min: 0, longitud_max: 500, formato: 'libre', regex: null, mensaje_formato: null },
  texto_amplio: { lineas_visibles: 4, longitud_min: 0, longitud_max: 5000, formato: 'libre', regex: null, mensaje_formato: null },
  fotografia: { origen: 'camara', calidad: { tamano_minimo_kb: null, resolucion_minima_ancho: null, resolucion_minima_alto: null, compresion_maxima_pct: null }, cantidad_min: 1, cantidad_max: 5, etiquetas_secuencia: [], permitir_anotacion: true, vista_previa_confirmacion: true },
  firma: { pantalla_completa: true, texto_conformidad: null },
  dibujo: { imagen_referencia: { tipo: 'ninguna', valor: null }, permitir_color: true, permitir_grosor: true },
  radio: { disposicion: 'vertical' },
  boton_grupo: { tamano: 'grande' },
  lista_desplegable: { busqueda: true, seleccion: 'unica', disponible_offline: true },
  seleccion_multiple: { min_selecciones: 0, max_selecciones: null, contador_por_opcion: false, contador_min: 1, contador_max: null, grupos_colapsables: false, plantillas_combinaciones: [] },
  concatenacion: { partes: [{ tipo: 'texto', valor: '' }], separador: '', mayusculas: false },
  archivo: { tipos_permitidos: ['pdf', 'imagen'], tamano_maximo_mb: 10, cantidad_max: 3, permitir_anotacion_imagen: true },
  escaner: { formatos: ['qr', 'ean', 'code128', 'datamatrix'], precargar_equipo: true, permitir_captura_manual: false },
  etiqueta_info: { contenido: '', icono: 'ninguno', enlace: null },
  audio: { duracion_maxima_seg: 120, transcripcion: true },
  fecha_hora: { modo: 'ambos', fecha_minima: null, fecha_maxima: null, intervalo_minutos: 1, defecto_hoy_mas_dias: null, vinculo: null },
  sello_fecha_hora: { trigger: 'al_enviar' },
  matematicas_tiempo: { inicio: { origen: 'sistema', valor: 'captura_folio' }, fin: { origen: 'sistema', valor: 'ahora' }, unidad: 'compuesto' },
  slider: { minimo: 0, maximo: 10, incremento: 1, etiqueta_min: null, etiqueta_max: null, modo_rango: false },
  encuesta_satisfaccion: { modalidad: 'estrellas', escala_max: 5, etiqueta_min: null, etiqueta_max: null, umbral_bajo: null },
  geolocalizacion: { radio_ajuste_m: 50, geofencing_radio_m: 300, alertar_fuera_un: true },
}

export const NOMBRE_TIPO: Record<TipoCampo, string> = {
  si_no: 'Sí / No', opcion_multiple: 'Opción múltiple', texto: 'Texto libre', texto_amplio: 'Campo amplio de texto', fotografia: 'Fotografía',
  firma: 'Firma', dibujo: 'Dibujo en pantalla', radio: 'Botón de radio', boton_grupo: 'Botón de grupo (color)', lista_desplegable: 'Lista desplegable',
  seleccion_multiple: 'Selección múltiple', concatenacion: 'Concatenación de secuencias', archivo: 'Carga de archivo', escaner: 'Escáner código de barras / QR',
  etiqueta_info: 'Etiqueta de información', audio: 'Grabación de audio', fecha_hora: 'Selector de fecha y hora', sello_fecha_hora: 'Sello de fecha y hora',
  matematicas_tiempo: 'Matemáticas basadas en tiempo', slider: 'Slider numérico', encuesta_satisfaccion: 'Encuesta de satisfacción', geolocalizacion: 'Geolocalización automática',
}

export interface Campo {
  clave: string
  tipo: TipoCampo
  etiqueta: string
  ayuda?: string | null
  obligatorio: boolean
  valor_defecto?: unknown
  config: ConfigCampo
  condiciones: Condicion[]
  fuente_opciones?: FuenteOpciones | null
}

export interface Seccion {
  clave: string
  titulo: string
  descripcion?: string | null
  campos: Campo[]
}

export interface EsquemaFormulario {
  version_contrato: number
  secciones: Seccion[]
}

export const camposDe = (e: EsquemaFormulario): Campo[] => e.secciones.flatMap((s) => s.campos)
export const campoDe = (e: EsquemaFormulario, clave: string): Campo | undefined => camposDe(e).find((c) => c.clave === clave)

// ------------------------------------------------------------------- API

export type TipoFormulario = 'captura_operador' | 'atencion_tecnico' | 'preventivo' | 'trabajo_especial' | 'encuesta' | 'libre'
export type EstadoFormulario = 'borrador' | 'publicado' | 'archivado'

export interface Formulario {
  id: string
  prestador_id: string | null
  tenant_id: string | null
  nombre: string
  descripcion: string
  tipo: TipoFormulario
  rol_destino: Rol[]
  estado: EstadoFormulario
  version_publicada_id: string | null
  es_plantilla_base: boolean
  clonado_de_id: string | null
  version_actual: number
  numero_version_publicada: number | null
  esquema_json: EsquemaFormulario
  puede_editar: boolean
  created_at: string
  updated_at: string
}

export interface VersionFormulario {
  id: string
  formulario_id: string
  numero_version: number
  esquema_json: EsquemaFormulario
  publicada_at: string | null
  notas_version: string
}

export interface OpcionCatalogo {
  valor: string
  etiqueta: string
  descripcion?: string | null
  padre?: string | null
  extra: Record<string, unknown>
}

export interface Respuesta {
  id: string
  formulario_id: string
  version_id: string
  numero_version: number
  tenant_id: string | null
  un_id: string | null
  equipo_id: string | null
  origen: string
  referencia_id: string | null
  respuestas_json: Record<string, unknown>
  estado: 'en_progreso' | 'enviado'
  iniciado_at: string
  enviado_at: string | null
  inmutable: boolean
  nombre_formulario: string | null
  errores: { campo: string; mensaje: string }[]
}

export interface Evidencia {
  id: string
  created_at: string
  respuesta_id: string
  campo_clave: string
  tipo: 'foto' | 'firma' | 'dibujo' | 'archivo' | 'audio'
  nombre_original: string
  mime: string
  bytes: number
  ancho_px: number | null
  alto_px: number | null
  etiqueta: string | null
  orden: number
  hash_sha256: string
  anotaciones_json: Record<string, unknown>
  calidad: Record<string, unknown>
}

export interface ContextoRespuesta {
  tenant_id?: string | null
  un_id?: string | null
  equipo_id?: string | null
  sistema?: Record<string, string>
}

export interface CatalogoPersonalizado {
  id: string
  prestador_id: string
  tenant_id: string | null
  nombre: string
  clave: string
  opciones: { id: string; valor: string; etiqueta: string; orden: number; activa: boolean; padre_opcion_id: string | null }[]
}
