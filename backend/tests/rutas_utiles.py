"""Utilidades de las pruebas de optimización de rutas (§6.8.2, §6.8.4). F2-06.

Cada prueba arma **su propio mercado** con sus propias unidades y sus propios folios: el plan del día es único por
mercado y fecha, así que compartir el mercado del seed haría que las pruebas se pisaran entre sí.

El límite de cálculo se baja a 2 segundos: con media docena de folios la solución ya es la buena y la suite no se
puede permitir 30 segundos por llamada.
"""
import uuid
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select

from tests.folios_utiles import AP, DES, tipo_equipo

SEGUNDOS_LIMITE_PRUEBA = 2
TECNICOS = ["tecnico1@acma.dev", "tecnico2@acma.dev", "tecnico3@acma.dev", "tecnico4@acma.dev"]
# Qué habilidad certificada tiene cada técnico del demo (F2-01), para saber a quién puede tocarle un folio.
HABILIDADES = {
    "tecnico1@acma.dev": {"electricidad", "refrigeracion"},
    "tecnico2@acma.dev": {"electricidad", "hvac"},
    "tecnico3@acma.dev": {"electricidad", "plomeria"},
    "tecnico4@acma.dev": {"electricidad", "hvac", "iluminacion"},
}


async def resolver_prueba(problema: dict) -> dict:
    """Resuelve un problema sintético **por el contenedor `solver`**, que es donde corre el motor.

    No se llama a `modelo_ortools.resolver()` en proceso a propósito: cargar el binario nativo de OR-Tools dentro
    de pytest revienta el intérprete con un segmentation fault. El contenedor es además el camino real de este
    equipo, así que la prueba ejercita el mismo código por el mismo transporte que la aplicación.
    """
    from services.rutas.motor import _por_sidecar

    return await _por_sidecar(problema, int(problema.get("limite_s") or 2))


async def mercado(cliente, auth, datos, *, unidades: list | None = None, email=AP) -> dict:
    """Mercado nuevo del prestador demo con las unidades indicadas (por defecto, las tres del cliente)."""
    codigo = f"M{uuid.uuid4().hex[:6].upper()}"
    r = await cliente.post("/api/rutas/mercados", headers=await auth(email),
                           json={"codigo": codigo, "nombre": f"Mercado {codigo}",
                                 "centro_lat": 19.4326, "centro_lng": -99.1332})
    assert r.status_code == 201, r.text
    m = r.json()
    ids = [str(u) for u in (unidades if unidades is not None else datos["unidades"])]
    r = await cliente.post(f"/api/rutas/mercados/{m['id']}/unidades", headers=await auth(email),
                           json={"un_ids": ids})
    assert r.status_code == 200, r.text
    return m


async def configurar(cliente, auth, *, email=AP, **cambios) -> dict:
    cuerpo = {"segundos_limite_calculo": SEGUNDOS_LIMITE_PRUEBA, **cambios}
    r = await cliente.put("/api/rutas/configuracion", headers=await auth(email), json=cuerpo)
    assert r.status_code == 200, r.text
    return r.json()


async def jornadas_abiertas(emails: list[str] | None = None) -> int:
    """Abre jornada a los técnicos indicados: sin jornada no entran al plan del día."""
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from models.catalogos import Tecnico
    from models.operaciones import EstadoJornada, JornadaTecnico
    from models.usuarios import Usuario

    abiertas = 0
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        for email in (emails or TECNICOS):
            fila = (await db.execute(select(Tecnico, Usuario).join(Usuario, Usuario.id == Tecnico.usuario_id)
                                     .where(Usuario.email == email))).first()
            if fila is None:
                continue
            tecnico, _ = fila
            ya = (await db.execute(select(JornadaTecnico).where(
                JornadaTecnico.tecnico_id == tecnico.id,
                JornadaTecnico.estado == EstadoJornada.activa))).scalars().first()
            if ya is not None:
                continue
            db.add(JornadaTecnico(prestador_id=tecnico.prestador_id, tecnico_id=tecnico.id,
                                  inicio=datetime.now(UTC) - timedelta(hours=1), estado=EstadoJornada.activa,
                                  aviso_aceptado_at=datetime.now(UTC) - timedelta(days=3)))
            abiertas += 1
        await db.commit()
    return abiertas


async def cerrar_jornadas() -> None:
    """Cierra todas las jornadas activas: lo usan las pruebas que necesitan un parque sin técnicos."""
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from models.operaciones import CerradaPorJornada, EstadoJornada, JornadaTecnico

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        for j in (await db.execute(select(JornadaTecnico).where(
                JornadaTecnico.estado == EstadoJornada.activa))).scalars():
            j.estado = EstadoJornada.cerrada
            j.fin = datetime.now(UTC)
            j.cerrada_por = CerradaPorJornada.sistema   # lo exige el CHECK `ck_jornadas_cerrada` de 0015
        await db.commit()


async def folios_del_dia(cliente, auth, datos, cantidad: int = 4, *, familia="Refrigeración",
                         un_index: int = 0, ventana: tuple[int, int] | None = None,
                         estado: str = "autorizado") -> list[dict]:
    """Folios abiertos de hoy escritos directo, como el histórico sintético de P10.

    Por la API serían cuatro llamadas por folio (capturar, confirmar, autorizar) y lo que se prueba aquí es el
    ruteo, no la captura: eso ya lo cubre `test_folios_captura.py`.
    """
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from models.catalogos import Equipo, FamiliaEquipo, NivelSeveridadCatalogo, TipoEquipo, TipoFalla
    from models.folios import EstadoFolio, Folio, SeveridadOrigen, TipoFolio
    from models.organizaciones import Prestador
    from models.usuarios import Usuario

    creados = []
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        prestador = (await db.execute(select(Prestador).where(Prestador.rfc == "PDE200101AB1"))).scalar_one()
        operador = (await db.execute(select(Usuario).where(Usuario.email == "operador@acma.dev"))).scalar_one()
        fam = (await db.execute(select(FamiliaEquipo).where(FamiliaEquipo.nombre == familia))).scalar_one()
        un_id = datos["unidades"][un_index]
        equipos = list((await db.execute(
            select(Equipo).join(TipoEquipo, TipoEquipo.id == Equipo.tipo_equipo_id)
            .where(Equipo.tenant_id == datos["tenant"], Equipo.un_id == un_id,
                   TipoEquipo.familia_id == fam.id).limit(max(1, cantidad)))).scalars())
        assert equipos, f"no hay equipos de {familia} en la unidad {un_index}"
        falla = (await db.execute(select(TipoFalla).where(TipoFalla.prestador_id == prestador.id))).scalars().first()
        severidad = (await db.execute(select(NivelSeveridadCatalogo).where(
            NivelSeveridadCatalogo.prestador_id == prestador.id)
            .order_by(NivelSeveridadCatalogo.orden))).scalars().first()
        inicio = datetime.combine(date.today(), time(8, 0), tzinfo=UTC)
        for i in range(cantidad):
            equipo = equipos[i % len(equipos)]
            folio = Folio(
                tenant_id=datos["tenant"], prestador_id=prestador.id, un_id=equipo.un_id, equipo_id=equipo.id,
                numero_folio=f"PR-{uuid.uuid4().hex[:10].upper()}", tipo_folio=TipoFolio.correctivo,
                estado=EstadoFolio(estado), descripcion=f"Folio de ruta {i + 1} para la prueba",
                tipo_falla_id=falla.id if falla else None,
                severidad_id=severidad.id if severidad else None,
                severidad_origen=SeveridadOrigen.automatica_matriz, confirmacion_un=True,
                capturado_por=operador.id, capturado_at=datetime.now(UTC) - timedelta(hours=2),
                fecha_falla=datetime.now(UTC) - timedelta(hours=3),
                ventana_inicio=inicio + timedelta(hours=ventana[0] - 8) if ventana else None,
                ventana_fin=inicio + timedelta(hours=ventana[1] - 8) if ventana else None)
            db.add(folio)
            await db.flush()
            creados.append({"id": str(folio.id), "numero_folio": folio.numero_folio,
                            "equipo_id": str(equipo.id), "un_id": str(equipo.un_id)})
        await db.commit()
    return creados


async def calcular(cliente, auth, mercado_id, *, email=DES, esperado=200, fecha=None) -> dict:
    cuerpo = {"mercado_id": str(mercado_id)}
    if fecha is not None:
        cuerpo["fecha"] = fecha.isoformat()
    r = await cliente.post("/api/rutas/calcular", headers=await auth(email), json=cuerpo)
    assert r.status_code == esperado, r.text
    return r.json()


async def publicar(cliente, auth, plan_id, *, email=DES, esperado=200) -> dict:
    r = await cliente.post(f"/api/rutas/{plan_id}/publicar", headers=await auth(email))
    assert r.status_code == esperado, r.text
    return r.json()


async def plan(cliente, auth, plan_id, *, email=DES) -> dict:
    r = await cliente.get(f"/api/rutas/{plan_id}", headers=await auth(email))
    assert r.status_code == 200, r.text
    return r.json()


def paradas_de(detalle: dict) -> list[dict]:
    return [p for ruta in detalle["rutas"] for p in ruta["paradas"]]


def tecnico_de(detalle: dict, folio_id: str) -> str | None:
    for ruta in detalle["rutas"]:
        for p in ruta["paradas"]:
            if p["folio_id"] == str(folio_id):
                return ruta["tecnico_id"]
    return None


def sin_asignar(detalle: dict) -> dict[str, str]:
    return {x["folio_id"]: x.get("motivo", "") for x in detalle["plan"]["sin_asignar"]}


async def usuario_id(email: str):
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from models.usuarios import Usuario

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        return (await db.execute(select(Usuario.id).where(Usuario.email == email))).scalar_one()


async def posiciones(email: str, puntos: list[tuple[float, float]], *, desde_min: int = 12,
                     paso_min: int = 2) -> int:
    """Siembra posiciones GPS de un técnico, de la más vieja a la más nueva (F2-03)."""
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from models.catalogos import Tecnico
    from models.operaciones import EstadoJornada, JornadaTecnico, TecnicoPosicion
    from models.usuarios import Usuario

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        tecnico, _ = (await db.execute(select(Tecnico, Usuario).join(Usuario, Usuario.id == Tecnico.usuario_id)
                                       .where(Usuario.email == email))).one()
        jornada = (await db.execute(select(JornadaTecnico).where(
            JornadaTecnico.tecnico_id == tecnico.id,
            JornadaTecnico.estado == EstadoJornada.activa))).scalars().first()
        assert jornada is not None, f"{email} no tiene jornada activa"
        ahora = datetime.now(UTC)
        for i, (lat, lng) in enumerate(puntos):
            db.add(TecnicoPosicion(
                prestador_id=tecnico.prestador_id, tecnico_id=tecnico.id, jornada_id=jornada.id,
                posicion=func.ST_GeogFromText(f"POINT({lng} {lat})"), precision_m=10,
                capturada_at=ahora - timedelta(minutes=desde_min - paso_min * i)))
        lat, lng = puntos[-1]
        tecnico.ultima_posicion = func.ST_GeogFromText(f"POINT({lng} {lat})")
        tecnico.ultima_posicion_at = ahora
        await db.commit()
    return len(puntos)
