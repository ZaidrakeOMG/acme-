"""Motor de reglas de formularios: visibilidad por condiciones, validación por tipo y valores calculados.

Espejo exacto de frontend/src/services/formularios/validacion.ts. Cualquier cambio aquí se replica allá.

Reglas de evaluación (en orden de documento, cliente y servidor iguales):
- Un campo sin condiciones es visible. Con condiciones: parte oculto si alguna condición es `mostrar`, visible si todas
  son `ocultar`; luego cada condición que se cumple fija la visibilidad según su acción (la última que se cumple gana).
- El valor de un campo oculto cuenta como vacío para las condiciones de los campos siguientes y se elimina de la
  respuesta normalizada; un campo oculto no es obligatorio ni se valida.
- Los tipos calculados (concatenacion, matematicas_tiempo, sello_fecha_hora) se recalculan en el servidor.
"""
from __future__ import annotations

import math
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from schemas.formularios import TIPOS_CALCULADOS, TIPOS_SIN_DATO, Campo, EsquemaFormulario, FuenteFija

ResolutorOpciones = Callable[[Campo], list[str] | None]  # valores válidos, o None si no se puede verificar (catálogo)

RE_NUMEROS = re.compile(r"^-?\d+([.,]\d+)?$")
RE_LETRAS = re.compile(r"^[A-Za-zÁÉÍÓÚáéíóúÑñÜü\s]+$")
RE_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RE_HORA = re.compile(r"^\d{2}:\d{2}$")
RE_FECHA_HORA = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")


def vacio(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip() == ""
    if isinstance(v, (list, dict, tuple, set)):
        return len(v) == 0
    return False


def _escalar(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v).rstrip("0").rstrip(".") if isinstance(v, float) else str(v)
    return str(v)


def _numero(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", "."))
        except ValueError:
            return None
    if isinstance(v, list) and v and not isinstance(v[0], dict):
        return _numero(v[0])
    return None


def _valores_de(v: Any) -> list[str]:
    """Valores seleccionados de un campo de opciones (admite [{valor, cantidad}])."""
    if isinstance(v, list):
        return [_escalar(x["valor"] if isinstance(x, dict) else x) for x in v]
    if vacio(v):
        return []
    return [_escalar(v)]


def cumple(operador: str, valor_cond: Any, v: Any) -> bool:
    if operador == "vacio":
        return vacio(v)
    if operador == "no_vacio":
        return not vacio(v)
    if operador == "igual":
        if isinstance(v, list):
            return _valores_de(v) == [_escalar(x) for x in (valor_cond if isinstance(valor_cond, list) else [valor_cond])]
        return not vacio(v) and _escalar(v).lower() == _escalar(valor_cond).lower()
    if operador == "distinto":
        return not cumple("igual", valor_cond, v)
    if operador == "contiene":
        if vacio(v):
            return False
        if isinstance(v, list):
            return _escalar(valor_cond) in _valores_de(v)
        return _escalar(valor_cond).lower() in _escalar(v).lower()
    if operador == "opcion_seleccionada":
        return _escalar(valor_cond) in _valores_de(v)
    if operador == "en_rango":
        if vacio(v):
            return False
        minimo, maximo = valor_cond
        if isinstance(v, str) and (RE_FECHA.match(v) or RE_FECHA_HORA.match(v) or RE_HORA.match(v)):
            return str(minimo) <= v <= str(maximo)
        if isinstance(v, dict) and "minutos" in v:
            v = v["minutos"]
        n = _numero(v)
        return n is not None and float(minimo) <= n <= float(maximo)
    return False


def visibilidad(esquema: EsquemaFormulario, respuestas: dict[str, Any]) -> set[str]:
    """Claves visibles, evaluadas en orden de documento."""
    visibles: set[str] = set()
    ocultos: set[str] = set()
    for campo in esquema.campos:
        if not campo.condiciones:
            visibles.add(campo.clave)
            continue
        visible = not any(c.accion == "mostrar" for c in campo.condiciones)
        for cond in campo.condiciones:
            origen = None if cond.campo_origen in ocultos else respuestas.get(cond.campo_origen)
            if cumple(cond.operador, cond.valor, origen):
                visible = cond.accion == "mostrar"
        (visibles if visible else ocultos).add(campo.clave)
    return visibles


# ------------------------------------------------------------------- fechas

def _resolver_fecha(expr: str | None, hoy: datetime) -> str | None:
    if not expr:
        return None
    m = re.fullmatch(r"hoy([+-]\d+)?", expr.strip())
    if m:
        dias = int(m.group(1) or 0)
        return (hoy + timedelta(days=dias)).strftime("%Y-%m-%d")
    return expr


def _parse_iso(v: str) -> datetime | None:
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d", "%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(v[:19] if fmt.endswith("%S") else v, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def formatear_duracion(minutos: int, unidad: str) -> str:
    if unidad == "minutos":
        return f"{minutos} min"
    if unidad == "horas":
        return f"{minutos / 60:.2f} h"
    if unidad == "dias":
        return f"{minutos / 1440:.2f} d"
    h, m = divmod(abs(minutos), 60)
    d, h = divmod(h, 24)
    partes = [f"{d}d" if d else "", f"{h}h" if h or d else "", f"{m}min"]
    return ("-" if minutos < 0 else "") + " ".join(p for p in partes if p)


# -------------------------------------------------------------- validación

class Contexto:
    def __init__(self, evidencias: dict[str, list[dict[str, Any]]] | None = None, sistema: dict[str, str] | None = None,
                 sellos: dict[str, str] | None = None, iniciado_at: datetime | None = None, enviado_at: datetime | None = None,
                 hoy: datetime | None = None, resolutor: ResolutorOpciones | None = None):
        self.evidencias = evidencias or {}   # campo_clave -> [{tipo, ...}]
        self.sistema = sistema or {}         # claves de tiempo del sistema (captura_folio, asignacion, ...)
        self.sellos = sellos or {}           # sellos ya fijados por el servidor (clave -> ISO)
        self.iniciado_at = iniciado_at
        self.enviado_at = enviado_at
        self.hoy = hoy or datetime.now(UTC).replace(tzinfo=None)
        self.resolutor = resolutor


def _evidencias(ctx: Contexto, clave: str, tipo: str | None = None) -> int:
    lista = ctx.evidencias.get(clave, [])
    return len([e for e in lista if tipo is None or e.get("tipo") == tipo])


def _opciones_validas(campo: Campo, ctx: Contexto) -> list[str] | None:
    if isinstance(campo.fuente_opciones, FuenteFija):
        return [o.valor for o in campo.fuente_opciones.opciones]
    return ctx.resolutor(campo) if ctx.resolutor else None


def _validar_campo(campo: Campo, v: Any, ctx: Contexto, respuestas: dict[str, Any]) -> tuple[Any, str | None]:
    """Devuelve (valor normalizado, error)."""
    t, cfg = campo.tipo, campo.config
    oblig = campo.obligatorio

    if t == "si_no":
        if vacio(v):
            return None, "Selecciona una opción" if oblig else None
        if isinstance(v, str) and v.lower() in ("true", "false"):
            v = v.lower() == "true"
        if not isinstance(v, bool):
            return None, "Valor inválido"
        return v, None

    if t in ("texto", "texto_amplio", "escaner"):
        if vacio(v):
            return None, "Este campo es obligatorio" if oblig else None
        if not isinstance(v, str):
            return None, "Debe ser texto"
        s = v.strip()
        if t == "escaner":
            return (s, None) if len(s) <= 500 else (None, "Código demasiado largo")
        if len(s) < cfg["longitud_min"]:
            return None, f"Mínimo {cfg['longitud_min']} caracteres"
        if len(s) > cfg["longitud_max"]:
            return None, f"Máximo {cfg['longitud_max']} caracteres"
        if cfg["formato"] == "numeros" and not RE_NUMEROS.match(s):
            return None, cfg.get("mensaje_formato") or "Solo se permiten números"
        if cfg["formato"] == "letras" and not RE_LETRAS.match(s):
            return None, cfg.get("mensaje_formato") or "Solo se permiten letras"
        if cfg["formato"] == "regex" and not re.fullmatch(cfg["regex"], s):
            return None, cfg.get("mensaje_formato") or "El formato no es válido"
        return s, None

    if t in ("radio", "boton_grupo", "lista_desplegable"):
        multiple = t == "lista_desplegable" and cfg["seleccion"] == "multiple"
        valores = _valores_de(v)
        if not valores:
            return None, "Selecciona una opción" if oblig else None
        if not multiple and len(valores) > 1:
            return None, "Solo se permite una opción"
        validas = _opciones_validas(campo, ctx)
        if validas is not None:
            malas = [x for x in valores if x not in validas]
            if malas:
                return None, f"Opción no válida: {', '.join(malas)}"
        return (valores if multiple else valores[0]), None

    if t in ("opcion_multiple", "seleccion_multiple"):
        valores = _valores_de(v)
        if not valores:
            if oblig or cfg["min_selecciones"] > 0:
                return None, f"Selecciona al menos {max(1, cfg['min_selecciones'])} opción(es)"
            return [], None
        if len(set(valores)) != len(valores):
            return None, "Hay opciones repetidas"
        if len(valores) < cfg["min_selecciones"]:
            return None, f"Selecciona al menos {cfg['min_selecciones']} opción(es)"
        if cfg["max_selecciones"] is not None and len(valores) > cfg["max_selecciones"]:
            return None, f"Máximo {cfg['max_selecciones']} opción(es)"
        validas = _opciones_validas(campo, ctx)
        if validas is not None:
            malas = [x for x in valores if x not in validas]
            if malas:
                return None, f"Opción no válida: {', '.join(malas)}"
        if t == "seleccion_multiple" and cfg["contador_por_opcion"]:
            normal = []
            for x in v:
                cantidad = x.get("cantidad", 1) if isinstance(x, dict) else 1
                n = _numero(cantidad)
                if n is None or n != int(n) or n < cfg["contador_min"] or (cfg["contador_max"] is not None and n > cfg["contador_max"]):
                    return None, "Cantidad fuera de rango"
                normal.append({"valor": _escalar(x["valor"] if isinstance(x, dict) else x), "cantidad": int(n)})
            return normal, None
        return valores, None

    if t == "fotografia":
        n = _evidencias(ctx, campo.clave, "foto")
        if n < cfg["cantidad_min"] and (oblig or cfg["cantidad_min"] > 0):
            return None, f"Se requieren al menos {cfg['cantidad_min']} foto(s); hay {n}"
        if n > cfg["cantidad_max"]:
            return None, f"Máximo {cfg['cantidad_max']} foto(s)"
        return {"evidencias": n}, None

    if t == "firma":
        if _evidencias(ctx, campo.clave, "firma") < 1:
            return None, "La firma es obligatoria"
        return {"evidencias": 1, "timestamp": (v or {}).get("timestamp") if isinstance(v, dict) else None}, None

    if t == "dibujo":
        n = _evidencias(ctx, campo.clave, "dibujo")
        if oblig and n < 1:
            return None, "El dibujo es obligatorio"
        return {"evidencias": n}, None

    if t == "archivo":
        n = _evidencias(ctx, campo.clave, "archivo")
        if oblig and n < 1:
            return None, "Adjunta al menos un archivo"
        if n > cfg["cantidad_max"]:
            return None, f"Máximo {cfg['cantidad_max']} archivo(s)"
        return {"evidencias": n}, None

    if t == "audio":
        n = _evidencias(ctx, campo.clave, "audio")
        if oblig and n < 1:
            return None, "Graba una nota de voz"
        return {"evidencias": n}, None

    if t == "fecha_hora":
        if vacio(v):
            return None, "Indica la fecha/hora" if oblig else None
        if not isinstance(v, str):
            return None, "Formato de fecha inválido"
        patron = {"fecha": RE_FECHA, "hora": RE_HORA, "ambos": RE_FECHA_HORA}[cfg["modo"]]
        if not patron.match(v) or _parse_iso(v) is None:
            return None, {"fecha": "Usa el formato AAAA-MM-DD", "hora": "Usa el formato HH:MM", "ambos": "Usa el formato AAAA-MM-DDTHH:MM"}[cfg["modo"]]
        if cfg["modo"] != "hora":
            minimo, maximo = _resolver_fecha(cfg["fecha_minima"], ctx.hoy), _resolver_fecha(cfg["fecha_maxima"], ctx.hoy)
            if minimo and v[:10] < minimo[:10]:
                return None, f"La fecha no puede ser anterior a {minimo[:10]}"
            if maximo and v[:10] > maximo[:10]:
                return None, f"La fecha no puede ser posterior a {maximo[:10]}"
        if cfg["modo"] != "fecha" and cfg["intervalo_minutos"] > 1:
            minutos = int(v[-2:])
            if minutos % cfg["intervalo_minutos"] != 0:
                return None, f"Los minutos deben ir de {cfg['intervalo_minutos']} en {cfg['intervalo_minutos']}"
        vinculo = cfg.get("vinculo")
        if vinculo and vinculo["rol"] == "fin":
            inicio = respuestas.get(vinculo["campo_par"])
            if isinstance(inicio, str) and inicio and v < inicio:
                return None, "La fecha de fin no puede ser anterior a la de inicio"
        return v, None

    if t == "slider":
        if vacio(v):
            return None, "Indica un valor" if oblig else None
        valores = [_numero(x) for x in v] if (isinstance(v, list) and cfg["modo_rango"]) else [_numero(v)]
        if cfg["modo_rango"] and (not isinstance(v, list) or len(v) != 2):
            return None, "Indica un rango [desde, hasta]"
        if any(x is None for x in valores):
            return None, "Valor numérico inválido"
        for x in valores:
            if x < cfg["minimo"] or x > cfg["maximo"]:
                return None, f"El valor debe estar entre {cfg['minimo']} y {cfg['maximo']}"
            pasos = (x - cfg["minimo"]) / cfg["incremento"]
            if abs(pasos - round(pasos)) > 1e-6:
                return None, f"El valor debe ir en incrementos de {cfg['incremento']}"
        if cfg["modo_rango"] and valores[0] > valores[1]:
            return None, "El inicio del rango no puede ser mayor que el fin"
        return (valores if cfg["modo_rango"] else valores[0]), None

    if t == "encuesta_satisfaccion":
        if vacio(v):
            return None, "Califica el servicio" if oblig else None
        n = _numero(v)
        if n is None or n != int(n) or not 1 <= n <= cfg["escala_max"]:
            return None, f"La calificación debe ser un entero entre 1 y {cfg['escala_max']}"
        return int(n), None

    if t == "geolocalizacion":
        if vacio(v):
            return None, "Captura la ubicación" if oblig else None
        if not isinstance(v, dict) or _numero(v.get("lat")) is None or _numero(v.get("lng")) is None:
            return None, "Ubicación inválida"
        lat, lng = float(v["lat"]), float(v["lng"])
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return None, "Coordenadas fuera de rango"
        lat0 = _numero(v.get("lat_original"))
        lng0 = _numero(v.get("lng_original"))
        ajustada = bool(v.get("ajustada")) and lat0 is not None and lng0 is not None
        if ajustada:
            desplazamiento = haversine_m(lat0, lng0, lat, lng)
            if desplazamiento > cfg["radio_ajuste_m"]:
                return None, f"El ajuste manual excede el radio permitido de {cfg['radio_ajuste_m']} m"
        return {"lat": lat, "lng": lng, "lat_original": lat0 if ajustada else lat, "lng_original": lng0 if ajustada else lng,
                "ajustada": ajustada, "precision_m": _numero(v.get("precision_m"))}, None

    return v, None


def _calcular(campo: Campo, respuestas: dict[str, Any], ctx: Contexto, esquema: EsquemaFormulario) -> Any:
    t, cfg = campo.tipo, campo.config
    if t == "concatenacion":
        partes = []
        for p in cfg["partes"]:
            if p["tipo"] == "texto":
                partes.append(p["valor"])
            else:
                v = respuestas.get(p["valor"])
                origen = esquema.campo(p["valor"])
                if origen and origen.fuente_opciones and isinstance(origen.fuente_opciones, FuenteFija):
                    etiquetas = {o.valor: o.etiqueta for o in origen.fuente_opciones.opciones}
                    partes.append(", ".join(etiquetas.get(x, x) for x in _valores_de(v)))
                elif isinstance(v, dict):
                    partes.append(str(v.get("texto") or v.get("valor") or ""))
                elif isinstance(v, list):
                    partes.append(", ".join(_valores_de(v)))
                elif vacio(v):
                    partes.append("")
                else:
                    partes.append(_escalar(v))
        texto = cfg["separador"].join(partes)
        return texto.upper() if cfg["mayusculas"] else texto
    if t == "matematicas_tiempo":
        def instante(f: dict) -> datetime | None:
            if f["origen"] == "campo":
                v = respuestas.get(f["valor"])
                return _parse_iso(v) if isinstance(v, str) else None
            if f["valor"] == "ahora":
                return ctx.enviado_at.replace(tzinfo=None) if ctx.enviado_at else ctx.hoy
            v = ctx.sistema.get(f["valor"])
            return _parse_iso(v) if v else None
        a, b = instante(cfg["inicio"]), instante(cfg["fin"])
        if a is None or b is None:
            return None
        minutos = int(round((b - a).total_seconds() / 60))
        return {"minutos": minutos, "unidad": cfg["unidad"], "texto": formatear_duracion(minutos, cfg["unidad"])}
    if t == "sello_fecha_hora":
        trigger = cfg["trigger"]
        if trigger == "al_abrir" and ctx.iniciado_at:
            return ctx.iniciado_at.isoformat()
        if trigger == "al_enviar" and ctx.enviado_at:
            return ctx.enviado_at.isoformat()
        if campo.clave in ctx.sellos:
            return ctx.sellos[campo.clave]
        return (ctx.enviado_at or ctx.hoy).isoformat() if ctx.enviado_at else None
    return None


def validar(esquema: EsquemaFormulario, respuestas: dict[str, Any], ctx: Contexto, estricto: bool = True
            ) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Normaliza y valida. `estricto=False` (guardado parcial) solo normaliza tipos y omite obligatorios."""
    visibles = visibilidad(esquema, respuestas)
    salida: dict[str, Any] = {}
    errores: list[dict[str, str]] = []
    for campo in esquema.campos:
        if campo.clave not in visibles or campo.tipo in TIPOS_SIN_DATO:
            continue
        if campo.tipo in TIPOS_CALCULADOS:
            calculado = _calcular(campo, {**respuestas, **salida}, ctx, esquema)
            if calculado is not None:
                salida[campo.clave] = calculado
            continue
        v = respuestas.get(campo.clave)
        if v is None and campo.valor_defecto is not None and campo.tipo not in ("texto", "texto_amplio"):
            v = campo.valor_defecto
        if not estricto and vacio(v) and campo.tipo not in ("fotografia", "firma", "dibujo", "archivo", "audio"):
            continue
        normalizado, error = _validar_campo(campo, v, ctx, {**respuestas, **salida})
        if error:
            if estricto or not vacio(v):
                errores.append({"campo": campo.clave, "mensaje": error})
            continue
        if normalizado is not None:
            salida[campo.clave] = normalizado
    return salida, errores
