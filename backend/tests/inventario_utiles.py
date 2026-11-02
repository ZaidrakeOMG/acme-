"""Ayudas compartidas por las pruebas de P09 (inventario, órdenes de compra, caja chica, costos, presupuestos, ERP y activos)."""
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select, update

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from tests.folios_utiles import AE, AP, AUN, DES, MC, OP, SUPO, TEC, TEC2, accion, detalle, tecnico_usuario_id
from tests.seguimiento_utiles import alertas_disparadas, bandeja, retroceder

_cache: dict = {}


async def articulo(cliente, auth, *, codigo=None, costo="100.00", minimo="2", categoria="Refrigeración", email=AP, esperado=201) -> dict:
    cuerpo = {"codigo": codigo or f"ART-{uuid.uuid4().hex[:6].upper()}", "descripcion": "Artículo de prueba", "categoria": categoria,
              "costo_unitario_vigente": costo, "stock_minimo_default": minimo}
    r = await cliente.post("/api/inventario/articulos", headers=await auth(email), json=cuerpo)
    assert r.status_code == esperado, r.text
    return r.json()


async def ubicacion(cliente, auth, *, nombre=None, tipo="almacen", tecnico_id=None, email=AP, esperado=201) -> dict:
    cuerpo = {"nombre": nombre or f"Ubicación {uuid.uuid4().hex[:5]}", "tipo": tipo}
    if tecnico_id:
        cuerpo["tecnico_id"] = str(tecnico_id)
    r = await cliente.post("/api/inventario/ubicaciones", headers=await auth(email), json=cuerpo)
    assert r.status_code == esperado, r.text
    return r.json()


async def almacen_demo(cliente, auth) -> dict:
    """El almacén central del seed (una vez por sesión de pruebas)."""
    if "almacen" not in _cache:
        ubicaciones = (await cliente.get("/api/inventario/ubicaciones", headers=await auth(AP), params={"tipo": "almacen"})).json()
        _cache["almacen"] = ubicaciones[0]
    return _cache["almacen"]


async def vehiculo_de(cliente, auth, email=TEC) -> dict | None:
    tid = await tecnico_usuario_id(cliente, auth, email)
    ubicaciones = (await cliente.get("/api/inventario/ubicaciones", headers=await auth(AP), params={"tipo": "vehiculo"})).json()
    return next((u for u in ubicaciones if u["tecnico_id"] == tid), None)


async def entrada(cliente, auth, articulo_id, ubicacion_id, cantidad="10", costo=None, email=AP, esperado=201) -> dict:
    cuerpo = {"articulo_id": str(articulo_id), "ubicacion_id": str(ubicacion_id), "cantidad": cantidad, "razon": "Entrada de prueba"}
    if costo is not None:
        cuerpo["costo_unitario"] = costo
    r = await cliente.post("/api/inventario/movimientos/entrada", headers=await auth(email), json=cuerpo)
    assert r.status_code == esperado, r.text
    return r.json()


async def traspaso(cliente, auth, articulo_id, origen_id, destino_id, cantidad="2", email=AP, esperado=201) -> dict:
    r = await cliente.post("/api/inventario/movimientos/traspaso", headers=await auth(email),
                           json={"articulo_id": str(articulo_id), "origen_id": str(origen_id), "destino_id": str(destino_id), "cantidad": cantidad,
                                 "razon": "Carga de la unidad"})
    assert r.status_code == esperado, r.text
    return r.json()


async def existencia(cliente, auth, ubicacion_id, articulo_id, email=AP) -> dict | None:
    filas = (await cliente.get("/api/inventario/existencias", headers=await auth(email),
                               params={"ubicacion_id": str(ubicacion_id), "articulo_id": str(articulo_id)})).json()
    return filas[0] if filas else None


async def folio_en_ejecucion(cliente, auth, datos, tecnico=TEC):
    """Folio autorizado, asignado al técnico y en ejecución, listo para consumir refacciones."""
    from tests.test_cierre_folio import _en_ejecucion

    return await _en_ejecucion(cliente, auth, datos)


async def refaccion(cliente, auth, folio_id, *, articulo_id=None, cantidad="1", origen="almacen", ubicacion_id=None, descripcion="Refacción de prueba",
                    costo="0", email=TEC, esperado=201) -> dict:
    cuerpo = {"descripcion": descripcion, "cantidad": cantidad, "origen": origen, "costo_unitario": costo}
    if articulo_id:
        cuerpo["articulo_id"] = str(articulo_id)
    if ubicacion_id:
        cuerpo["ubicacion_id"] = str(ubicacion_id)
    r = await cliente.post(f"/api/folios/{folio_id}/refacciones", headers=await auth(email), json=cuerpo)
    assert r.status_code == esperado, r.text
    return r.json()


async def cerrar_folio(cliente, auth, datos, folio, tecnico=TEC) -> dict:
    from tests.test_cierre_folio import _respuesta_atencion, firmar

    rid = await _respuesta_atencion(cliente, auth, datos, folio, tecnico)
    await accion(cliente, auth, tecnico, folio["id"], "atencion", {"respuesta_id": rid}, esperado=201)
    await firmar(cliente, auth, OP, folio["id"])
    return await accion(cliente, auth, tecnico, folio["id"], "cerrar")


async def costos_de(cliente, auth, folio_id, email=MC) -> dict:
    r = await cliente.get(f"/api/folios/{folio_id}/costos", headers=await auth(email))
    assert r.status_code == 200, r.text
    return r.json()


async def validar_costo(cliente, auth, folio_id, email=MC, esperado=200, **extra) -> dict:
    r = await cliente.post(f"/api/folios/{folio_id}/costos/validar", headers=await auth(email), json=extra)
    assert r.status_code == esperado, r.text
    return r.json()


async def tarifa(cliente, auth, tarifa_hora="400.00", email=AP, **extra) -> dict:
    r = await cliente.post("/api/presupuestos/tarifas", headers=await auth(email), json={"tarifa_hora": tarifa_hora, **extra})
    assert r.status_code == 201, r.text
    return r.json()


async def fondo(cliente, auth, tecnico_email=TEC, monto="5000.00", email=AP, esperado=201) -> dict:
    tid = await tecnico_usuario_id(cliente, auth, tecnico_email)
    r = await cliente.post("/api/caja-chica/fondos", headers=await auth(email), json={"tecnico_id": tid, "monto_inicial": monto})
    assert r.status_code == esperado, r.text
    return r.json()


async def fondo_de(cliente, auth, tecnico_email=TEC, email=AP) -> dict | None:
    tid = await tecnico_usuario_id(cliente, auth, tecnico_email)
    fondos = (await cliente.get("/api/caja-chica/fondos", headers=await auth(email))).json()
    return next((f for f in fondos if f["tecnico_id"] == tid), None)


async def gasto(cliente, auth, *, folio_id=None, subtotal="200.00", iva="32.00", articulo_id=None, email=TEC, esperado=201, **extra) -> dict:
    cuerpo = {"proveedor": "Refaccionaria de prueba", "rfc_proveedor": "RPR900101AB1", "descripcion": "Refacción comprada en campo",
              "subtotal": subtotal, "iva": iva, **extra}
    if folio_id:
        cuerpo["folio_id"] = str(folio_id)
    if articulo_id:
        cuerpo["articulo_id"] = str(articulo_id)
    r = await cliente.post("/api/caja-chica/gastos", headers=await auth(email), json=cuerpo)
    assert r.status_code == esperado, r.text
    return r.json()


async def presupuesto(cliente, auth, datos, *, un_id=None, grupo_id=None, monto="10000.00", tipo="todos", email=AE, esperado=201, **extra) -> dict:
    hoy = date.today()
    cuerpo = {"nombre": f"Presupuesto {uuid.uuid4().hex[:5]}", "tipo_actividad": tipo, "periodo_inicio": (hoy - timedelta(days=30)).isoformat(),
              "periodo_fin": (hoy + timedelta(days=60)).isoformat(), "monto": monto, **extra}
    if un_id:
        cuerpo["un_id"] = str(un_id)
    if grupo_id:
        cuerpo["grupo_id"] = str(grupo_id)
    r = await cliente.post("/api/presupuestos", headers=await auth(email), json=cuerpo)
    assert r.status_code == esperado, r.text
    return r.json()


async def permiso_tecnico(cliente, auth, email_tecnico, clave, habilitado=True) -> str:
    """Override individual de un permiso del técnico (§6.8.3); devuelve su usuario_id."""
    h = await auth(AP)
    lista = (await cliente.get("/api/catalogos/tecnicos", headers=h)).json()
    t = next(x for x in lista if x["email"] == email_tecnico)
    r = await cliente.put(f"/api/catalogos/tecnicos/{t['id']}/permisos", headers=h,
                          json={"overrides": [{"permiso_clave": clave, "habilitado": habilitado, "razon": "Prueba P09"}]})
    assert r.status_code == 200, r.text
    return t["usuario_id"]


async def equipo_con_activo(cliente, auth, datos, *, costo="100000.00", reposicion="120000.00", email=AE) -> dict:
    """Equipo nuevo con datos económicos capturados para la ficha de activos."""
    from tests.folios_utiles import nuevo_equipo

    e = await nuevo_equipo(cliente, auth, datos, criticidad="A")
    r = await cliente.put(f"/api/activos/{e['id']}/datos-economicos", headers=await auth(email),
                          json={"costo_adquisicion": costo, "valor_reposicion": reposicion, "fecha_adquisicion": (date.today() - timedelta(days=1460)).isoformat(),
                                "costo_hora_inactividad": "400.00"})
    assert r.status_code == 200, r.text
    return e


__all__ = ["AE", "AP", "AUN", "DES", "MC", "OP", "SUPO", "TEC", "TEC2", "accion", "alertas_disparadas", "bandeja", "detalle", "retroceder",
           "tecnico_usuario_id", "Decimal", "select", "update", "nueva_sesion", "CONTEXTO_SISTEMA"]
