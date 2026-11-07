"""Pruebas contra PostgreSQL real (base acma_test) con el rol acma_api, igual que en producción.

Antes de importar la app se redirige DATABASE_URL a la base de pruebas y se activa MFA obligatorio.
La base se recrea con Alembic (rol acma_owner) al inicio de la sesión de pruebas.
"""
import os
import subprocess
import sys
import uuid
from pathlib import Path



def cargar_env(ruta: Path) -> dict[str, str]:
    valores: dict[str, str] = {}
    if ruta.exists():
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            linea = linea.split(" #", 1)[0].strip()
            if linea and not linea.startswith("#") and "=" in linea:
                clave, _, valor = linea.partition("=")
                valores[clave.strip()] = valor.strip()
    return valores


RAIZ = Path(__file__).resolve().parents[2]
BACKEND = RAIZ / "backend"
_env = cargar_env(RAIZ / ".env")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or _env["TEST_DATABASE_URL"]
os.environ["DATABASE_READ_URL"] = ""
os.environ["TEST_DATABASE_MIGRATIONS_URL"] = os.environ.get("TEST_DATABASE_MIGRATIONS_URL") or _env["TEST_DATABASE_MIGRATIONS_URL"]
os.environ["DB_POOL_NULO"] = "true"
os.environ["MFA_OBLIGATORIO"] = "true"
os.environ["ALMACENAMIENTO_MODO"] = "memoria"
os.environ["ACMA_ENTORNO"] = "pruebas"
os.environ["TIEMPO_REAL_MODO"] = "local"
os.environ["VAPID_CLAVE_PUBLICA"] = ""
os.environ["VAPID_CLAVE_PRIVADA"] = ""
os.environ["SMTP_HOST"] = ""
os.environ["NOTIFICACIONES_ENVIO_INLINE"] = "true"

import pyotp  # noqa: E402
import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

URL_OWNER = os.environ["TEST_DATABASE_MIGRATIONS_URL"]


def _alembic(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "alembic", "-x", f"url={URL_OWNER}", *args], cwd=BACKEND, check=True,
                   capture_output=True)


def pytest_sessionstart(session) -> None:
    _alembic("downgrade", "base")
    _alembic("upgrade", "head")


@pytest.fixture(scope="session")
async def datos():
    """Datos demo (seed_dev) + un segundo tenant/prestador para pruebas de aislamiento."""
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from core.security import hashear_contrasena
    from models import Prestador, Tenant, TenantPrestador, UnidadNegocio, Usuario
    from models.base import Dominio, Rol
    from scripts.seed_dev import CONTRASENA_DEMO, sembrar
    from services import catalogos_service

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        await sembrar(db)
        # La captura evalua el horario de servicio del contrato con la hora real del servidor (§6.8.6, causa 7). Con el
        # horario del demo (L-V 08:00-20:00, sabado 09:00-14:00, domingo cerrado) el resultado de media suite cambiaba
        # segun la hora a la que se corriera: fuera de esa ventana cada folio capturado se iba a `en_revision`. En la
        # base de pruebas los contratos quedan abiertos los siete dias; la causa 7 tiene su propia prueba, que
        # estrecha la ventana y la restaura (`test_folios_captura.py::test_7_fuera_de_horario_del_contrato...`).
        from models.contratos import Contrato
        abierto = {d: [["00:00", "23:59"]] for d in
                   ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")}
        for contrato in (await db.execute(select(Contrato))).scalars():
            contrato.horario_servicio_json = abierto
        await db.flush()
        otro_prestador = Prestador(razon_social="Otro Prestador", rfc="OPR200101AA1")
        otro_tenant = Tenant(razon_social="Otro Cliente", rfc="OCL200101BB2")
        db.add_all([otro_prestador, otro_tenant])
        await db.flush()
        db.add(TenantPrestador(tenant_id=otro_tenant.id, prestador_id=otro_prestador.id))
        await catalogos_service.sembrar_niveles(db, otro_prestador.id)  # como lo hace POST /api/prestadores
        un_otro = UnidadNegocio(tenant_id=otro_tenant.id, codigo="OTRA-1", nombre="Unidad del otro cliente")
        db.add(un_otro)
        h = hashear_contrasena(CONTRASENA_DEMO)
        db.add_all([
            Usuario(email="admin.otro@acma.dev", nombre="Admin Otro", rol=Rol.admin_empresa, dominio=Dominio.tenant,
                    tenant_id=otro_tenant.id, password_hash=h),
            Usuario(email="operador.otro@acma.dev", nombre="Operador Otro", rol=Rol.operador, dominio=Dominio.tenant,
                    tenant_id=otro_tenant.id, password_hash=h),
            Usuario(email="admin.otroprestador@acma.dev", nombre="Admin Otro Prestador", rol=Rol.admin_prestador,
                    dominio=Dominio.prestador, prestador_id=otro_prestador.id, password_hash=h),
        ])
        await db.commit()
        demo_tenant = (await db.execute(select(Tenant).where(Tenant.rfc == "CDE200101XY2"))).scalar_one()
        demo_prestador = (await db.execute(select(Prestador).where(Prestador.rfc == "PDE200101AB1"))).scalar_one()
        unidades = (await db.execute(select(UnidadNegocio).where(UnidadNegocio.tenant_id == demo_tenant.id)
                                     .order_by(UnidadNegocio.codigo))).scalars().all()
        return {
            "tenant": demo_tenant.id, "prestador": demo_prestador.id, "unidades": [u.id for u in unidades],
            "otro_tenant": otro_tenant.id, "otro_prestador": otro_prestador.id, "un_otro": un_otro.id,
            "contrasena": CONTRASENA_DEMO,
        }


def nueva_ip() -> str:
    b = uuid.uuid4().bytes
    return f"10.{b[0]}.{b[1]}.{b[2] or 1}"


@pytest.fixture
def cliente_factory():
    from main import app

    def _crear(ip: str | None = None) -> AsyncClient:
        return AsyncClient(transport=ASGITransport(app=app, client=(ip or nueva_ip(), 50000)), base_url="http://prueba")

    return _crear


@pytest.fixture
async def cliente(cliente_factory):
    async with cliente_factory() as c:
        yield c


SECRETOS_MFA: dict[str, str] = {}
_TOKENS: dict[str, dict] = {}


async def olvidar_paso_totp(email: str) -> None:
    """Olvida el último paso TOTP consumido por ese usuario.

    P11a: el servidor no acepta dos veces el mismo paso de 30 s (§6.9.5). Varias pruebas necesitan usar más de un
    código dentro de la misma ventana, así que limpian la marca en lugar de esperar medio minuto.
    `test_totp_no_se_reutiliza` es la que verifica la regla.
    """
    from sqlalchemy import update

    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from models.usuarios import Usuario

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        await db.execute(update(Usuario).where(Usuario.email == email).values(mfa_ultimo_paso=None))
        await db.commit()


def csrf(cliente: AsyncClient) -> dict[str, str]:
    """Cabecera de doble envío que exigen /auth/refresh y /auth/logout (P11a)."""
    valor = cliente.cookies.get("acma_csrf")
    return {"X-ACMA-CSRF": valor} if valor else {}


async def refrescar(cliente: AsyncClient):
    """Renueva la sesión como lo hace el navegador: cookie httpOnly + cabecera CSRF."""
    return await cliente.post("/api/auth/refresh", headers=csrf(cliente))


async def iniciar_sesion(cliente: AsyncClient, email: str, contrasena: str) -> dict:
    """Login completo, resolviendo MFA (enrolamiento o verificación) cuando el rol lo exige. Devuelve los tokens.

    P11a: el refresh queda en la cookie `acma_refresh` del cliente; `tokens` solo trae el token de acceso.
    """
    r = await cliente.post("/api/auth/login", json={"email": email, "contrasena": contrasena})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    if not cuerpo["mfa_requerido"]:
        return cuerpo["tokens"]
    token_mfa = cuerpo["token_mfa"]
    if cuerpo["mfa_enrolamiento_requerido"]:
        setup = await cliente.post("/api/auth/mfa/setup", json={"token_mfa": token_mfa})
        assert setup.status_code == 200, setup.text
        SECRETOS_MFA[email] = setup.json()["secreto"]
    await olvidar_paso_totp(email)
    v = await cliente.post("/api/auth/mfa/verify",
                           json={"token_mfa": token_mfa, "codigo": pyotp.TOTP(SECRETOS_MFA[email]).now()})
    assert v.status_code == 200, v.text
    return v.json()["tokens"]


@pytest.fixture
def auth(datos, cliente_factory):
    """auth("operador@acma.dev") -> cabeceras Authorization (cacheadas por correo durante la sesión)."""

    async def _auth(email: str) -> dict[str, str]:
        import time

        # El acceso dura 15 min y la suite completa ya supera ese tiempo (P07): se vuelve a iniciar sesión a los 10 min.
        if email not in _TOKENS or time.monotonic() - _TOKENS[email].get("_emitido", 0) > 600:
            async with cliente_factory() as c:
                _TOKENS[email] = {**await iniciar_sesion(c, email, datos["contrasena"]), "_emitido": time.monotonic()}
        return {"Authorization": f"Bearer {_TOKENS[email]['access_token']}"}

    return _auth
