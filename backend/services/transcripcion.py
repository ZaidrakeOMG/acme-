"""Transcripción de audio (§4.3 `audio`). Interfaz con implementación stub: sin proveedores de pago en Fase 1.

Fase 2 sustituye `TranscriptorStub` por un adaptador real (p. ej. Whisper/Speech-to-Text) con la misma firma.
"""
import logging
from typing import Protocol

log = logging.getLogger("acma.transcripcion")


class Transcriptor(Protocol):
    def transcribir(self, archivo_key: str, mime: str) -> dict: ...


class TranscriptorStub:
    def transcribir(self, archivo_key: str, mime: str) -> dict:
        log.info("Transcripción pendiente (stub) para %s", archivo_key)
        return {"estado": "pendiente", "texto": None, "motivo": "Transcripción automática disponible en Fase 2"}


transcriptor: Transcriptor = TranscriptorStub()
