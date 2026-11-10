"""Pruebas de carga de ACMA (ACT-1.6, §6.7: 50 técnicos simultáneos, escalable a 500+).

Tres perfiles, con el peso con que el diseño describe la jornada:

  TecnicoCampo    50 usuarios · abre jornada, manda su posición GPS, sincroniza catálogos incrementales, lee sus
                  folios, abre el detalle y manda su cola offline (§6.2 capa 3, §6.8.4, §6.8.6). Es el perfil que
                  define el requisito de §6.7; desde F2-03 incluye las 100 posiciones por minuto de §6.8.4.
  UsuarioOficina  20 usuarios · listados con filtros, detalle de folio, minuta del día, tablero y SLA del contrato.
  OperadorCaptura  1 usuario  · captura de folios nuevos, la escritura más costosa (dispara clasificación,
                  severidad, SLA y alertas).

Antes de correr:  .venv/Scripts/python -m pruebas_carga.preparar --tecnicos 50
Luego:            .venv/Scripts/python -m locust -f pruebas_carga/locustfile.py --host http://localhost:8000

Con los servidores de desarrollo y pytest apagados (esta máquina tiene 7 GB).
"""
import json
import random
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from locust import HttpUser, between, events, task

DATOS = Path(__file__).resolve().parent / "datos_carga.json"


def cargar() -> dict:
    if not DATOS.exists():
        raise SystemExit(f"Falta {DATOS}. Corre primero: .venv/Scripts/python -m pruebas_carga.preparar")
    return json.loads(DATOS.read_text(encoding="utf-8"))


CONFIG = cargar()
# Cada usuario simulado toma un correo distinto de la lista, en orden, dando la vuelta si hacen falta más.
_siguiente = {"tecnico": 0, "oficina": 0}


def turno(cual: str, lista: list[str]) -> str:
    i = _siguiente[cual]
    _siguiente[cual] = i + 1
    return lista[i % len(lista)]


class BaseAcma(HttpUser):
    """Inicia sesión una vez y conserva el token de acceso en memoria, como hace la app (P11a)."""

    abstract = True
    wait_time = between(1, 4)
    email = ""
    contrasena = ""

    def on_start(self) -> None:
        # Sin `catch_response` la respuesta no admite success()/failure(): locust ya la contó. Si el login no sale,
        # este usuario no puede hacer nada util, asi que se detiene la corrida con el motivo en consola.
        r = self.client.post("/api/auth/login", json={"email": self.email, "contrasena": self.contrasena},
                             name="POST /api/auth/login")
        cuerpo = r.json() if r.status_code == 200 else {}
        if not cuerpo.get("tokens"):
            print(f"Login de {self.email} fallido ({r.status_code}): {r.text[:200]}")
            self.environment.runner.quit()
            return
        self.client.headers["Authorization"] = f"Bearer {cuerpo['tokens']['access_token']}"

    # Varias pantallas no las ve todo rol (§5.1: el Supervisor de operadores no consulta finanzas, y solo cinco roles
    # ven contratos). Un 403 ahi es la respuesta correcta, no una falla de carga.
    def json_de(self, ruta: str, nombre: str, tolera: tuple[int, ...] = (), **params):
        with self.client.get(ruta, params=params or None, name=nombre, catch_response=True) as r:
            # status 0 = la peticion no llego a hacerse (conexion rechazada o cortada). Locust ya la contó; marcarla
            # a mano revienta el greenlet, asi que aqui solo se sale.
            if not r.status_code:
                return None
            if r.status_code in tolera:
                r.success()
                return None
            if r.status_code != 200:
                r.failure(f"{r.status_code}: {r.text[:200]}")
                return None
            return r.json()


class TecnicoCampo(BaseAcma):
    """El perfil del requisito: sincronización incremental + atención del folio asignado."""

    weight = 50

    def on_start(self) -> None:
        self.email = turno("tecnico", CONFIG["tecnicos"])
        self.contrasena = CONFIG["contrasena_carga"]
        self.dispositivo = f"carga-{uuid.uuid4().hex[:10]}"
        self.desde: str | None = None
        self.folios: list[str] = []
        self.chats: list[str] = []
        # Un punto de partida distinto por técnico, alrededor de la Ciudad de México.
        self.lat = 19.40 + random.uniform(-0.08, 0.08)
        self.lng = -99.15 + random.uniform(-0.08, 0.08)
        super().on_start()
        # F2-03: sin jornada abierta el servidor no acepta posiciones (§6.8.4).
        with self.client.post("/api/operacion/jornada/iniciar",
                              json={"dispositivo_id": self.dispositivo, "acepta_aviso": True},
                              name="POST /api/operacion/jornada/iniciar", catch_response=True) as r:
            if r.status_code and r.status_code >= 500:
                r.failure(f"{r.status_code}: {r.text[:200]}")

    def on_stop(self) -> None:
        self.client.post("/api/operacion/jornada/cerrar", name="POST /api/operacion/jornada/cerrar")

    @task(10)
    def mandar_posicion(self) -> None:
        """La escritura más frecuente de la jornada: 50 técnicos cada 30 s son 100 posiciones por minuto (§6.8.4)."""
        self.lat += random.uniform(-0.0012, 0.0012)
        self.lng += random.uniform(-0.0012, 0.0012)
        cuerpo = {"posiciones": [{
            "lat": round(self.lat, 6), "lng": round(self.lng, 6),
            "capturada_at": datetime.now(UTC).isoformat(),
            "precision_m": round(random.uniform(5, 25), 1),
            "velocidad_mps": round(random.uniform(0, 14), 2),
            "rumbo": round(random.uniform(0, 359), 1),
            "bateria_pct": random.randint(20, 100),
        }]}
        with self.client.post("/api/operacion/posiciones", json=cuerpo, name="POST /api/operacion/posiciones",
                              catch_response=True) as r:
            # Un 409 es legítimo si la jornada se cerró sola; un 5xx no.
            if r.status_code and r.status_code >= 500:
                r.failure(f"{r.status_code}: {r.text[:200]}")
            elif r.status_code == 409:
                r.success()

    @task(5)
    def sincronizar(self) -> None:
        """Paquete incremental: la primera vez completo, después solo lo que cambió (§6.2 capa 3)."""
        params = {"dispositivo_id": self.dispositivo, "version_app": "carga", "plataforma": "android"}
        if self.desde:
            params["desde"] = self.desde
        paquete = self.json_de("/api/sync/catalogos", "GET /api/sync/catalogos", **params)
        if paquete:
            # `servidor_at` es la marca que el dispositivo guarda para pedir solo lo que cambió después.
            self.desde = paquete.get("servidor_at") or datetime.now(UTC).isoformat()
            self.folios = [f["id"] for f in paquete.get("folios", []) if isinstance(f, dict) and "id" in f] or self.folios

    @task(3)
    def mis_folios(self) -> None:
        lista = self.json_de("/api/folios", "GET /api/folios (técnico)", limite=50)
        if lista:
            self.folios = [f["id"] for f in lista] or self.folios

    @task(3)
    def abrir_folio(self) -> None:
        if not self.folios:
            return
        folio = random.choice(self.folios)
        self.json_de(f"/api/folios/{folio}", "GET /api/folios/{id}")
        self.json_de(f"/api/folios/{folio}/historial", "GET /api/folios/{id}/historial")
        canales = self.json_de(f"/api/folios/{folio}/chats", "GET /api/folios/{id}/chats") or []
        if canales:
            self.chats = [c["id"] for c in canales]

    @task(2)
    def subir_cola_offline(self) -> None:
        """La cola offline del técnico: un mensaje al canal del folio, idempotente por `id_cliente` (§6.2)."""
        if not self.chats:
            return
        lote = {"dispositivo_id": self.dispositivo, "version_app": "carga", "plataforma": "android", "mutaciones": [{
            "id_cliente": str(uuid.uuid4()),
            "tipo": "mensaje_chat",
            "timestamp_dispositivo": datetime.now(UTC).isoformat(),
            "payload": {"chat_id": random.choice(self.chats),
                        "contenido_texto": "Avance registrado desde la prueba de carga."},
        }]}
        with self.client.post("/api/sync/mutaciones", json=lote, name="POST /api/sync/mutaciones",
                              catch_response=True) as r:
            # Una mutación rechazada con 200 también cumple el contrato; lo que no se admite es un 5xx.
            if r.status_code and r.status_code >= 500:
                r.failure(f"{r.status_code}: {r.text[:200]}")

    @task(1)
    def notificaciones(self) -> None:
        self.json_de("/api/notificaciones", "GET /api/notificaciones", limite=20)


class UsuarioOficina(BaseAcma):
    """Mesa de control, despacho y administración: listados, detalle, minuta, tablero y SLA."""

    weight = 20

    def on_start(self) -> None:
        self.email = turno("oficina", CONFIG["oficina"])
        self.contrasena = CONFIG["contrasena_demo"]
        self.folios: list[str] = []
        self.contrato: str | None = None
        super().on_start()
        contratos = self.json_de("/api/contratos", "GET /api/contratos", tolera=(403,)) or []
        vigentes = [c for c in contratos if c.get("estado") == "activo"]
        self.contrato = vigentes[0]["id"] if vigentes else None

    @task(6)
    def listar_folios(self) -> None:
        filtros = random.choice([
            {"limite": 50},
            {"limite": 50, "estado": "en_ejecucion"},
            {"limite": 50, "estado": "cerrado"},
            {"limite": 50, "q": "falla"},
        ])
        lista = self.json_de("/api/folios", "GET /api/folios (oficina)", **filtros)
        if lista:
            self.folios = [f["id"] for f in lista]

    @task(4)
    def detalle_de_folio(self) -> None:
        if not self.folios:
            return
        folio = random.choice(self.folios)
        self.json_de(f"/api/folios/{folio}", "GET /api/folios/{id}", tolera=(403,))
        self.json_de(f"/api/sla/folios/{folio}", "GET /api/sla/folios/{id}", tolera=(403,))

    @task(3)
    def tablero(self) -> None:
        self.json_de("/api/bi/tablero", "GET /api/bi/tablero")

    @task(2)
    def jornada(self) -> None:
        self.json_de("/api/bi/jornada", "GET /api/bi/jornada")

    @task(2)
    def minuta_del_dia(self) -> None:
        hoy = datetime.now(UTC).date().isoformat()
        self.json_de("/api/minutas", "GET /api/minutas", desde=hoy, hasta=hoy)

    @task(2)
    def cumplimiento_sla(self) -> None:
        if not self.contrato:
            return
        hasta = datetime.now(UTC).date()
        self.json_de(f"/api/sla/contratos/{self.contrato}/cumplimiento",
                     "GET /api/sla/contratos/{id}/cumplimiento",
                     desde=(hasta - timedelta(days=30)).isoformat(), hasta=hasta.isoformat())

    @task(1)
    def seguimiento(self) -> None:
        self.json_de("/api/seguimiento/cotizaciones", "GET /api/seguimiento/{modulo}", tolera=(403,))


class OperadorCaptura(BaseAcma):
    """La escritura más costosa: capturar un folio dispara clasificación, severidad, SLA y alertas."""

    weight = 1
    wait_time = between(3, 8)

    def on_start(self) -> None:
        self.email = CONFIG["operador"]
        self.contrasena = CONFIG["contrasena_demo"]
        # Cada operador simulado se queda con su propio tramo de la bolsa de equipos para no chocar entre ellos.
        bolsa = list(CONFIG["equipos"])
        random.shuffle(bolsa)
        self.equipos = bolsa
        # La falla tiene que ser de la familia del equipo (§6.8.6 valida la combinación).
        self.fallas_por_familia: dict[str, list[str]] = {}
        super().on_start()
        for f in self.json_de("/api/catalogos/tipos-falla", "GET /api/catalogos/tipos-falla") or []:
            self.fallas_por_familia.setdefault(f["familia_equipo_id"], []).append(f["id"])
        # El operador solo captura en las UNs que tiene asignadas (§5.1): el resto de la bolsa no le sirve.
        mias = {u["id"] for u in self.json_de("/api/unidades-negocio", "GET /api/unidades-negocio") or []}
        self.equipos = [e for e in self.equipos
                        if self.fallas_por_familia.get(e.get("familia_id")) and e["un_id"] in mias]

    @task(3)
    def capturar(self) -> None:
        if not self.equipos:
            return
        equipo = self.equipos.pop()
        cuerpo = {
            "un_id": equipo["un_id"], "equipo_id": equipo["id"],
            "tipo_falla_id": random.choice(self.fallas_por_familia[equipo["familia_id"]]),
            "descripcion": f"Captura de prueba de carga {uuid.uuid4().hex[:8]}",
            "confirmacion_un": True, "confirmacion_un_geolat": 19.4326, "confirmacion_un_geolng": -99.1332,
            "geolat_captura": 19.4326, "geolng_captura": -99.1332,
        }
        with self.client.post("/api/folios", json=cuerpo, name="POST /api/folios", catch_response=True) as r:
            # Duplicado: 409 si el tenant bloquea y 422 JUSTIFICACION_REQUERIDA si solo pide justificar (§6.8.6).
            # Las dos son la regla de negocio funcionando, no una falla de carga.
            if not r.status_code:
                return
            if r.status_code == 409 or (r.status_code == 422 and "JUSTIFICACION_REQUERIDA" in r.text):
                r.success()
            elif r.status_code != 201:
                r.failure(f"{r.status_code}: {r.text[:200]}")

    @task(2)
    def verificar_duplicado(self) -> None:
        if not self.equipos:
            return
        self.json_de("/api/folios/verificar-duplicado", "GET /api/folios/verificar-duplicado",
                     equipo_id=self.equipos[-1]["id"])

    @task(1)
    def politicas(self) -> None:
        self.json_de("/api/folios/politicas", "GET /api/folios/politicas")


@events.quitting.add_listener
def resumen(environment, **_):
    """Deja en consola los percentiles que pide ACT-1.6, para copiarlos a docs/rendimiento/resultados.md."""
    e = environment.stats.total
    print("\n--- Resumen de la corrida ---")
    print(f"Peticiones: {e.num_requests}  ·  fallas: {e.num_failures} "
          f"({(e.num_failures / e.num_requests * 100) if e.num_requests else 0:.2f} %)")
    for p in (0.5, 0.95, 0.99):
        print(f"p{int(p * 100)}: {e.get_response_time_percentile(p)} ms")
    print(f"RPS medio: {e.total_rps:.1f}")
