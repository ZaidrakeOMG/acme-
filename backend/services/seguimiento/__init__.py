"""Los cuatro módulos de seguimiento (§7.7–7.9, P07). Un servicio por módulo con la misma estructura: tabla de transiciones por
estado y rol, `cambiar_estado()` que valida, exige justificación donde el diseño lo pide, escribe `modulo_historial` y notifica.
`entradas` concentra los tres orígenes (minuta, clasificación, rechazo multinivel)."""
from services.seguimiento import base, cotizaciones, entradas, interno, presupuesto, reprogramacion

__all__ = ["base", "cotizaciones", "entradas", "interno", "presupuesto", "reprogramacion"]
