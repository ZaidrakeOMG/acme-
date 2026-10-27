"""Notificaciones push/app (stub de P04). El canal real (push, minuta) llega en P07; aquí se registra en el log y se
deja un historial en memoria para pruebas. Sin proveedores externos (regla 3)."""
import logging
from collections import deque
from typing import Any
from uuid import UUID

log = logging.getLogger("acma.notificaciones")

# Últimas notificaciones emitidas (para inspección en pruebas/desarrollo).
ENVIADAS: deque[dict[str, Any]] = deque(maxlen=200)


def enviar(*, roles: list[str] | None = None, usuarios: list[UUID] | None = None, tenant_id: UUID | None = None,
           prestador_id: UUID | None = None, titulo: str, cuerpo: str = "", datos: dict[str, Any] | None = None,
           canales: list[str] | None = None) -> dict[str, Any]:
    n = {
        "roles": roles or [], "usuarios": [str(u) for u in usuarios or []], "tenant_id": str(tenant_id) if tenant_id else None,
        "prestador_id": str(prestador_id) if prestador_id else None, "titulo": titulo, "cuerpo": cuerpo, "datos": datos or {},
        "canales": canales or ["push", "app"],
    }
    ENVIADAS.append(n)
    log.info("Notificación [%s] a %s: %s — %s", ",".join(n["canales"]), n["roles"] or n["usuarios"], titulo, cuerpo)
    return n
