"""Contenido de servicio contractual (§6.10.4): confidencial del cliente, con puntos de revisión estructurados,
versiones y avisos de coherencia con la iguala del contrato de P10. F2-01."""
import uuid

from sqlalchemy import select, text

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA, ContextoRLS
from models.capacitacion import ContenidoServicio
from tests.capacitacion_utiles import tipo_equipo_id
from tests.folios_utiles import AE, AP, AUN, DES, MC, OP, OTRO_AE, SA, TEC, accion, autorizar_sin_flujo, nuevo_equipo
from tests.sla_utiles import contrato_demo

PUNTOS = [
    {"clave": "limpieza", "descripcion": "Limpieza de condensador", "obligatorio": True},
    {"clave": "temperatura", "descripcion": "Registro de temperatura", "obligatorio": True},
    {"descripcion": "Fotografía del equipo", "obligatorio": False},
]


async def _guardar(cliente, auth, tipo_eq, contrato_id, *, email=AE, esperado=201, **extra):
    cuerpo = {"tipo_equipo_id": tipo_eq, "contrato_id": contrato_id, "titulo": "Rutina contractual",
              "puntos_revision": PUNTOS, "periodicidad": "mensual", **extra}
    r = await cliente.post("/api/biblioteca/contenido", headers=await auth(email), json=cuerpo)
    assert r.status_code == esperado, r.text
    return r.json()


async def test_el_cliente_define_los_puntos_de_revision(cliente, auth, datos):
    contrato = await contrato_demo(cliente, auth)
    tipo = await tipo_equipo_id(cliente, auth, "Cámara de congelación")
    guardado = await _guardar(cliente, auth, tipo, contrato["id"])
    contenido = guardado["contenido"]
    assert contenido["version"] == 1 and contenido["periodicidad"] == "mensual"
    # Los puntos quedan ordenados y con clave, incluso el que no la traía.
    assert [p["orden"] for p in contenido["puntos_revision"]] == [1, 2, 3]
    assert contenido["puntos_revision"][2]["clave"] == "punto_3"
    assert contenido["puntos_revision"][0]["obligatorio"] is True

    # Un punto sin descripción se rechaza: una lista de puntos vacíos no sirve de nada.
    r = await cliente.post("/api/biblioteca/contenido", headers=await auth(AE),
                           json={"tipo_equipo_id": tipo, "contrato_id": contrato["id"], "titulo": "Mala",
                                 "puntos_revision": [{"descripcion": "  "}]})
    assert r.status_code == 422


async def test_avisa_cuando_no_coincide_con_la_iguala_del_contrato(cliente, auth, datos):
    """P10 + §6.10.4: se avisa y no se bloquea (decisión anotada)."""
    contrato = await contrato_demo(cliente, auth)
    tipo = await tipo_equipo_id(cliente, auth, "Aire acondicionado central")
    incluidos = contrato.get("folios_correctivos_iguala")
    guardado = await _guardar(cliente, auth, tipo, contrato["id"],
                              correctivos_iguala=(incluidos or 0) + 7)
    assert guardado["avisos"], "debería avisar que no coincide con el contrato"
    assert "correctivos" in guardado["avisos"][0]
    assert guardado["contenido"]["id"], "pero el contenido se guarda igual"

    # Con el mismo número que el contrato, no hay avisos.
    limpio = await _guardar(cliente, auth, tipo, contrato["id"], correctivos_iguala=incluidos)
    assert limpio["avisos"] == []


async def test_la_version_nueva_archiva_la_anterior(cliente, auth, datos):
    contrato = await contrato_demo(cliente, auth)
    tipo = await tipo_equipo_id(cliente, auth, "Anuncio luminoso")
    primero = (await _guardar(cliente, auth, tipo, contrato["id"]))["contenido"]
    segundo = (await _guardar(cliente, auth, tipo, contrato["id"], titulo="Rutina revisada"))["contenido"]
    assert segundo["version"] == primero["version"] + 1

    vigentes = (await cliente.get("/api/biblioteca/contenido", headers=await auth(AE),
                                  params={"tipo_equipo_id": tipo})).json()
    assert [c["id"] for c in vigentes] == [segundo["id"]], "solo uno vigente por contrato y tipo de equipo"
    con_historial = (await cliente.get("/api/biblioteca/contenido", headers=await auth(AE),
                                       params={"tipo_equipo_id": tipo, "incluir_inactivos": True})).json()
    assert primero["id"] in {c["id"] for c in con_historial}


async def test_el_prestador_lo_ve_pero_no_lo_escribe(cliente, auth, datos):
    """§6.10.4: lo sube el Admin empresa; el prestador que lo atiende lo consulta."""
    contrato = await contrato_demo(cliente, auth)
    tipo = await tipo_equipo_id(cliente, auth, "Refrigerador vertical")
    for email in (AP, MC, DES):
        lista = (await cliente.get("/api/biblioteca/contenido", headers=await auth(email))).json()
        assert any(c["tipo_equipo_id"] == tipo for c in lista), f"{email} debería ver el contenido del cliente"
    r = await cliente.post("/api/biblioteca/contenido", headers=await auth(AP),
                           json={"tipo_equipo_id": tipo, "contrato_id": contrato["id"], "titulo": "Del prestador",
                                 "puntos_revision": PUNTOS})
    assert r.status_code == 403


async def test_otro_cliente_del_mismo_prestador_no_lo_ve(cliente, auth, datos):
    """El caso que §6.10.4 llama confidencial: otro tenant del MISMO prestador no debe verlo, ni por HTTP ni en la base."""
    h = await auth(SA)
    sufijo = uuid.uuid4().hex[:3].upper()
    nuevo = (await cliente.post("/api/tenants", headers=h,
                                json={"razon_social": f"Cliente vecino {sufijo}",
                                      "rfc": f"CVE010101{sufijo}"})).json()
    v = await cliente.post(f"/api/tenants/{nuevo['id']}/prestadores", headers=h,
                           json={"prestador_id": str(datos["prestador"])})
    assert v.status_code == 201, v.text
    correo = f"admin.vecino.{sufijo.lower()}@acma.dev"
    u = await cliente.post("/api/usuarios", headers=h, json={
        "email": correo, "nombre": "Admin Vecino", "rol": "admin_empresa",
        # La misma contraseña del seed: la fixture `auth` inicia sesión con ella.
        "contrasena": datos["contrasena"], "tenant_id": nuevo["id"]})
    assert u.status_code == 201, u.text

    # Por HTTP: el vecino no ve nada del cliente demo.
    lista = (await cliente.get("/api/biblioteca/contenido", headers=await auth(correo))).json()
    assert all(c["tenant_id"] == nuevo["id"] for c in lista), lista

    # Y en la base, con su propio contexto RLS, tampoco.
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        from models.usuarios import Usuario

        usuario = (await db.execute(select(Usuario).where(Usuario.email == correo))).scalar_one()
    contexto = ContextoRLS(usuario_id=usuario.id, tenant_id=usuario.tenant_id, prestador_id=None,
                           rol=usuario.rol.value)
    async with nueva_sesion(contexto) as db:
        filas = (await db.execute(select(ContenidoServicio.tenant_id))).scalars().all()
        assert all(t == usuario.tenant_id for t in filas), "la RLS debe ocultar el contenido de otros clientes"


async def test_el_tecnico_solo_ve_el_contenido_de_sus_folios(cliente, auth, datos):
    """§6.10.4: el técnico consulta los puntos del cliente **solo** de los folios que tiene asignados."""
    contrato = await contrato_demo(cliente, auth)
    equipo = await nuevo_equipo(cliente, auth, datos, familia="Refrigeración")
    tipo_del_folio = equipo["tipo_equipo_id"]
    await _guardar(cliente, auth, tipo_del_folio, contrato["id"], titulo="Puntos del folio asignado")
    # Un tipo de equipo que el técnico no atiende hoy.
    otro_tipo = await tipo_equipo_id(cliente, auth, "Lámpara LED de techo")
    await _guardar(cliente, auth, otro_tipo, contrato["id"], titulo="Puntos de iluminación")

    # Sin folios asignados de ese tipo, no ve nada de ese tipo.
    antes = (await cliente.get("/api/biblioteca/contenido", headers=await auth(TEC))).json()
    assert otro_tipo not in {c["tipo_equipo_id"] for c in antes}

    folio = await autorizar_sin_flujo(cliente, auth, datos, OP, equipo=equipo)
    from tests.folios_utiles import tecnico_con_habilidades

    tec = await tecnico_con_habilidades(cliente, auth, TEC, ["refrigeracion", "electricidad"])
    await accion(cliente, auth, DES, folio["id"], "asignar", {"tecnico_id": tec})

    despues = (await cliente.get("/api/biblioteca/contenido", headers=await auth(TEC))).json()
    tipos = {c["tipo_equipo_id"] for c in despues}
    assert tipo_del_folio in tipos, "el técnico debe ver los puntos del folio que le asignaron"
    assert otro_tipo not in tipos, "y no los de un tipo de equipo que no atiende"


async def test_el_operador_del_cliente_no_define_el_contenido(cliente, auth, datos):
    contrato = await contrato_demo(cliente, auth)
    tipo = await tipo_equipo_id(cliente, auth)
    r = await cliente.post("/api/biblioteca/contenido", headers=await auth(OP),
                           json={"tipo_equipo_id": tipo, "contrato_id": contrato["id"], "titulo": "Del operador",
                                 "puntos_revision": PUNTOS})
    assert r.status_code == 403
    # El Admin UN lo consulta pero no lo define (§6.10.4: lo sube el Admin empresa).
    assert (await cliente.get("/api/biblioteca/contenido", headers=await auth(AUN))).status_code == 200
    r = await cliente.post("/api/biblioteca/contenido", headers=await auth(AUN),
                           json={"tipo_equipo_id": tipo, "contrato_id": contrato["id"], "titulo": "Del admin UN",
                                 "puntos_revision": PUNTOS})
    assert r.status_code == 403


async def test_el_contrato_debe_ser_del_cliente(cliente_factory, auth, datos):
    async with cliente_factory() as c:
        contrato = await contrato_demo(c, auth)
        tipo = await tipo_equipo_id(c, auth)
        r = await c.post("/api/biblioteca/contenido", headers=await auth(OTRO_AE),
                         json={"tipo_equipo_id": tipo, "contrato_id": contrato["id"], "titulo": "Ajeno",
                               "puntos_revision": PUNTOS})
        assert r.status_code == 404, r.text
