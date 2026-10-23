"""Las 4 plantillas base del repositorio (§6.8.3c): cierre de correctivo, inspección preventiva, instalación de equipo y
trabajo especial. Entre todas usan los 22 tipos de campo de §4.3. Las usa seed_dev y las pruebas."""
from __future__ import annotations

from typing import Any

from schemas.formularios import TIPOS_CAMPO, EsquemaFormulario


def _fija(*pares: tuple[str, str], colores: list[str] | None = None) -> dict[str, Any]:
    return {"origen": "fija", "opciones": [
        {"valor": v, "etiqueta": e, **({"color": colores[i]} if colores else {})} for i, (v, e) in enumerate(pares)]}


def _catalogo(catalogo: str, campo_padre: str | None = None, **extra) -> dict[str, Any]:
    return {"origen": "catalogo", "catalogo": catalogo, "filtro_contexto": True, "campo_padre": campo_padre, **extra}


CIERRE_CORRECTIVO: dict[str, Any] = {"secciones": [
    {"clave": "llegada", "titulo": "Llegada al sitio", "campos": [
        {"clave": "sello_llegada", "tipo": "sello_fecha_hora", "etiqueta": "Hora de llegada", "config": {"trigger": "al_abrir"}},
        {"clave": "ubicacion", "tipo": "geolocalizacion", "etiqueta": "Ubicación de llegada", "obligatorio": True,
         "config": {"radio_ajuste_m": 50, "geofencing_radio_m": 300, "alertar_fuera_un": True}},
        {"clave": "codigo_equipo", "tipo": "escaner", "etiqueta": "Escanea la etiqueta del equipo", "ayuda": "QR o código de barras del activo",
         "config": {"formatos": ["qr", "ean", "code128", "datamatrix"], "precargar_equipo": True, "permitir_captura_manual": True}},
        {"clave": "equipo", "tipo": "lista_desplegable", "etiqueta": "Equipo intervenido", "obligatorio": True,
         "config": {"busqueda": True, "seleccion": "unica", "disponible_offline": True}, "fuente_opciones": _catalogo("equipos_tenant")},
    ]},
    {"clave": "diagnostico", "titulo": "Diagnóstico", "campos": [
        {"clave": "enciende", "tipo": "si_no", "etiqueta": "¿El equipo enciende?", "obligatorio": True,
         "config": {"etiqueta_si": "Funciona", "etiqueta_no": "No funciona", "modo_defecto": "sin_defecto"}},
        {"clave": "familia", "tipo": "radio", "etiqueta": "Familia del equipo", "obligatorio": True, "config": {"disposicion": "vertical"},
         "fuente_opciones": _catalogo("familias_equipo", filtro_contexto=False)},
        {"clave": "tipo_falla", "tipo": "lista_desplegable", "etiqueta": "Tipo de falla detectada", "obligatorio": True,
         "config": {"busqueda": True, "seleccion": "unica", "disponible_offline": True}, "fuente_opciones": _catalogo("tipos_falla", campo_padre="familia")},
        {"clave": "sintomas", "tipo": "opcion_multiple", "etiqueta": "Síntomas observados", "config": {"min_selecciones": 1, "max_selecciones": 4},
         "fuente_opciones": _fija(("ruido", "Ruido inusual"), ("calor", "Sobrecalentamiento"), ("fuga", "Fuga"), ("olor", "Olor a quemado"), ("vibracion", "Vibración"))},
        {"clave": "detalle_falla", "tipo": "texto", "etiqueta": "Detalle de la falla", "obligatorio": True,
         "config": {"longitud_min": 10, "longitud_max": 300, "formato": "libre"},
         "condiciones": [{"campo_origen": "enciende", "operador": "igual", "valor": False, "accion": "mostrar"}]},
        {"clave": "nivel_dano", "tipo": "slider", "etiqueta": "Nivel de daño", "valor_defecto": 3,
         "config": {"minimo": 0, "maximo": 10, "incremento": 1, "etiqueta_min": "Ninguno", "etiqueta_max": "Severo", "modo_rango": False}},
        {"clave": "aviso_seguridad", "tipo": "etiqueta_info", "etiqueta": "Seguridad",
         "config": {"contenido": "**Desconecta la energía** antes de intervenir.\n- Usa guantes dieléctricos\n- Señaliza el área", "icono": "advertencia",
                    "enlace": {"url": "https://ejemplo.invalid/manual-seguridad", "texto": "Manual de seguridad"}},
         "condiciones": [{"campo_origen": "nivel_dano", "operador": "en_rango", "valor": [7, 10], "accion": "mostrar"}]},
    ]},
    {"clave": "trabajo", "titulo": "Trabajo ejecutado", "campos": [
        {"clave": "fotos_antes", "tipo": "fotografia", "etiqueta": "Fotos antes", "obligatorio": True,
         "config": {"origen": "camara", "cantidad_min": 1, "cantidad_max": 3, "etiquetas_secuencia": ["Antes", "Detalle"], "permitir_anotacion": True, "vista_previa_confirmacion": True}},
        {"clave": "refacciones", "tipo": "seleccion_multiple", "etiqueta": "Refacciones utilizadas",
         "config": {"min_selecciones": 0, "contador_por_opcion": True, "contador_min": 1, "contador_max": 50, "grupos_colapsables": True,
                    "plantillas_combinaciones": [{"nombre": "Kit eléctrico básico", "valores": ["fusible", "contactor"], "cantidades": {"fusible": 2, "contactor": 1}}]},
         "fuente_opciones": {"origen": "fija", "opciones": [
             {"valor": "fusible", "etiqueta": "Fusible 10A", "grupo": "Eléctrico"}, {"valor": "contactor", "etiqueta": "Contactor", "grupo": "Eléctrico"},
             {"valor": "gas", "etiqueta": "Carga de gas R-404", "grupo": "Refrigeración"}, {"valor": "filtro", "etiqueta": "Filtro deshidratador", "grupo": "Refrigeración"}]}},
        {"clave": "causa_raiz", "tipo": "lista_desplegable", "etiqueta": "Causa raíz", "config": {"busqueda": True, "seleccion": "unica", "disponible_offline": True},
         "fuente_opciones": _catalogo("catalogo_personalizado", catalogo_personalizado_id="00000000-0000-0000-0000-000000000000")},
        {"clave": "informe", "tipo": "texto_amplio", "etiqueta": "Informe del trabajo", "obligatorio": True,
         "valor_defecto": "Describir: qué encontró, qué hizo, qué recomienda",
         "config": {"lineas_visibles": 5, "longitud_min": 20, "longitud_max": 3000, "formato": "libre"}},
        {"clave": "nota_voz", "tipo": "audio", "etiqueta": "Nota de voz (opcional)", "config": {"duracion_maxima_seg": 120, "transcripcion": True}},
        {"clave": "fotos_despues", "tipo": "fotografia", "etiqueta": "Fotos después", "obligatorio": True,
         "config": {"origen": "camara_galeria", "cantidad_min": 1, "cantidad_max": 3, "etiquetas_secuencia": ["Después"], "permitir_anotacion": True, "vista_previa_confirmacion": True}},
        {"clave": "esquema", "tipo": "dibujo", "etiqueta": "Marca en la foto dónde intervino",
         "config": {"imagen_referencia": {"tipo": "campo_fotografia", "valor": "fotos_despues"}, "permitir_color": True, "permitir_grosor": True}},
    ]},
    {"clave": "cierre", "titulo": "Cierre", "campos": [
        {"clave": "inicio_trabajo", "tipo": "fecha_hora", "etiqueta": "Inicio del trabajo", "obligatorio": True, "config": {"modo": "ambos", "intervalo_minutos": 5}},
        {"clave": "fin_trabajo", "tipo": "fecha_hora", "etiqueta": "Fin del trabajo", "obligatorio": True,
         "config": {"modo": "ambos", "intervalo_minutos": 5, "vinculo": {"rol": "fin", "campo_par": "inicio_trabajo"}}},
        {"clave": "duracion", "tipo": "matematicas_tiempo", "etiqueta": "Duración del servicio",
         "config": {"inicio": {"origen": "campo", "valor": "inicio_trabajo"}, "fin": {"origen": "campo", "valor": "fin_trabajo"}, "unidad": "compuesto"}},
        {"clave": "resultado", "tipo": "boton_grupo", "etiqueta": "Resultado", "obligatorio": True, "config": {"tamano": "grande"},
         "fuente_opciones": _fija(("resuelto", "Resuelto"), ("parcial", "Parcial"), ("pendiente", "Pendiente"), colores=["#2E7D32", "#F9A825", "#C62828"])},
        {"clave": "pendiente_detalle", "tipo": "texto", "etiqueta": "¿Qué queda pendiente?", "obligatorio": True, "config": {"longitud_min": 5, "longitud_max": 300},
         "condiciones": [{"campo_origen": "resultado", "operador": "opcion_seleccionada", "valor": "pendiente", "accion": "mostrar"},
                         {"campo_origen": "resultado", "operador": "opcion_seleccionada", "valor": "parcial", "accion": "mostrar"}]},
        {"clave": "referencia", "tipo": "concatenacion", "etiqueta": "Referencia del servicio",
         "config": {"partes": [{"tipo": "texto", "valor": "SRV"}, {"tipo": "campo", "valor": "codigo_equipo"}, {"tipo": "campo", "valor": "resultado"}], "separador": "-", "mayusculas": True}},
        {"clave": "cotizacion", "tipo": "archivo", "etiqueta": "Cotización de refacción (si aplica)",
         "config": {"tipos_permitidos": ["pdf", "imagen"], "tamano_maximo_mb": 10, "cantidad_max": 2, "permitir_anotacion_imagen": True}},
        {"clave": "firma", "tipo": "firma", "etiqueta": "Firma de conformidad del operador", "config": {"pantalla_completa": True, "texto_conformidad": "Recibí el servicio a conformidad"}},
        {"clave": "satisfaccion", "tipo": "encuesta_satisfaccion", "etiqueta": "¿Cómo calificas el servicio?", "obligatorio": True,
         "config": {"modalidad": "estrellas", "escala_max": 5, "etiqueta_min": "Malo", "etiqueta_max": "Excelente", "umbral_bajo": 2}},
        {"clave": "retroalimentacion", "tipo": "texto_amplio", "etiqueta": "Cuéntanos qué salió mal", "obligatorio": True,
         "config": {"lineas_visibles": 3, "longitud_min": 10, "longitud_max": 1000},
         "condiciones": [{"campo_origen": "satisfaccion", "operador": "en_rango", "valor": [1, 2], "accion": "mostrar"}]},
        {"clave": "sello_cierre", "tipo": "sello_fecha_hora", "etiqueta": "Hora de cierre", "config": {"trigger": "al_enviar"}},
    ]},
]}

INSPECCION_PREVENTIVA: dict[str, Any] = {"secciones": [
    {"clave": "equipo", "titulo": "Equipo revisado", "campos": [
        {"clave": "sello_inicio", "tipo": "sello_fecha_hora", "etiqueta": "Inicio de la inspección", "config": {"trigger": "al_abrir"}},
        {"clave": "familia", "tipo": "radio", "etiqueta": "Familia", "obligatorio": True, "config": {"disposicion": "horizontal"},
         "fuente_opciones": _catalogo("familias_equipo", filtro_contexto=False)},
        {"clave": "tipo_equipo", "tipo": "lista_desplegable", "etiqueta": "Clasificación del equipo", "obligatorio": True,
         "config": {"busqueda": True, "seleccion": "unica", "disponible_offline": True}, "fuente_opciones": _catalogo("tipos_equipo", campo_padre="familia")},
        {"clave": "equipo", "tipo": "lista_desplegable", "etiqueta": "Equipo", "obligatorio": True,
         "config": {"busqueda": True, "seleccion": "unica", "disponible_offline": True}, "fuente_opciones": _catalogo("equipos_tenant")},
    ]},
    {"clave": "puntos", "titulo": "Puntos de revisión", "campos": [
        {"clave": "limpieza", "tipo": "si_no", "etiqueta": "¿Se realizó limpieza?", "obligatorio": True, "valor_defecto": True,
         "config": {"etiqueta_si": "Sí", "etiqueta_no": "No", "modo_defecto": "con_defecto"}},
        {"clave": "puntos_ok", "tipo": "opcion_multiple", "etiqueta": "Puntos verificados", "obligatorio": True, "config": {"min_selecciones": 1},
         "valor_defecto": ["filtros", "conexiones"],
         "fuente_opciones": _fija(("filtros", "Filtros"), ("conexiones", "Conexiones eléctricas"), ("gas", "Presión de gas"), ("drenaje", "Drenaje"), ("ruido", "Nivel de ruido"))},
        {"clave": "temperatura", "tipo": "texto", "etiqueta": "Temperatura medida (°C)", "obligatorio": True,
         "config": {"longitud_min": 1, "longitud_max": 6, "formato": "numeros", "mensaje_formato": "Solo números, p. ej. -18 o 4.5"}},
        {"clave": "estado_general", "tipo": "slider", "etiqueta": "Estado general", "valor_defecto": 7,
         "config": {"minimo": 1, "maximo": 10, "incremento": 1, "etiqueta_min": "Crítico", "etiqueta_max": "Óptimo", "modo_rango": False}},
        {"clave": "requiere_correctivo", "tipo": "boton_grupo", "etiqueta": "¿Requiere correctivo?", "obligatorio": True, "valor_defecto": "no",
         "config": {"tamano": "grande"}, "fuente_opciones": _fija(("no", "No"), ("si", "Sí, programar"), colores=["#2E7D32", "#C62828"])},
        {"clave": "hallazgo", "tipo": "texto_amplio", "etiqueta": "Describe el hallazgo", "obligatorio": True,
         "config": {"lineas_visibles": 4, "longitud_min": 10, "longitud_max": 2000},
         "condiciones": [{"campo_origen": "requiere_correctivo", "operador": "igual", "valor": "si", "accion": "mostrar"}]},
        {"clave": "fotos", "tipo": "fotografia", "etiqueta": "Evidencia fotográfica", "obligatorio": True,
         "config": {"origen": "camara", "cantidad_min": 1, "cantidad_max": 4, "etiquetas_secuencia": ["General", "Detalle"], "permitir_anotacion": True, "vista_previa_confirmacion": True}},
    ]},
    {"clave": "cierre", "titulo": "Cierre", "campos": [
        {"clave": "proxima", "tipo": "fecha_hora", "etiqueta": "Próxima inspección sugerida", "config": {"modo": "fecha", "fecha_minima": "hoy", "defecto_hoy_mas_dias": 30}},
        {"clave": "sello_fin", "tipo": "sello_fecha_hora", "etiqueta": "Fin de la inspección", "config": {"trigger": "al_enviar"}},
        {"clave": "duracion", "tipo": "matematicas_tiempo", "etiqueta": "Duración",
         "config": {"inicio": {"origen": "campo", "valor": "sello_inicio"}, "fin": {"origen": "sistema", "valor": "ahora"}, "unidad": "minutos"}},
        {"clave": "firma", "tipo": "firma", "etiqueta": "Firma del responsable de la UN", "config": {"pantalla_completa": True}},
    ]},
]}

INSTALACION_EQUIPO: dict[str, Any] = {"secciones": [
    {"clave": "datos", "titulo": "Datos del equipo nuevo", "campos": [
        {"clave": "un", "tipo": "lista_desplegable", "etiqueta": "Ubicación del trabajo", "obligatorio": True,
         "config": {"busqueda": True, "seleccion": "unica", "disponible_offline": True}, "fuente_opciones": _catalogo("unidades_negocio")},
        {"clave": "serie", "tipo": "escaner", "etiqueta": "Escanea el número de serie", "obligatorio": True,
         "config": {"formatos": ["qr", "code128", "datamatrix"], "precargar_equipo": False, "permitir_captura_manual": True}},
        {"clave": "modelo", "tipo": "texto", "etiqueta": "Modelo", "obligatorio": True, "config": {"longitud_min": 2, "longitud_max": 60, "formato": "regex", "regex": "^[A-Z0-9-]+$", "mensaje_formato": "Mayúsculas, números y guiones"}},
        {"clave": "codigo_activo", "tipo": "concatenacion", "etiqueta": "Código de activo propuesto",
         "config": {"partes": [{"tipo": "texto", "valor": "EQ"}, {"tipo": "campo", "valor": "modelo"}, {"tipo": "campo", "valor": "serie"}], "separador": "-", "mayusculas": True}},
        {"clave": "instrucciones", "tipo": "etiqueta_info", "etiqueta": "Instalación",
         "config": {"contenido": "Verifica **nivelación**, **voltaje** y **drenaje** antes de energizar.", "icono": "info"}},
    ]},
    {"clave": "pruebas", "titulo": "Pruebas de arranque", "campos": [
        {"clave": "voltaje_ok", "tipo": "si_no", "etiqueta": "¿Voltaje dentro de rango?", "obligatorio": True, "config": {"etiqueta_si": "Correcto", "etiqueta_no": "Fuera de rango"}},
        {"clave": "voltaje_medido", "tipo": "texto", "etiqueta": "Voltaje medido (V)", "obligatorio": True, "config": {"longitud_min": 1, "longitud_max": 6, "formato": "numeros"},
         "condiciones": [{"campo_origen": "voltaje_ok", "operador": "igual", "valor": False, "accion": "mostrar"}]},
        {"clave": "rango_temp", "tipo": "slider", "etiqueta": "Rango de temperatura alcanzado (°C)",
         "config": {"minimo": -30, "maximo": 30, "incremento": 1, "etiqueta_min": "-30", "etiqueta_max": "30", "modo_rango": True}},
        {"clave": "arranque", "tipo": "fecha_hora", "etiqueta": "Hora de arranque", "obligatorio": True, "config": {"modo": "hora", "intervalo_minutos": 5}},
        {"clave": "fotos", "tipo": "fotografia", "etiqueta": "Fotos de la instalación", "obligatorio": True,
         "config": {"origen": "camara", "cantidad_min": 2, "cantidad_max": 6, "etiquetas_secuencia": ["Frente", "Placa de datos", "Conexiones"], "permitir_anotacion": True, "vista_previa_confirmacion": True}},
        {"clave": "plano", "tipo": "dibujo", "etiqueta": "Ubicación en el plano", "config": {"imagen_referencia": {"tipo": "ninguna"}, "permitir_color": True, "permitir_grosor": False}},
        {"clave": "garantia", "tipo": "archivo", "etiqueta": "Póliza de garantía", "obligatorio": True,
         "config": {"tipos_permitidos": ["pdf"], "tamano_maximo_mb": 20, "cantidad_max": 1, "permitir_anotacion_imagen": False}},
    ]},
    {"clave": "entrega", "titulo": "Entrega", "campos": [
        {"clave": "ubicacion", "tipo": "geolocalizacion", "etiqueta": "Ubicación de la instalación", "obligatorio": True, "config": {"radio_ajuste_m": 30, "geofencing_radio_m": 500, "alertar_fuera_un": True}},
        {"clave": "firma", "tipo": "firma", "etiqueta": "Firma de recepción", "config": {"pantalla_completa": True}},
        {"clave": "sello", "tipo": "sello_fecha_hora", "etiqueta": "Entregado", "config": {"trigger": "al_enviar"}},
    ]},
]}

TRABAJO_ESPECIAL: dict[str, Any] = {"secciones": [
    {"clave": "alcance", "titulo": "Alcance", "campos": [
        {"clave": "sello_inicio", "tipo": "sello_fecha_hora", "etiqueta": "Inicio", "config": {"trigger": "al_abrir"}},
        {"clave": "tecnico_ejecutante", "tipo": "lista_desplegable", "etiqueta": "Técnico ejecutante", "obligatorio": True,
         "config": {"busqueda": True, "seleccion": "multiple", "disponible_offline": True}, "fuente_opciones": _catalogo("tecnicos_prestador")},
        {"clave": "tercero", "tipo": "lista_desplegable", "etiqueta": "Tercero que intervino", "config": {"busqueda": True, "seleccion": "unica", "disponible_offline": False},
         "fuente_opciones": _catalogo("proveedores_externos")},
        {"clave": "descripcion", "tipo": "texto_amplio", "etiqueta": "Descripción del trabajo", "obligatorio": True, "config": {"lineas_visibles": 6, "longitud_min": 20, "longitud_max": 5000}},
        {"clave": "materiales", "tipo": "seleccion_multiple", "etiqueta": "Materiales", "config": {"min_selecciones": 0, "contador_por_opcion": True, "contador_min": 1, "grupos_colapsables": False},
         "fuente_opciones": _catalogo("materiales")},
    ]},
    {"clave": "ejecucion", "titulo": "Ejecución", "campos": [
        {"clave": "fase", "tipo": "boton_grupo", "etiqueta": "Fase entregada", "obligatorio": True, "config": {"tamano": "grande"},
         "fuente_opciones": _fija(("inicio", "Inicio"), ("avance", "Avance"), ("final", "Entrega final"), colores=["#1565C0", "#F9A825", "#2E7D32"])},
        {"clave": "porcentaje", "tipo": "slider", "etiqueta": "Avance (%)", "obligatorio": True, "config": {"minimo": 0, "maximo": 100, "incremento": 5, "etiqueta_min": "0%", "etiqueta_max": "100%", "modo_rango": False}},
        {"clave": "fotos", "tipo": "fotografia", "etiqueta": "Evidencia", "obligatorio": True,
         "config": {"origen": "camara_galeria", "cantidad_min": 1, "cantidad_max": 10, "etiquetas_secuencia": [], "permitir_anotacion": True, "vista_previa_confirmacion": True}},
        {"clave": "nota_voz", "tipo": "audio", "etiqueta": "Comentarios de obra", "config": {"duracion_maxima_seg": 300, "transcripcion": True}},
        {"clave": "inicio_jornada", "tipo": "fecha_hora", "etiqueta": "Inicio de jornada", "obligatorio": True, "config": {"modo": "ambos"}},
        {"clave": "fin_jornada", "tipo": "fecha_hora", "etiqueta": "Fin de jornada", "obligatorio": True, "config": {"modo": "ambos", "vinculo": {"rol": "fin", "campo_par": "inicio_jornada"}}},
        {"clave": "horas", "tipo": "matematicas_tiempo", "etiqueta": "Horas trabajadas", "config": {"inicio": {"origen": "campo", "valor": "inicio_jornada"}, "fin": {"origen": "campo", "valor": "fin_jornada"}, "unidad": "horas"}},
    ]},
    {"clave": "aceptacion", "titulo": "Aceptación del cliente", "campos": [
        {"clave": "acepta", "tipo": "si_no", "etiqueta": "¿El cliente acepta el trabajo?", "obligatorio": True, "config": {"etiqueta_si": "Acepta", "etiqueta_no": "No acepta"},
         "condiciones": [{"campo_origen": "fase", "operador": "igual", "valor": "final", "accion": "mostrar"}]},
        {"clave": "motivo_rechazo", "tipo": "texto_amplio", "etiqueta": "Motivo del rechazo", "obligatorio": True, "config": {"lineas_visibles": 3, "longitud_min": 10, "longitud_max": 1000},
         "condiciones": [{"campo_origen": "acepta", "operador": "igual", "valor": False, "accion": "mostrar"}]},
        {"clave": "satisfaccion", "tipo": "encuesta_satisfaccion", "etiqueta": "Satisfacción", "config": {"modalidad": "emojis", "escala_max": 5, "umbral_bajo": 2},
         "condiciones": [{"campo_origen": "fase", "operador": "igual", "valor": "final", "accion": "mostrar"}]},
        {"clave": "firma", "tipo": "firma", "etiqueta": "Firma del cliente", "config": {"pantalla_completa": True},
         "condiciones": [{"campo_origen": "fase", "operador": "igual", "valor": "final", "accion": "mostrar"}]},
        {"clave": "ubicacion", "tipo": "geolocalizacion", "etiqueta": "Ubicación", "config": {"radio_ajuste_m": 100, "geofencing_radio_m": 1000, "alertar_fuera_un": False}},
        {"clave": "codigo", "tipo": "concatenacion", "etiqueta": "Código de entrega", "config": {"partes": [{"tipo": "texto", "valor": "TE"}, {"tipo": "campo", "valor": "fase"}, {"tipo": "campo", "valor": "porcentaje"}], "separador": "/"}},
        {"clave": "aviso", "tipo": "etiqueta_info", "etiqueta": "Nota", "config": {"contenido": "La aceptación final cierra el trabajo especial.", "icono": "peligro"},
         "condiciones": [{"campo_origen": "fase", "operador": "igual", "valor": "final", "accion": "mostrar"}]},
        {"clave": "evidencia_extra", "tipo": "archivo", "etiqueta": "Documentos", "config": {"tipos_permitidos": ["cualquiera"], "tamano_maximo_mb": 25, "cantidad_max": 5, "permitir_anotacion_imagen": True}},
        {"clave": "sello_fin", "tipo": "sello_fecha_hora", "etiqueta": "Fin", "config": {"trigger": "al_llegar_seccion"}},
    ]},
]}

PLANTILLAS: list[dict[str, Any]] = [
    {"nombre": "Cierre de correctivo", "tipo": "atencion_tecnico", "rol_destino": ["tecnico"], "esquema": CIERRE_CORRECTIVO,
     "descripcion": "Reporte de atención del técnico para un folio correctivo, con firma del operador y encuesta."},
    {"nombre": "Inspección preventiva", "tipo": "preventivo", "rol_destino": ["tecnico"], "esquema": INSPECCION_PREVENTIVA,
     "descripcion": "Puntos de revisión de un mantenimiento preventivo programado."},
    {"nombre": "Instalación de equipo", "tipo": "trabajo_especial", "rol_destino": ["tecnico"], "esquema": INSTALACION_EQUIPO,
     "descripcion": "Alta de un equipo nuevo con pruebas de arranque y recepción."},
    {"nombre": "Trabajo especial", "tipo": "trabajo_especial", "rol_destino": ["tecnico", "despachador"], "esquema": TRABAJO_ESPECIAL,
     "descripcion": "Avances y aceptación del cliente en un trabajo especial."},
]

CAPTURA_OPERADOR: dict[str, Any] = {"secciones": [
    {"clave": "captura", "titulo": "Reporte de falla", "campos": [
        {"clave": "equipo", "tipo": "lista_desplegable", "etiqueta": "Equipo afectado", "obligatorio": True,
         "config": {"busqueda": True, "seleccion": "unica", "disponible_offline": True}, "fuente_opciones": _catalogo("equipos_tenant")},
        {"clave": "familia", "tipo": "radio", "etiqueta": "Familia del equipo", "obligatorio": True, "config": {"disposicion": "horizontal"},
         "fuente_opciones": _catalogo("familias_equipo", filtro_contexto=False)},
        {"clave": "tipo_falla", "tipo": "lista_desplegable", "etiqueta": "Tipo de falla", "obligatorio": True,
         "config": {"busqueda": True, "seleccion": "unica", "disponible_offline": True}, "fuente_opciones": _catalogo("tipos_falla", campo_padre="familia")},
        {"clave": "urgencia", "tipo": "boton_grupo", "etiqueta": "Impacto en la operación", "obligatorio": True, "config": {"tamano": "grande"},
         "fuente_opciones": _fija(("bajo", "Sigue operando"), ("medio", "Opera parcialmente"), ("alto", "Detenido"), colores=["#2E7D32", "#F9A825", "#C62828"])},
        {"clave": "descripcion", "tipo": "texto_amplio", "etiqueta": "Descripción", "obligatorio": True, "config": {"lineas_visibles": 4, "longitud_min": 10, "longitud_max": 2000}},
        {"clave": "fotos", "tipo": "fotografia", "etiqueta": "Fotos del problema", "obligatorio": True,
         "config": {"origen": "camara", "cantidad_min": 1, "cantidad_max": 3, "etiquetas_secuencia": [], "permitir_anotacion": True, "vista_previa_confirmacion": True}},
        {"clave": "ubicacion", "tipo": "geolocalizacion", "etiqueta": "Ubicación", "obligatorio": True, "config": {"radio_ajuste_m": 50, "geofencing_radio_m": 300, "alertar_fuera_un": True}},
    ]},
]}


def validar_plantillas() -> dict[str, EsquemaFormulario]:
    esquemas = {p["nombre"]: EsquemaFormulario.model_validate(p["esquema"]) for p in PLANTILLAS}
    esquemas["Captura de operador"] = EsquemaFormulario.model_validate(CAPTURA_OPERADOR)
    return esquemas


def tipos_cubiertos() -> set[str]:
    return {c.tipo for e in validar_plantillas().values() for c in e.campos}


if __name__ == "__main__":
    faltan = set(TIPOS_CAMPO) - tipos_cubiertos()
    print("Tipos cubiertos:", len(tipos_cubiertos()), "faltan:", sorted(faltan) or "ninguno")
