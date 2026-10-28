"""Calendario de preventivos (§7.6): carga manual por fila y por importador, consulta por rol, edición, publicación del mes
con notificación, texto literal de desvío y generación de folios desde el calendario manual."""
from datetime import date

from services import notificaciones
from services.preventivos_service import texto_desvio
from tests.folios_utiles import AE, AP, AUN, DES, MC, OP, OTRO_AE, OTRO_AP, SUPO, TEC, nuevo_equipo, tecnico_usuario_id
from tests.preventivos_utiles import calendario, generar, nuevo_plan


def test_texto_desvio_literal():
    """§7.6: «realizado 2 días antes de lo programado» o «realizado con 4 días de retraso»."""
    assert texto_desvio(0) == "realizado en la fecha programada"
    assert texto_desvio(4) == "realizado con 4 días de retraso"
    assert texto_desvio(1) == "realizado con 1 día de retraso"
    assert texto_desvio(-2) == "realizado 2 días antes de lo programado"
    assert texto_desvio(-1) == "realizado 1 día antes de lo programado"
    assert texto_desvio(None) == "pendiente de ejecución"


async def test_cargar_consultar_y_editar(cliente, auth, datos):
    equipo = await nuevo_equipo(cliente, auth, datos)
    tec = await tecnico_usuario_id(cliente, auth, TEC)
    filas = [{"un_id": str(datos["unidades"][0]), "equipo_id": equipo["id"], "fecha_programada": "2027-03-10", "descripcion": "Limpieza"},
             {"un_id": str(datos["unidades"][2]), "fecha_programada": "2027-03-12", "tecnico_id": tec, "descripcion": "Revisión de la UN completa"}]
    r = await cliente.post("/api/preventivos/calendario", headers=await auth(DES), json={"tenant_id": str(datos["tenant"]), "filas": filas})
    assert r.status_code == 201, r.text
    creadas = r.json()
    assert [c["estado"] for c in creadas] == ["programado", "programado"] and creadas[0]["equipo_codigo"] == equipo["codigo"] and creadas[1]["equipo_id"] is None
    assert creadas[0]["origen"] == "manual" and creadas[0]["texto_desvio"] == "pendiente de ejecución" and creadas[1]["tecnico_nombre"]
    mes = await calendario(cliente, auth, DES, mes="2027-03")
    assert {c["id"] for c in creadas} <= {c["id"] for c in mes}
    # Roles del cliente: Admin empresa ve todo; Admin UN solo sus UNs; el operador no consulta.
    assert {c["id"] for c in creadas} <= {c["id"] for c in await calendario(cliente, auth, AE, mes="2027-03")}
    assert all(c["id"] != creadas[1]["id"] for c in await calendario(cliente, auth, AUN, mes="2027-03"))  # admin.un está en las UN 0 y 1
    assert creadas[0]["id"] in {c["id"] for c in await calendario(cliente, auth, AUN, mes="2027-03")}
    assert (await cliente.get("/api/preventivos/calendario", headers=await auth(OP), params={"mes": "2027-03"})).status_code == 403
    assert all(c["id"] not in {x["id"] for x in creadas} for c in await calendario(cliente, auth, OTRO_AE, mes="2027-03"))
    assert all(c["id"] not in {x["id"] for x in creadas} for c in await calendario(cliente, auth, OTRO_AP, mes="2027-03"))
    # Validaciones: UN de otro cliente, equipo de otra UN, técnico ajeno.
    r = await cliente.post("/api/preventivos/calendario", headers=await auth(DES), json={"tenant_id": str(datos["tenant"]), "filas": [
        {"un_id": str(datos["un_otro"]), "fecha_programada": "2027-03-01"}]})
    assert r.status_code == 422 and r.json()["codigo"] == "UNIDAD_INVALIDA"
    r = await cliente.post("/api/preventivos/calendario", headers=await auth(DES), json={"tenant_id": str(datos["tenant"]), "filas": [
        {"un_id": str(datos["unidades"][1]), "equipo_id": equipo["id"], "fecha_programada": "2027-03-01"}]})
    assert r.status_code == 422 and r.json()["codigo"] == "EQUIPO_INVALIDO"
    # Edición: técnico y fecha mientras no hay folio; Mesa de control también edita; el técnico no.
    r = await cliente.patch(f"/api/preventivos/calendario/{creadas[0]['id']}", headers=await auth(MC), json={"tecnico_id": tec, "fecha_programada": "2027-03-11"})
    assert r.status_code == 200 and r.json()["tecnico_id"] == tec and r.json()["fecha_programada"] == "2027-03-11" and r.json()["fecha_programada_original"] == "2027-03-10"
    assert (await cliente.patch(f"/api/preventivos/calendario/{creadas[0]['id']}", headers=await auth(TEC), json={"descripcion": "x"})).status_code == 403


async def test_publicar_mes_notifica_al_cliente(cliente, auth, datos):
    equipo = await nuevo_equipo(cliente, auth, datos)
    r = await cliente.post("/api/preventivos/calendario", headers=await auth(DES), json={"tenant_id": str(datos["tenant"]), "filas": [
        {"un_id": str(datos["unidades"][0]), "equipo_id": equipo["id"], "fecha_programada": "2027-05-20"}]})
    assert r.status_code == 201
    r = await cliente.post("/api/preventivos/calendario/publicar", headers=await auth(DES), params={"mes": "2027-05", "tenant_id": str(datos["tenant"])})
    assert r.status_code == 200, r.text
    pub = r.json()
    assert pub["mes"] == "2027-05-01" and pub["total_preventivos"] >= 1 and pub["publicado_por"]
    # ENVIADAS es un deque acotado: se busca la notificación por su contenido, no por posición.
    nuevas = [n for n in notificaciones.ENVIADAS if n["datos"].get("evento") == "calendario.publicado" and n["roles"] and n["datos"].get("mes") == "2027-05-01"]
    assert nuevas and nuevas[-1]["roles"] == ["admin_empresa", "admin_un"] and len(nuevas[-1]["usuarios"]) >= 2 and "email" in nuevas[-1]["canales"]
    assert nuevas[-1]["datos"]["mes"] == "2027-05-01" and nuevas[-1]["tenant_id"] == str(datos["tenant"])
    # Publicar otra vez el mismo mes actualiza la publicación (no duplica).
    r = await cliente.post("/api/preventivos/calendario/publicar", headers=await auth(AP), params={"mes": "2027-05", "tenant_id": str(datos["tenant"])})
    assert r.status_code == 200 and r.json()["id"] == pub["id"]
    lista = (await cliente.get("/api/preventivos/calendario/publicaciones", headers=await auth(AE))).json()
    assert any(p["id"] == pub["id"] for p in lista)
    assert (await cliente.post("/api/preventivos/calendario/publicar", headers=await auth(AE), params={"mes": "2027-05"})).status_code == 403
    r = await cliente.post("/api/preventivos/calendario/publicar", headers=await auth(DES), params={"mes": "2031-01", "tenant_id": str(datos["tenant"])})
    assert r.status_code == 409 and r.json()["codigo"] == "MES_VACIO"


async def test_importar_calendario_por_csv(cliente, auth, datos):
    plan = await nuevo_plan(cliente, auth)
    equipo = await nuevo_equipo(cliente, auth, datos)
    h = await auth(AP)
    cat = (await cliente.get("/api/catalogos/importar/catalogos", headers=h)).json()
    assert any(c["clave"] == "calendario_preventivos" for c in cat)
    un = (await cliente.get(f"/api/unidades-negocio/{datos['unidades'][0]}", headers=await auth(AE))).json()
    csv = "cliente,un_codigo,fecha,equipo_codigo,plan,tecnico_email,descripcion\n" \
          f"CDE200101XY2,{un['codigo']},2027-06-15,{equipo['codigo']},{plan['nombre']},tecnico1@acma.dev,Desde CSV\n" \
          f"Cliente Demo,{un['codigo']},2027-06-16,,,,Revisión de la UN\n" \
          f"CDE200101XY2,{un['codigo']},2027-06-17,NO-EXISTE,,,\n" \
          f"CDE200101XY2,{un['codigo']},2027-06-18,,,nadie@acma.dev,\n" \
          f"CDE200101XY2,{un['codigo']},fecha-mala,,,,\n"
    r = await cliente.post("/api/catalogos/importar/calendario_preventivos", headers=h, files={"archivo": ("cal.csv", csv.encode(), "text/csv")})
    assert r.status_code == 201, r.text
    imp = r.json()
    assert imp["filas_ok"] == 2 and imp["filas_error"] == 3, imp
    columnas_error = {e["columna"] for e in imp["errores_json"]}
    assert columnas_error == {"equipo_codigo", "tecnico_email", "fecha"}
    r = await cliente.post(f"/api/catalogos/importar/{imp['id']}/confirmar", headers=h)
    assert r.status_code == 200 and r.json()["resultado"]["creados"] == 2, r.text
    filas = [c for c in await calendario(cliente, auth, AP, mes="2027-06") if c["descripcion"] in ("Desde CSV", "Revisión de la UN")]
    assert len(filas) == 2 and next(c for c in filas if c["descripcion"] == "Desde CSV")["plan_id"] == plan["id"]
    # Repetir el mismo archivo: las dos filas válidas ahora son duplicados.
    r = await cliente.post("/api/catalogos/importar/calendario_preventivos", headers=h, files={"archivo": ("cal.csv", csv.encode(), "text/csv")})
    assert r.status_code == 201 and len(r.json()["duplicados_json"]) == 2


async def test_generar_desde_calendario_manual(cliente, auth, datos):
    equipo = await nuevo_equipo(cliente, auth, datos)
    r = await cliente.post("/api/preventivos/calendario", headers=await auth(DES), json={"tenant_id": str(datos["tenant"]), "filas": [
        {"un_id": str(datos["unidades"][0]), "equipo_id": equipo["id"], "fecha_programada": "2027-08-03", "descripcion": "Manual con equipo"},
        {"un_id": str(datos["unidades"][0]), "fecha_programada": "2027-08-03", "descripcion": "Manual de UN completa"}]})
    assert r.status_code == 201
    con_equipo, sin_equipo = r.json()
    resumen = await generar(cliente, auth, date(2027, 8, 1), 7)
    assert resumen["manuales"] >= 1 and resumen["omitidos"] >= 1  # la fila de UN completa no genera folio (decisión pendiente)
    filas = {c["id"]: c for c in await calendario(cliente, auth, DES, mes="2027-08")}
    assert filas[con_equipo["id"]]["estado"] == "generado" and filas[con_equipo["id"]]["folio_id"] and filas[con_equipo["id"]]["estado_folio"] == "autorizado"
    assert filas[sin_equipo["id"]]["estado"] == "programado" and filas[sin_equipo["id"]]["folio_id"] is None
    f = (await cliente.get(f"/api/folios/{con_equipo['folio_id'] or filas[con_equipo['id']]['folio_id']}", headers=await auth(AE))).json()
    assert f["folio"]["tipo_folio"] == "preventivo" and f["folio"]["estado"] == "autorizado" and f["folio"]["calendario_id"] == con_equipo["id"]
    assert [h["estado_nuevo"] for h in f["historial"] if h["evento"] == "transicion"] == ["capturado", "autorizado"]
    # Segunda corrida: idempotente.
    resumen2 = await generar(cliente, auth, date(2027, 8, 1), 7)
    assert resumen2["manuales"] == 0
    # La fecha ya no se edita con folio generado.
    r = await cliente.patch(f"/api/preventivos/calendario/{con_equipo['id']}", headers=await auth(DES), json={"fecha_programada": "2027-08-04"})
    assert r.status_code == 409, r.text
    assert (await cliente.post("/api/preventivos/generar", headers=await auth(SUPO))).status_code == 403
