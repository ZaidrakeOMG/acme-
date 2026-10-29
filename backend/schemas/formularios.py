"""Contrato del esquema JSON de formularios (§4.3, §6.8.3c). Espejo exacto en frontend/src/types/formularios.ts.

Un formulario es `secciones[] → campos[]`. Cada campo tiene `clave`, `tipo` (uno de los 22), `config` específica del tipo,
`condiciones[]` (lógica condicional) y, en los tipos de selección, `fuente_opciones` (fija o catálogo del sistema).
"""
from __future__ import annotations

import re
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from models.base import Rol
from schemas.comun import ConVersionSalida, Modelo

VERSION_CONTRATO = 1

TIPOS_CAMPO = (
    "si_no", "opcion_multiple", "texto", "texto_amplio", "fotografia", "firma", "dibujo", "radio", "boton_grupo",
    "lista_desplegable", "seleccion_multiple", "concatenacion", "archivo", "escaner", "etiqueta_info", "audio",
    "fecha_hora", "sello_fecha_hora", "matematicas_tiempo", "slider", "encuesta_satisfaccion", "geolocalizacion",
)
TipoCampo = Literal[
    "si_no", "opcion_multiple", "texto", "texto_amplio", "fotografia", "firma", "dibujo", "radio", "boton_grupo",
    "lista_desplegable", "seleccion_multiple", "concatenacion", "archivo", "escaner", "etiqueta_info", "audio",
    "fecha_hora", "sello_fecha_hora", "matematicas_tiempo", "slider", "encuesta_satisfaccion", "geolocalizacion",
]
# §4.3 "valor por defecto configurable": solo estos tipos lo admiten (texto/texto_amplio como sugerido preescrito).
TIPOS_CON_DEFECTO = {"si_no", "radio", "boton_grupo", "lista_desplegable", "opcion_multiple", "slider", "fecha_hora",
                     "texto", "texto_amplio", "seleccion_multiple"}
TIPOS_CON_OPCIONES = {"opcion_multiple", "radio", "boton_grupo", "lista_desplegable", "seleccion_multiple"}
TIPOS_EVIDENCIA = {"fotografia", "firma", "dibujo", "archivo", "audio"}
# Tipos calculados por el servidor: el valor del cliente se descarta.
TIPOS_CALCULADOS = {"concatenacion", "matematicas_tiempo", "sello_fecha_hora"}
TIPOS_SIN_DATO = {"etiqueta_info"}

CATALOGOS_SISTEMA = ("equipos_tenant", "unidades_negocio", "tecnicos_prestador", "tipos_falla", "tipos_equipo",
                     "familias_equipo", "materiales", "proveedores_externos", "catalogo_personalizado")
CatalogoSistema = Literal["equipos_tenant", "unidades_negocio", "tecnicos_prestador", "tipos_falla", "tipos_equipo",
                          "familias_equipo", "materiales", "proveedores_externos", "catalogo_personalizado"]

Operador = Literal["igual", "distinto", "contiene", "vacio", "no_vacio", "en_rango", "opcion_seleccionada"]
_CLAVE = re.compile(r"^[a-z][a-z0-9_]{0,59}$")


class Condicion(BaseModel):
    campo_origen: str
    operador: Operador
    valor: Any = None
    accion: Literal["mostrar", "ocultar"] = "mostrar"

    @model_validator(mode="after")
    def _valor_requerido(self) -> Condicion:
        if self.operador in ("igual", "distinto", "contiene", "opcion_seleccionada") and self.valor is None:
            raise ValueError(f"El operador {self.operador} requiere valor")
        if self.operador == "en_rango":
            if not (isinstance(self.valor, (list, tuple)) and len(self.valor) == 2):
                raise ValueError("en_rango requiere valor [minimo, maximo]")
        return self


class Opcion(BaseModel):
    valor: str = Field(min_length=1, max_length=120)
    etiqueta: str = Field(min_length=1, max_length=200)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    grupo: str | None = Field(default=None, max_length=80, description="Grupo colapsable (seleccion_multiple)")
    descripcion: str | None = Field(default=None, max_length=300)


class FuenteFija(BaseModel):
    origen: Literal["fija"] = "fija"
    opciones: list[Opcion] = Field(min_length=1, max_length=500)

    @field_validator("opciones")
    @classmethod
    def _unicas(cls, v: list[Opcion]) -> list[Opcion]:
        valores = [o.valor for o in v]
        if len(set(valores)) != len(valores):
            raise ValueError("Los valores de las opciones deben ser únicos")
        return v


class FuenteCatalogo(BaseModel):
    origen: Literal["catalogo"] = "catalogo"
    catalogo: CatalogoSistema
    catalogo_personalizado_id: UUID | None = None
    filtro_contexto: bool = Field(default=True, description="Filtrar por el contexto del folio activo (un_id, tenant_id, equipo_id)")
    campo_padre: str | None = Field(default=None, description="Cascada §6.8.3c: campo cuyo valor filtra este catálogo")

    @model_validator(mode="after")
    def _personalizado(self) -> FuenteCatalogo:
        if self.catalogo == "catalogo_personalizado" and self.catalogo_personalizado_id is None:
            raise ValueError("catalogo_personalizado requiere catalogo_personalizado_id")
        return self


FuenteOpciones = FuenteFija | FuenteCatalogo


# ------------------------------------------------------------ config por tipo (§4.3)

class ConfigSiNo(BaseModel):
    etiqueta_si: str = Field(default="Sí", max_length=40)
    etiqueta_no: str = Field(default="No", max_length=40)
    modo_defecto: Literal["sin_defecto", "con_defecto"] = "sin_defecto"


class ConfigOpcionMultiple(BaseModel):
    min_selecciones: int = Field(default=0, ge=0)
    max_selecciones: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _rango(self) -> ConfigOpcionMultiple:
        if self.max_selecciones is not None and self.max_selecciones < self.min_selecciones:
            raise ValueError("max_selecciones debe ser mayor o igual a min_selecciones")
        return self


class ConfigTexto(BaseModel):
    longitud_min: int = Field(default=0, ge=0)
    longitud_max: int = Field(default=500, ge=1, le=20000)
    formato: Literal["libre", "numeros", "letras", "regex"] = "libre"
    regex: str | None = Field(default=None, max_length=300)
    mensaje_formato: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _regex(self) -> ConfigTexto:
        if self.longitud_max < self.longitud_min:
            raise ValueError("longitud_max debe ser mayor o igual a longitud_min")
        if self.formato == "regex":
            if not self.regex:
                raise ValueError("formato regex requiere regex")
            try:
                re.compile(self.regex)
            except re.error as e:
                raise ValueError(f"Expresión regular inválida: {e}")
        return self


class ConfigTextoAmplio(ConfigTexto):
    lineas_visibles: int = Field(default=4, ge=2, le=30)
    longitud_max: int = Field(default=5000, ge=1, le=50000)


class CalidadFoto(BaseModel):
    tamano_minimo_kb: int | None = Field(default=None, ge=0)
    resolucion_minima_ancho: int | None = Field(default=None, ge=1)
    resolucion_minima_alto: int | None = Field(default=None, ge=1)
    compresion_maxima_pct: int | None = Field(default=None, ge=0, le=100)


class ConfigFotografia(BaseModel):
    origen: Literal["camara", "camara_galeria"] = "camara"
    calidad: CalidadFoto = Field(default_factory=CalidadFoto, description="Vacío = defaults globales del superadmin")
    cantidad_min: int = Field(default=1, ge=0, le=20)
    cantidad_max: int = Field(default=5, ge=1, le=20)
    etiquetas_secuencia: list[str] = Field(default_factory=list, max_length=20, description="Nombre y orden de cada foto")
    permitir_anotacion: bool = True
    vista_previa_confirmacion: bool = True

    @model_validator(mode="after")
    def _rango(self) -> ConfigFotografia:
        if self.cantidad_max < self.cantidad_min:
            raise ValueError("cantidad_max debe ser mayor o igual a cantidad_min")
        if self.etiquetas_secuencia and len(self.etiquetas_secuencia) < self.cantidad_min:
            raise ValueError("Las etiquetas en secuencia deben cubrir al menos cantidad_min fotos")
        return self


class ConfigFirma(BaseModel):
    pantalla_completa: bool = True
    texto_conformidad: str | None = Field(default=None, max_length=300)


class ImagenReferencia(BaseModel):
    tipo: Literal["ninguna", "url", "campo_fotografia"] = "ninguna"
    valor: str | None = Field(default=None, max_length=500, description="URL/clave de archivo o clave del campo fotografía")

    @model_validator(mode="after")
    def _valor(self) -> ImagenReferencia:
        if self.tipo != "ninguna" and not self.valor:
            raise ValueError("La imagen de referencia requiere valor")
        return self


class ConfigDibujo(BaseModel):
    imagen_referencia: ImagenReferencia = Field(default_factory=ImagenReferencia)
    permitir_color: bool = True
    permitir_grosor: bool = True


class ConfigRadio(BaseModel):
    disposicion: Literal["vertical", "horizontal"] = "vertical"


class ConfigBotonGrupo(BaseModel):
    tamano: Literal["normal", "grande"] = "grande"


class ConfigListaDesplegable(BaseModel):
    busqueda: bool = True
    seleccion: Literal["unica", "multiple"] = "unica"
    disponible_offline: bool = True


class PlantillaCombinacion(BaseModel):
    nombre: str = Field(max_length=80)
    valores: list[str] = Field(min_length=1)
    cantidades: dict[str, int] = Field(default_factory=dict)


class ConfigSeleccionMultiple(ConfigOpcionMultiple):
    contador_por_opcion: bool = False
    contador_min: int = Field(default=1, ge=0)
    contador_max: int | None = Field(default=None, ge=1)
    grupos_colapsables: bool = False
    plantillas_combinaciones: list[PlantillaCombinacion] = Field(default_factory=list, max_length=20)


class ParteConcatenacion(BaseModel):
    tipo: Literal["texto", "campo"]
    valor: str = Field(max_length=200)


class ConfigConcatenacion(BaseModel):
    partes: list[ParteConcatenacion] = Field(min_length=1, max_length=30)
    separador: str = Field(default="", max_length=10)
    mayusculas: bool = False


class ConfigArchivo(BaseModel):
    tipos_permitidos: list[Literal["pdf", "imagen", "hoja_calculo", "documento", "cualquiera"]] = Field(default_factory=lambda: ["pdf", "imagen"])
    tamano_maximo_mb: int = Field(default=10, ge=1, le=100)
    cantidad_max: int = Field(default=3, ge=1, le=20)
    permitir_anotacion_imagen: bool = True


class ConfigEscaner(BaseModel):
    formatos: list[Literal["qr", "ean", "code128", "datamatrix"]] = Field(default_factory=lambda: ["qr", "ean", "code128", "datamatrix"], min_length=1)
    precargar_equipo: bool = Field(default=True, description="Si el código corresponde a un equipo, precarga su contexto")
    permitir_captura_manual: bool = False


class EnlaceInfo(BaseModel):
    url: str = Field(max_length=500)
    texto: str = Field(default="Ver documento", max_length=120)


class ConfigEtiquetaInfo(BaseModel):
    contenido: str = Field(max_length=4000, description="Texto con formato enriquecido simple (**negritas**, listas con -)")
    icono: Literal["ninguno", "info", "advertencia", "peligro"] = "ninguno"
    enlace: EnlaceInfo | None = None


class ConfigAudio(BaseModel):
    duracion_maxima_seg: int = Field(default=120, ge=5, le=900)
    transcripcion: bool = True


class VinculoFechas(BaseModel):
    rol: Literal["inicio", "fin"]
    campo_par: str


class ConfigFechaHora(BaseModel):
    modo: Literal["fecha", "hora", "ambos"] = "ambos"
    fecha_minima: str | None = Field(default=None, description="ISO o 'hoy' / 'hoy+N' / 'hoy-N'")
    fecha_maxima: str | None = None
    intervalo_minutos: int = Field(default=1, ge=1, le=60)
    defecto_hoy_mas_dias: int | None = Field(default=None, ge=-365, le=365)
    vinculo: VinculoFechas | None = None


class ConfigSelloFechaHora(BaseModel):
    trigger: Literal["al_abrir", "al_llegar_seccion", "al_enviar", "por_condicion"] = "al_enviar"


class FuenteTiempo(BaseModel):
    origen: Literal["campo", "sistema"]
    valor: str = Field(description="Clave del campo fecha_hora/sello, o clave de sistema: captura_folio, asignacion, autorizacion, fecha_programada, ahora")


class ConfigMatematicasTiempo(BaseModel):
    inicio: FuenteTiempo
    fin: FuenteTiempo
    unidad: Literal["minutos", "horas", "dias", "compuesto"] = "compuesto"


class ConfigSlider(BaseModel):
    minimo: float = 0
    maximo: float = 10
    incremento: float = Field(default=1, gt=0)
    etiqueta_min: str | None = Field(default=None, max_length=40)
    etiqueta_max: str | None = Field(default=None, max_length=40)
    modo_rango: bool = False

    @model_validator(mode="after")
    def _rango(self) -> ConfigSlider:
        if self.maximo <= self.minimo:
            raise ValueError("maximo debe ser mayor que minimo")
        return self


class ConfigEncuesta(BaseModel):
    modalidad: Literal["estrellas", "numerica", "emojis"] = "estrellas"
    escala_max: int = Field(default=5, ge=3, le=10)
    etiqueta_min: str | None = Field(default=None, max_length=40)
    etiqueta_max: str | None = Field(default=None, max_length=40)
    umbral_bajo: int | None = Field(default=None, ge=1, description="Calificación ≤ umbral dispara condiciones de 'rango bajo'")

    @model_validator(mode="after")
    def _escala(self) -> ConfigEncuesta:
        permitidas = {"estrellas": {5}, "numerica": {10}, "emojis": {3, 5}}[self.modalidad]
        if self.escala_max not in permitidas:
            raise ValueError(f"escala_max para {self.modalidad} debe ser {sorted(permitidas)}")
        return self


class ConfigGeolocalizacion(BaseModel):
    radio_ajuste_m: int = Field(default=50, ge=0, le=2000, description="Ajuste manual permitido dentro de este radio")
    geofencing_radio_m: int = Field(default=300, ge=10, le=20000, description="Distancia máxima a la UN sin alerta")
    alertar_fuera_un: bool = True


CONFIG_POR_TIPO: dict[str, type[BaseModel]] = {
    "si_no": ConfigSiNo, "opcion_multiple": ConfigOpcionMultiple, "texto": ConfigTexto, "texto_amplio": ConfigTextoAmplio,
    "fotografia": ConfigFotografia, "firma": ConfigFirma, "dibujo": ConfigDibujo, "radio": ConfigRadio,
    "boton_grupo": ConfigBotonGrupo, "lista_desplegable": ConfigListaDesplegable, "seleccion_multiple": ConfigSeleccionMultiple,
    "concatenacion": ConfigConcatenacion, "archivo": ConfigArchivo, "escaner": ConfigEscaner, "etiqueta_info": ConfigEtiquetaInfo,
    "audio": ConfigAudio, "fecha_hora": ConfigFechaHora, "sello_fecha_hora": ConfigSelloFechaHora,
    "matematicas_tiempo": ConfigMatematicasTiempo, "slider": ConfigSlider, "encuesta_satisfaccion": ConfigEncuesta,
    "geolocalizacion": ConfigGeolocalizacion,
}


class HallazgoMapeo(BaseModel):
    """P07 §7.3: el campo genera un hallazgo al enviar el formulario de atención. Mapeo de qué campos alimentan la descripción
    (por defecto el propio campo), la urgencia (texto baja/media/alta/critica o slider 1–10) y la foto; `condicion_campo` /
    `condicion_valor` limitan la generación (p. ej. requiere_correctivo == "si")."""
    campo_descripcion: str | None = Field(default=None, pattern=_CLAVE.pattern)
    campo_urgencia: str | None = Field(default=None, pattern=_CLAVE.pattern)
    urgencia_fija: Literal["baja", "media", "alta", "critica"] | None = None
    campo_foto: str | None = Field(default=None, pattern=_CLAVE.pattern)
    condicion_campo: str | None = Field(default=None, pattern=_CLAVE.pattern)
    condicion_valor: Any = None


class ActivoMapeo(BaseModel):
    """P08 §6.10.7: un campo `si_no` o `radio` del formulario de captura o de atención clasifica el folio como instalación de activo
    cuando responde `valor_afirmativo` (por defecto «si»). Los campos opcionales alimentan el alta automática del equipo al cerrar."""
    valor_afirmativo: Any = "si"
    campo_tipo_equipo: str | None = Field(default=None, pattern=_CLAVE.pattern)
    campo_marca: str | None = Field(default=None, pattern=_CLAVE.pattern)
    campo_modelo: str | None = Field(default=None, pattern=_CLAVE.pattern)
    campo_serie: str | None = Field(default=None, pattern=_CLAVE.pattern)
    campo_valor_reposicion: str | None = Field(default=None, pattern=_CLAVE.pattern)
    campo_nombre: str | None = Field(default=None, pattern=_CLAVE.pattern)


class Campo(BaseModel):
    clave: str = Field(pattern=_CLAVE.pattern, description="Única en el formulario, sin acentos")
    genera_hallazgo: HallazgoMapeo | None = Field(default=None, description="P07: crea un hallazgo para la minuta al enviar")
    clasifica_instalacion_activo: ActivoMapeo | None = Field(default=None, description="P08: clasifica el folio como instalación de activo (§6.10.7)")
    tipo: TipoCampo
    etiqueta: str = Field(min_length=1, max_length=200)
    ayuda: str | None = Field(default=None, max_length=500)
    obligatorio: bool = False
    valor_defecto: Any = None
    config: dict[str, Any] = Field(default_factory=dict)
    condiciones: list[Condicion] = Field(default_factory=list, max_length=20)
    fuente_opciones: FuenteOpciones | None = None

    @model_validator(mode="after")
    def _por_tipo(self) -> Campo:
        modelo = CONFIG_POR_TIPO[self.tipo]
        self.config = modelo.model_validate(self.config).model_dump()
        if self.tipo in TIPOS_CON_OPCIONES and self.fuente_opciones is None:
            raise ValueError(f"El campo {self.clave} ({self.tipo}) requiere fuente_opciones")
        if self.tipo not in TIPOS_CON_OPCIONES and self.fuente_opciones is not None:
            raise ValueError(f"El campo {self.clave} ({self.tipo}) no admite fuente_opciones")
        if self.tipo == "boton_grupo":
            if not isinstance(self.fuente_opciones, FuenteFija) or not 2 <= len(self.fuente_opciones.opciones) <= 5:
                raise ValueError("boton_grupo requiere entre 2 y 5 opciones fijas")
            if any(o.color is None for o in self.fuente_opciones.opciones):
                raise ValueError("Cada opción de boton_grupo requiere color")
        if self.valor_defecto is not None and self.tipo not in TIPOS_CON_DEFECTO:
            raise ValueError(f"El tipo {self.tipo} no admite valor por defecto (§4.3)")
        if self.tipo == "si_no" and self.config["modo_defecto"] == "con_defecto" and not isinstance(self.valor_defecto, bool):
            raise ValueError("si_no con modo con_defecto requiere valor_defecto true/false")
        if self.tipo == "firma":
            self.obligatorio = True  # §4.3: campo obligatorio por definición
        if self.tipo in TIPOS_CALCULADOS | TIPOS_SIN_DATO:
            self.obligatorio = False
        return self


class Seccion(BaseModel):
    clave: str = Field(pattern=_CLAVE.pattern)
    titulo: str = Field(min_length=1, max_length=200)
    descripcion: str | None = Field(default=None, max_length=1000)
    campos: list[Campo] = Field(default_factory=list, max_length=200)


class EsquemaFormulario(BaseModel):
    version_contrato: int = VERSION_CONTRATO
    secciones: list[Seccion] = Field(min_length=1, max_length=50)

    @property
    def campos(self) -> list[Campo]:
        return [c for s in self.secciones for c in s.campos]

    def campo(self, clave: str) -> Campo | None:
        return next((c for c in self.campos if c.clave == clave), None)

    @model_validator(mode="after")
    def _referencias(self) -> EsquemaFormulario:
        claves = [c.clave for c in self.campos]
        if len(set(claves)) != len(claves):
            repetidas = sorted({k for k in claves if claves.count(k) > 1})
            raise ValueError(f"Claves de campo repetidas: {', '.join(repetidas)}")
        secciones = [s.clave for s in self.secciones]
        if len(set(secciones)) != len(secciones):
            raise ValueError("Claves de sección repetidas")
        existentes = set(claves)
        por_clave = {c.clave: c for c in self.campos}
        for c in self.campos:
            m = c.genera_hallazgo
            if m:
                for ref in (m.campo_descripcion, m.campo_urgencia, m.campo_foto, m.condicion_campo):
                    if ref and ref not in existentes:
                        raise ValueError(f"genera_hallazgo de {c.clave} apunta a un campo inexistente: {ref}")
            a = c.clasifica_instalacion_activo
            if a:
                if c.tipo not in ("si_no", "radio", "boton_grupo", "lista_desplegable"):
                    raise ValueError(f"clasifica_instalacion_activo solo aplica a campos si_no o radio ({c.clave} es {c.tipo})")
                for ref in (a.campo_tipo_equipo, a.campo_marca, a.campo_modelo, a.campo_serie, a.campo_valor_reposicion, a.campo_nombre):
                    if ref and ref not in existentes:
                        raise ValueError(f"clasifica_instalacion_activo de {c.clave} apunta a un campo inexistente: {ref}")
        for c in self.campos:
            for cond in c.condiciones:
                if cond.campo_origen not in existentes:
                    raise ValueError(f"Condición de {c.clave}: el campo origen {cond.campo_origen} no existe")
                if cond.campo_origen == c.clave:
                    raise ValueError(f"El campo {c.clave} no puede condicionarse a sí mismo")
            if isinstance(c.fuente_opciones, FuenteCatalogo) and c.fuente_opciones.campo_padre:
                if c.fuente_opciones.campo_padre not in existentes:
                    raise ValueError(f"Cascada de {c.clave}: el campo padre no existe")
            if c.tipo == "concatenacion":
                for p in c.config["partes"]:
                    if p["tipo"] == "campo" and p["valor"] not in existentes:
                        raise ValueError(f"Concatenación {c.clave}: el campo {p['valor']} no existe")
            if c.tipo == "matematicas_tiempo":
                for extremo in ("inicio", "fin"):
                    f = c.config[extremo]
                    if f["origen"] == "campo":
                        origen = por_clave.get(f["valor"])
                        if origen is None or origen.tipo not in ("fecha_hora", "sello_fecha_hora"):
                            raise ValueError(f"Matemáticas {c.clave}: {extremo} debe apuntar a un campo fecha_hora o sello")
            if c.tipo == "fecha_hora" and c.config.get("vinculo"):
                par = por_clave.get(c.config["vinculo"]["campo_par"])
                if par is None or par.tipo != "fecha_hora":
                    raise ValueError(f"Fecha {c.clave}: el campo par del vínculo debe ser fecha_hora")
            if c.tipo == "dibujo" and c.config["imagen_referencia"]["tipo"] == "campo_fotografia":
                ref = por_clave.get(c.config["imagen_referencia"]["valor"])
                if ref is None or ref.tipo != "fotografia":
                    raise ValueError(f"Dibujo {c.clave}: la imagen de referencia debe ser un campo fotografia")
        return self


# ------------------------------------------------------------------ API

TipoFormulario = Literal["captura_operador", "atencion_tecnico", "preventivo", "trabajo_especial", "encuesta", "libre"]
EstadoFormulario = Literal["borrador", "publicado", "archivado"]


class FormularioEntrada(BaseModel):
    nombre: str = Field(min_length=2, max_length=160)
    descripcion: str = Field(default="", max_length=1000)
    tipo: TipoFormulario = "libre"
    rol_destino: list[Rol] = Field(min_length=1)
    tenant_id: UUID | None = Field(default=None, description="Alcance específico de un cliente; null = global del prestador")
    prestador_id: UUID | None = Field(default=None, description="Solo superadmin; null = plantilla de plataforma")
    es_plantilla_base: bool = False
    esquema: EsquemaFormulario


class FormularioCambios(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=160)
    descripcion: str | None = Field(default=None, max_length=1000)
    tipo: TipoFormulario | None = None
    rol_destino: list[Rol] | None = Field(default=None, min_length=1)
    tenant_id: UUID | None = None
    esquema: EsquemaFormulario | None = None
    notas_version: str | None = Field(default=None, max_length=1000)


class PublicarEntrada(BaseModel):
    notas_version: str = Field(default="", max_length=1000)


class ClonarEntrada(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=160)
    tenant_id: UUID | None = None
    prestador_id: UUID | None = Field(default=None, description="Solo superadmin")


class VersionSalida(ConVersionSalida):
    formulario_id: UUID
    numero_version: int
    esquema_json: dict[str, Any]
    publicada_at: str | None = None
    publicada_por: UUID | None
    notas_version: str


class FormularioSalida(ConVersionSalida):
    prestador_id: UUID | None
    tenant_id: UUID | None
    nombre: str
    descripcion: str
    tipo: TipoFormulario
    rol_destino: list[str]
    estado: EstadoFormulario
    version_publicada_id: UUID | None
    es_plantilla_base: bool
    clonado_de_id: UUID | None
    version_actual: int = Field(description="Número de la versión más reciente (borrador o publicada)")
    numero_version_publicada: int | None = None
    esquema_json: dict[str, Any] = Field(description="Esquema de la versión más reciente")
    puede_editar: bool = False


class DiffVersiones(BaseModel):
    de: int
    a: int
    agregados: list[str]
    quitados: list[str]
    modificados: list[str]


class AsignacionEntrada(BaseModel):
    tenant_id: UUID | None = None
    tipo_folio: str | None = Field(default=None, max_length=40)
    tipo_equipo_id: UUID | None = None
    familia_equipo_id: UUID | None = None
    plan_mantenimiento_id: UUID | None = Field(default=None, description="FK diferida: la tabla llega en P06")
    activa: bool = True


class AsignacionSalida(ConVersionSalida):
    formulario_id: UUID
    prestador_id: UUID
    tenant_id: UUID | None
    tipo_folio: str | None
    tipo_equipo_id: UUID | None
    familia_equipo_id: UUID | None
    plan_mantenimiento_id: UUID | None
    prioridad: int
    activa: bool


class PermisoMesaEntrada(BaseModel):
    usuario_id: UUID
    puede_editar_publicado: bool = True


class PermisosMesaEntrada(BaseModel):
    permisos: list[PermisoMesaEntrada] = Field(max_length=100)


class PermisoMesaSalida(Modelo):
    usuario_id: UUID
    nombre: str
    puede_editar_publicado: bool


class OpcionPersonalizadaEntrada(BaseModel):
    valor: str = Field(min_length=1, max_length=120)
    etiqueta: str = Field(min_length=1, max_length=200)
    orden: int = 0
    activa: bool = True
    padre_valor: str | None = Field(default=None, description="Valor de la opción padre (cascada propia)")


class CatalogoPersonalizadoEntrada(BaseModel):
    nombre: str = Field(min_length=2, max_length=120)
    clave: str = Field(pattern=_CLAVE.pattern)
    tenant_id: UUID | None = None
    opciones: list[OpcionPersonalizadaEntrada] = Field(default_factory=list, max_length=2000)


class OpcionPersonalizadaSalida(Modelo):
    id: UUID
    valor: str
    etiqueta: str
    orden: int
    activa: bool
    padre_opcion_id: UUID | None


class CatalogoPersonalizadoSalida(ConVersionSalida):
    prestador_id: UUID
    tenant_id: UUID | None
    nombre: str
    clave: str
    activo: bool
    opciones: list[OpcionPersonalizadaSalida] = Field(default_factory=list)


class OpcionCatalogo(BaseModel):
    """Opción resuelta de un catálogo del sistema para el renderizador."""
    valor: str
    etiqueta: str
    descripcion: str | None = None
    padre: str | None = Field(default=None, description="Valor del padre en cascada (p. ej. familia del tipo de falla)")
    extra: dict[str, Any] = Field(default_factory=dict)


class OpcionesCatalogoSalida(BaseModel):
    catalogo: str
    opciones: list[OpcionCatalogo]
    aviso: str | None = Field(default=None, description="Catálogos sin datos hasta otro prompt")


OrigenRespuesta = Literal["folio_captura", "folio_atencion", "preventivo", "trabajo_especial", "encuesta", "independiente"]


class ContextoRespuesta(BaseModel):
    un_id: UUID | None = None
    equipo_id: UUID | None = None
    tenant_id: UUID | None = Field(default=None, description="Solo roles del prestador/plataforma; el tenant usa el suyo")
    sistema: dict[str, str] = Field(default_factory=dict, description="Timestamps de sistema para matematicas_tiempo (P04)")


class RespuestaEntrada(BaseModel):
    origen: OrigenRespuesta = "independiente"
    referencia_id: UUID | None = None
    contexto: ContextoRespuesta = Field(default_factory=ContextoRespuesta)
    respuestas: dict[str, Any] = Field(default_factory=dict)
    dispositivo: dict[str, Any] = Field(default_factory=dict)


class RespuestaParcial(BaseModel):
    respuestas: dict[str, Any]
    dispositivo: dict[str, Any] | None = None


class ErrorValidacion(BaseModel):
    campo: str
    mensaje: str


class RespuestaSalida(ConVersionSalida):
    formulario_id: UUID
    version_id: UUID
    numero_version: int
    tenant_id: UUID | None
    prestador_id: UUID | None
    un_id: UUID | None
    equipo_id: UUID | None
    origen: str
    referencia_id: UUID | None
    respuestas_json: dict[str, Any]
    respondido_por: UUID
    iniciado_at: str
    enviado_at: str | None
    estado: Literal["en_progreso", "enviado"]
    inmutable: bool
    nombre_formulario: str | None = None
    errores: list[ErrorValidacion] = Field(default_factory=list)


class EvidenciaSalida(ConVersionSalida):
    respuesta_id: UUID
    campo_clave: str
    tipo: str
    archivo_key: str
    nombre_original: str
    mime: str
    bytes: int
    ancho_px: int | None
    alto_px: int | None
    geolat: float | None
    geolng: float | None
    exif_timestamp: str | None
    anotaciones_json: dict[str, Any]
    orden: int
    etiqueta: str | None
    hash_sha256: str
    calidad: dict[str, Any] = Field(default_factory=dict)


class CalidadFotoDefaults(BaseModel):
    tamano_minimo_kb: int = Field(ge=0, le=10000)
    resolucion_minima_ancho: int = Field(ge=1, le=10000)
    resolucion_minima_alto: int = Field(ge=1, le=10000)
    compresion_maxima_pct: int = Field(ge=0, le=100)


class MiFormulario(BaseModel):
    formulario: FormularioSalida
    en_progreso: list[RespuestaSalida]
    enviados: int
