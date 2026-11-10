"""Tiempo real (§6.8.1 chat, §6.8.4 operaciones): un canal por tema. Las conexiones WebSocket/SSE de este proceso
se registran en colas locales; la publicación pasa por Redis pub/sub para que funcione con más de un proceso de API.
Si Redis no está disponible (o TIEMPO_REAL_MODO=local, como en pruebas) se reparte solo en el proceso.

El canal es una cadena con su tema por delante: `chat:{id}` para el chat de un folio y `operacion:{prestador}` para
el tablero de operaciones, que es por prestador para que las posiciones de un prestador no lleguen al tablero de
otro (§6.9.5). F2-03 generalizó lo que P05 tenía escrito solo para el chat; `suscribir()` y `publicar()` siguen
recibiendo el id del chat para no tocar el código de P05."""
import asyncio
import contextlib
import json
import logging
from typing import Any

from core.config import config

log = logging.getLogger("acma.tiempo_real")


class GestorTiempoReal:
    def __init__(self) -> None:
        self._locales: dict[str, set[asyncio.Queue]] = {}
        self._redis = None
        self._pubsub = None
        self._escucha: asyncio.Task | None = None
        self._canales: set[str] = set()

    # ------------------------------------------------------------ redis
    async def _conectar(self):
        if self._redis is not None or config.tiempo_real_modo != "redis":
            return self._redis
        try:
            import redis.asyncio as redis_async

            cliente = redis_async.from_url(config.redis_url, decode_responses=True)
            await asyncio.wait_for(cliente.ping(), timeout=2)
            self._redis = cliente
            self._pubsub = cliente.pubsub()
            self._escucha = asyncio.create_task(self._escuchar())
        except Exception as e:  # sin Redis: solo reparto local
            log.warning("Tiempo real sin Redis (%s); solo reparto en este proceso", e)
            self._redis = None
        return self._redis

    async def _escuchar(self) -> None:
        assert self._pubsub is not None
        while True:
            try:
                mensaje = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            except Exception:
                await asyncio.sleep(1)
                continue
            if mensaje and mensaje.get("type") == "message":
                with contextlib.suppress(Exception):
                    self._repartir_local(str(mensaje["channel"]), json.loads(mensaje["data"]))
            await asyncio.sleep(0)

    # --------------------------------------------------------- suscripción
    async def suscribir_canal(self, canal: str) -> asyncio.Queue:
        cola: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._locales.setdefault(canal, set()).add(cola)
        redis_cliente = await self._conectar()
        if redis_cliente is not None and canal not in self._canales:
            self._canales.add(canal)
            await self._pubsub.subscribe(canal)
        return cola

    async def desuscribir_canal(self, canal: str, cola: asyncio.Queue) -> None:
        colas = self._locales.get(canal)
        if colas:
            colas.discard(cola)
            if not colas:
                self._locales.pop(canal, None)
                if self._pubsub is not None and canal in self._canales:
                    self._canales.discard(canal)
                    with contextlib.suppress(Exception):
                        await self._pubsub.unsubscribe(canal)

    async def suscribir(self, chat_id: str) -> asyncio.Queue:
        return await self.suscribir_canal(f"chat:{chat_id}")

    async def desuscribir(self, chat_id: str, cola: asyncio.Queue) -> None:
        await self.desuscribir_canal(f"chat:{chat_id}", cola)

    def _repartir_local(self, canal: str, evento: dict[str, Any]) -> None:
        for cola in list(self._locales.get(canal, ())):
            with contextlib.suppress(asyncio.QueueFull):
                cola.put_nowait(evento)

    async def publicar_canal(self, canal: str, evento: dict[str, Any]) -> None:
        redis_cliente = await self._conectar()
        if redis_cliente is not None:
            try:
                await redis_cliente.publish(canal, json.dumps(evento, default=str))
                return  # el proceso lo recibe por su propia suscripción
            except Exception as e:
                log.warning("Publicación en Redis falló (%s); reparto local", e)
        self._repartir_local(canal, evento)

    async def publicar(self, chat_id: str, evento: dict[str, Any]) -> None:
        await self.publicar_canal(f"chat:{chat_id}", evento)

    def conexiones(self, chat_id: str) -> int:
        return len(self._locales.get(f"chat:{chat_id}", ()))

    def conexiones_canal(self, canal: str) -> int:
        return len(self._locales.get(canal, ()))


gestor = GestorTiempoReal()
