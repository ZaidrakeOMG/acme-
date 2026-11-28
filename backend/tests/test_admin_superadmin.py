"""Permisos administrativos exclusivos de superadmin."""
import uuid
import pytest

@pytest.mark.parametrize("email", ["admin.empresa@acma.dev", "admin.prestador@acma.dev"])
async def test_mutaciones_admin_prohibidas(cliente, auth, datos, email):
    h = await auth(email)
    inexistente = str(uuid.uuid4())
    rutas = [
        ("POST", "/api/usuarios", {"email": "nuevo@prueba.dev", "nombre": "Nuevo usuario", "rol": "superadmin", "contrasena": "Prueba#Segura2026"}),
        ("PATCH", f"/api/usuarios/{inexistente}", {"nombre": "Nuevo nombre"}),
        ("DELETE", f"/api/usuarios/{inexistente}", None),
        ("POST", f"/api/usuarios/{inexistente}/restablecer-contrasena", {"contrasena": "Prueba#Nueva2026"}),
        ("PATCH", f"/api/tenants/{datos['tenant']}", {"razon_social": "Otro"}),
        ("PATCH", f"/api/prestadores/{datos['prestador']}", {"razon_social": "Otro"}),
        ("PATCH", f"/api/unidades-negocio/{datos['unidades'][0]}", {"estado": "inactivo"}),
        ("PATCH", f"/api/grupos-un/{inexistente}", {"nombre": "Nuevo grupo"}),
        ("PATCH", f"/api/contratos/{inexistente}", {"estado": "inactivo"}),
    ]
    for metodo, ruta, cuerpo in rutas:
        r = await cliente.request(metodo, ruta, headers=h, json=cuerpo)
        assert r.status_code == 403, (email, ruta, r.status_code, r.text)

async def test_superadmin_restablece_contrasena_y_no_reutiliza(cliente, auth, datos):
    h = await auth("superadmin@acma.dev")
    r = await cliente.post("/api/usuarios", headers=h, json={
        "email": f"reset.{uuid.uuid4().hex[:8]}@prueba.dev", "nombre": "Prueba reset",
        "rol": "operador", "tenant_id": str(datos["tenant"]), "contrasena": "Prueba#Inicial2026"})
    assert r.status_code == 201, r.text
    ruta = f"/api/usuarios/{r.json()['id']}/restablecer-contrasena"
    nueva = {"contrasena": "Prueba#Nueva2026"}
    assert (await cliente.post(ruta, headers=h, json=nueva)).status_code == 204
    assert (await cliente.post(ruta, headers=h, json=nueva)).status_code == 422
