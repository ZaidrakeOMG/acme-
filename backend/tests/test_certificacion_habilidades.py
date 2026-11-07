"""La certificación que alimenta la habilidad (§6.10.3) y su consecuencia en la asignación (§6.8.6, P04/P06). F2-01.

Lo que se verifica aquí es la cadena completa: un curso aprobado certifica la habilidad, el vencimiento la retira y,
desde ese día, la restricción dura de asignación bloquea a ese técnico salvo el permiso con razón.
"""
from datetime import date, timedelta

from sqlalchemy import select, update

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from models.capacitacion import TecnicoCurso
from models.catalogos import Habilidad, OrigenHabilidad, Tecnico, TecnicoHabilidad
from tests.capacitacion_utiles import HOY, crear_curso, expediente, ficha_tecnico, habilidades, registrar
from tests.folios_utiles import AP, DES, OP, SA, TEC, TEC2, TEC4, accion, autorizar_sin_flujo, nuevo_equipo

TEC3 = "tecnico3@acma.dev"   # el seed lo crea en TECNICOS_NUEVOS y folios_utiles no lo exporta


async def _recalcular() -> dict:
    """Corre la tarea diaria con el rol sistema, como lo hace Celery."""
    from services import capacitacion_service

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        resumen = await capacitacion_service.recalcular_estados(db)
        await db.commit()
        return resumen


async def _habilidad(email: str, clave: str) -> TecnicoHabilidad | None:
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        from models.usuarios import Usuario

        fila = (await db.execute(
            select(TecnicoHabilidad).join(Tecnico, Tecnico.id == TecnicoHabilidad.tecnico_id)
            .join(Usuario, Usuario.id == Tecnico.usuario_id)
            .join(Habilidad, Habilidad.id == TecnicoHabilidad.habilidad_id)
            .where(Usuario.email == email, Habilidad.clave == clave))).scalar_one_or_none()
        return fila


async def test_un_curso_aprobado_certifica_la_habilidad_y_uno_reprobado_no(cliente, auth, datos):
    habs = await habilidades(cliente, auth)
    curso = await crear_curso(cliente, auth, f"Plomería certificada {HOY}", vigencia_meses=24,
                              habilidad_id=habs["plomeria"], tipo="certificacion")
    tecnico = await ficha_tecnico(cliente, auth, TEC2)

    # Reprobado: no certifica nada.
    exp = await registrar(cliente, auth, tecnico["id"], curso["id"], fecha_fin=HOY - timedelta(days=30),
                          aprobado=False, calificacion=50)
    assert not any(h["habilidad_id"] == habs["plomeria"] and h["certificada"] for h in exp["habilidades"])

    # Aprobado: la habilidad queda certificada con origen «curso» y la vigencia del curso.
    exp = await registrar(cliente, auth, tecnico["id"], curso["id"], fecha_fin=HOY - timedelta(days=5),
                          aprobado=True, calificacion=90)
    fila = next(h for h in exp["habilidades"] if h["habilidad_id"] == habs["plomeria"])
    assert fila["certificada"] is True and fila["origen"] == "curso"
    assert fila["fecha_certificacion"] == str(HOY - timedelta(days=5))
    assert fila["estado"] == "vigente"


async def test_la_habilidad_declarada_a_mano_gana_sobre_el_curso(cliente, auth, datos):
    """Regla elegida: si el prestador la afirmó a mano, el curso queda como respaldo y no la pisa."""
    habs = await habilidades(cliente, auth)
    tecnico = await ficha_tecnico(cliente, auth, TEC4)
    # Se declara a mano, sin vigencia.
    r = await cliente.put(f"/api/catalogos/tecnicos/{tecnico['id']}/habilidades", headers=await auth(AP),
                          json={"habilidades": [{"habilidad_id": habs["plomeria"], "certificada": True}]})
    assert r.status_code == 200, r.text
    assert (await _habilidad(TEC4, "plomeria")).origen == OrigenHabilidad.manual

    curso = await crear_curso(cliente, auth, f"Plomería respaldo {HOY}", vigencia_meses=12,
                              habilidad_id=habs["plomeria"])
    exp = await registrar(cliente, auth, tecnico["id"], curso["id"], fecha_fin=HOY - timedelta(days=2))
    fila = next(h for h in exp["habilidades"] if h["habilidad_id"] == habs["plomeria"])
    assert fila["origen"] == "manual", "la declaración del prestador manda"
    # El curso igual quedó registrado como respaldo documental.
    assert any(c["curso_id"] == curso["id"] for c in exp["cursos"])


async def test_el_vencimiento_retira_la_habilidad_y_bloquea_la_asignacion(cliente, auth, datos):
    """§6.10.3 + §6.8.6: al vencer la certificación, el técnico deja de poder recibir ese trabajo."""
    habs = await habilidades(cliente, auth)
    curso = await crear_curso(cliente, auth, f"Refrigeración vencible {HOY}", vigencia_meses=12,
                              habilidad_id=habs["refrigeracion"], tipo="certificacion")
    tecnico = await ficha_tecnico(cliente, auth, TEC3)
    usuario_id = tecnico["usuario_id"]

    # Solo esta habilidad, y certificada por el curso.
    await cliente.put(f"/api/catalogos/tecnicos/{tecnico['id']}/habilidades", headers=await auth(AP),
                      json={"habilidades": []})
    exp = await registrar(cliente, auth, tecnico["id"], curso["id"], fecha_fin=HOY - timedelta(days=10))
    fila = next(h for h in exp["habilidades"] if h["habilidad_id"] == habs["refrigeracion"])
    assert fila["certificada"] is True and fila["origen"] == "curso"

    # Con la certificación vigente, el despachador puede asignarlo.
    folio = await autorizar_sin_flujo(cliente, auth, datos, OP,
                                      equipo=await nuevo_equipo(cliente, auth, datos, familia="Refrigeración"))
    await accion(cliente, auth, DES, folio["id"], "asignar", {"tecnico_id": usuario_id})

    # Se envejece la certificación y corre la tarea diaria.
    registro_id = next(c["id"] for c in exp["cursos"] if c["curso_id"] == curso["id"])
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        await db.execute(update(TecnicoCurso).where(TecnicoCurso.id == registro_id)
                         .values(vigente_hasta=HOY - timedelta(days=1)))
        await db.commit()
    resumen = await _recalcular()
    assert resumen["habilidades_retiradas"] >= 1, resumen

    retirada = await _habilidad(TEC3, "refrigeracion")
    assert retirada is not None and retirada.certificada is False, "la habilidad debe quedar sin certificar"

    # Desde ese día, asignar a ese técnico un folio que exige la habilidad se bloquea.
    otro = await autorizar_sin_flujo(cliente, auth, datos, OP,
                                     equipo=await nuevo_equipo(cliente, auth, datos, familia="Refrigeración"))
    r = await cliente.post(f"/api/folios/{otro['id']}/asignar", headers=await auth(DES),
                           json={"tecnico_id": usuario_id})
    assert r.status_code == 409 and r.json()["codigo"] == "TECNICO_SIN_HABILIDAD", r.text

    # Con el permiso `asignar_tecnico_sin_habilidad` y razón, sí se puede (§6.8.3).
    h = await auth(AP)
    desp = (await cliente.get("/api/usuarios", headers=h, params={"rol": "despachador"})).json()[0]
    permiso = {"despachador_id": desp["id"], "tenant_id": str(datos["tenant"])}
    r = await cliente.put("/api/configuracion/permisos-despachador", headers=h,
                          json={"valores": {"asignar_tecnico_sin_habilidad": True}, **permiso})
    assert r.status_code == 200, r.text
    try:
        sin_razon = await cliente.post(f"/api/folios/{otro['id']}/asignar", headers=await auth(DES),
                                       json={"tecnico_id": usuario_id})
        assert sin_razon.status_code == 422 and sin_razon.json()["codigo"] == "RAZON_REQUERIDA"
        con_razon = await cliente.post(f"/api/folios/{otro['id']}/asignar", headers=await auth(DES),
                                       json={"tecnico_id": usuario_id, "razon": "Urgencia: es el único disponible"})
        assert con_razon.status_code == 200, con_razon.text
    finally:
        await cliente.put("/api/configuracion/permisos-despachador", headers=h,
                          json={"valores": {"asignar_tecnico_sin_habilidad": False}, **permiso})


async def test_el_retiro_queda_en_la_auditoria_y_dispara_su_alerta(cliente, auth, datos):
    """Cada habilidad retirada por vencimiento se registra y avisa (§6.9.5, §6.9.6)."""
    await _recalcular()   # el seed deja una certificación vencida de electricidad
    eventos = (await cliente.get("/api/auditoria/eventos", headers=await auth(SA),
                                 params={"evento_tipo": "capacitacion.habilidad_retirada_por_vencimiento",
                                         "limite": 50})).json()
    assert eventos, "el retiro por vencimiento debe quedar en audit_log"
    assert eventos[0]["actor_rol"] == "sistema"

    alertas = (await cliente.get("/api/alertas/historial", headers=await auth(AP),
                                 params={"clave": "CERTIFICACION_VENCIDA_HABILIDAD_RETIRADA", "limite": 50})).json()
    assert alertas, "debe quedar la alerta del día en que se retira la habilidad"


async def test_la_tarea_no_retira_lo_que_otro_curso_vigente_respalda(cliente, auth, datos):
    """Dos cursos de la misma habilidad: mientras uno siga vigente, la certificación se queda."""
    habs = await habilidades(cliente, auth)
    tecnico = await ficha_tecnico(cliente, auth, TEC)
    viejo = await crear_curso(cliente, auth, f"Iluminación viejo {HOY}", vigencia_meses=12,
                              habilidad_id=habs["iluminacion"])
    nuevo = await crear_curso(cliente, auth, f"Iluminación nuevo {HOY}", vigencia_meses=36,
                              habilidad_id=habs["iluminacion"])
    exp = await registrar(cliente, auth, tecnico["id"], viejo["id"], fecha_fin=HOY - timedelta(days=20))
    viejo_id = next(c["id"] for c in exp["cursos"] if c["curso_id"] == viejo["id"])
    await registrar(cliente, auth, tecnico["id"], nuevo["id"], fecha_fin=HOY - timedelta(days=5))

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        await db.execute(update(TecnicoCurso).where(TecnicoCurso.id == viejo_id)
                         .values(vigente_hasta=HOY - timedelta(days=1)))
        await db.commit()
    await _recalcular()

    fila = await _habilidad(TEC, "iluminacion")
    assert fila is not None and fila.certificada is True, "el curso nuevo sigue respaldando la habilidad"
