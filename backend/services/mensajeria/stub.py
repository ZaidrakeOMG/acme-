"""Proveedor simulado (modo `stub`, el de desarrollo y pruebas). F2-02.

Nada sale de la máquina: el mensaje renderizado se guarda en `ENVIADOS` (lo lee la pantalla de bitácora y las
pruebas) y como archivo de vista previa en el almacenamiento, igual que el `.eml` del correo en modo stub de P07.
Simula los estados `entregado` y `leido` y, para probar los caminos de error, acepta fallas programadas por número.
"""
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from services.mensajeria.base import MensajeSaliente, Resultado, segmentos_sms

log = logging.getLogger("acma.mensajeria")

ENVIADOS: list[dict[str, Any]] = []  # últimos mensajes simulados (máximo 200)
# Fallas programadas para pruebas: {telefono_o_"*": (codigo_error, permanente)}.
FALLAS: dict[str, tuple[str, bool]] = {}
# Estado que el stub reporta al consultarlo (los estados reales llegan por webhook).
ESTADOS: dict[str, str] = {}


class ProveedorStub:
    nombre = "stub"

    async def enviar_plantilla(self, m: MensajeSaliente) -> Resultado:
        return await self._registrar(m, "plantilla")

    async def enviar_texto(self, m: MensajeSaliente) -> Resultado:
        return await self._registrar(m, "texto")

    async def estado(self, mensaje_id: str) -> str | None:
        return ESTADOS.get(mensaje_id)

    def validar_webhook(self, cuerpo: bytes, cabeceras: dict[str, str]) -> bool:
        return True  # el endpoint de simulación ya exige rol de administrador

    async def _registrar(self, m: MensajeSaliente, tipo: str) -> Resultado:
        falla = FALLAS.get(m.telefono) or FALLAS.get("*")
        if falla:
            codigo, permanente = falla
            log.info("Mensaje (stub) NO enviado a %s: %s", m.telefono[-4:], codigo)
            return Resultado(estado="rechazado_por_proveedor" if permanente else "fallido", codigo_error=codigo,
                             detalle=f"falla simulada ({'permanente' if permanente else 'temporal'})",
                             permanente=permanente)
        mensaje_id = f"stub-{uuid.uuid4().hex[:16]}"
        segmentos, codificacion = segmentos_sms(m.cuerpo) if m.canal == "sms" else (0, "")
        registro = {"mensaje_id": mensaje_id, "canal": m.canal, "tipo": tipo, "plantilla": m.plantilla_clave,
                    "cuerpo": m.cuerpo, "variables": list(m.variables), "botones": list(m.botones),
                    "enlace": m.enlace, "segmentos": segmentos, "codificacion": codificacion,
                    "timestamp": datetime.now(UTC).isoformat(), "destino_final": m.telefono[-4:]}
        ENVIADOS.append(registro)
        del ENVIADOS[:-200]
        ESTADOS[mensaje_id] = "entregado"
        registro["vista_previa_key"] = _vista_previa(mensaje_id, m)
        log.info("Mensaje (stub) por %s «%s» → ••%s: %s", m.canal, m.plantilla_clave or tipo, m.telefono[-2:], m.cuerpo)
        return Resultado(estado="enviado", mensaje_id=mensaje_id, detalle=f"stub:{registro['vista_previa_key']}")


def _vista_previa(mensaje_id: str, m: MensajeSaliente) -> str:
    """Guarda el mensaje tal como se vería, para que la usuaria lo revise sin cuenta de proveedor."""
    from services.almacenamiento import obtener_almacenamiento

    clave = f"mensajeria/{datetime.now(UTC):%Y/%m/%d}/{mensaje_id}.txt"
    botones = "\n".join(f"[{b.get('texto', '')}] {b.get('url') or b.get('ruta', '')}".strip() for b in m.botones)
    texto = (f"Canal: {m.canal}\nPlantilla: {m.plantilla_clave}\nDestino: ••{m.telefono[-2:]}\n"
             f"Remitente: {m.remitente}\n\n{m.cuerpo}\n\n{botones}\n")
    try:
        obtener_almacenamiento().guardar(clave, texto.encode("utf-8"), "text/plain; charset=utf-8")
    except Exception as e:  # noqa: BLE001 — sin almacenamiento el mensaje queda en ENVIADOS y en el log
        log.warning("Vista previa del mensaje %s sin almacenamiento: %s", mensaje_id, e)
        return ""
    return clave


def simular_estado(mensaje_id: str, estado: str) -> None:
    """Lo usa el endpoint de simulación de webhook y las pruebas."""
    ESTADOS[mensaje_id] = estado


def limpiar() -> None:
    ENVIADOS.clear()
    FALLAS.clear()
    ESTADOS.clear()
