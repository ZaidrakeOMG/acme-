"""Capa de proveedores de mensajería (WhatsApp y SMS). F2-02.

`services/mensajeria_service.py` es la lógica (consentimiento, canal, costo, bitácora); aquí vive solo el «cómo se
manda»: la interfaz `ProveedorMensajeria`, el catálogo de plantillas y los tres proveedores (stub, Meta Cloud API y
Twilio).
"""
from services.mensajeria.base import (
    MensajeSaliente, ProveedorMensajeria, Resultado, codificacion_sms, longitud_sms, renderizar, segmentos_sms,
    sin_acentos,
)
from services.mensajeria.plantillas import CATALOGO, POR_CLAVE, Plantilla, clave_de_evento, sembrar_plantillas
from services.mensajeria.proveedores import modo_de_canal, nombre_proveedor, obtener, permitir, remitente_de

__all__ = [
    "CATALOGO", "MensajeSaliente", "POR_CLAVE", "Plantilla", "ProveedorMensajeria", "Resultado",
    "clave_de_evento", "codificacion_sms", "longitud_sms", "modo_de_canal", "nombre_proveedor", "obtener",
    "permitir", "remitente_de", "renderizar", "segmentos_sms", "sembrar_plantillas", "sin_acentos",
]
