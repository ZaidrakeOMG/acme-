"""Login, MFA (enrolamiento, verificación, recuperación), refresh rotativo con detección de reúso, bloqueos."""
import uuid

import pyotp

from tests.conftest import csrf, iniciar_sesion, olvidar_paso_totp, refrescar


async def _crear_usuario(cliente, auth, rol: str, tenant_id=None, prestador_id=None) -> str:
    email = f"{rol}.{uuid.uuid4().hex[:8]}@prueba.dev"
    r = await cliente.post("/api/usuarios", headers=await auth("superadmin@acma.dev"), json={
        "email": email, "nombre": f"Prueba {rol}", "rol": rol, "contrasena": "Prueba#Segura2026",
        "tenant_id": str(tenant_id) if tenant_id else None, "prestador_id": str(prestador_id) if prestador_id else None,
    })
    assert r.status_code == 201, r.text
    return email


async def test_cuentas_distintas_pueden_usar_misma_contrasena(cliente, auth, datos):
    """La unicidad aplica al correo, no a la clave: Argon2 usa sal independiente."""
    clave = "ClaveCompartidaDePrueba#2026Q"
    correos = [f"gps.usuarios.{uuid.uuid4().hex[:12]}@prueba.dev" for _ in range(2)]
    for indice, email in enumerate(correos):
        r = await cliente.post("/api/usuarios", headers=await auth("superadmin@acma.dev"),
                               json={"email": email, "nombre": f"Usuario prueba {indice + 1}",
                                     "rol": "operador", "contrasena": clave,
                                     "tenant_id": str(datos["tenant"])})
        assert r.status_code == 201, r.text
    for email in correos:
        login = await cliente.post("/api/auth/login",
                                  json={"email": email, "contrasena": clave})
        assert login.status_code == 200, login.text
        assert login.json()["usuario"]["email"] == email


async def test_login_sin_mfa_y_perfil(cliente, datos):
    r = await cliente.post("/api/auth/login", json={"email": "operador@acma.dev", "contrasena": datos["contrasena"]})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["mfa_requerido"] is False
    assert cuerpo["usuario"]["rol"] == "operador"
    yo = await cliente.get("/api/auth/yo", headers={"Authorization": f"Bearer {cuerpo['tokens']['access_token']}"})
    assert yo.status_code == 200
    assert yo.json()["tema"]["color_primario"] == "#1C3D8F"
    assert yo.json()["tema"]["prestador"] == "Prestador Demo"


async def test_credenciales_invalidas_formato_estandar(cliente, datos):
    r = await cliente.post("/api/auth/login", json={"email": "operador@acma.dev", "contrasena": "incorrecta"})
    assert r.status_code == 401
    assert r.json() == {"codigo": "CREDENCIALES_INVALIDAS", "mensaje": "Correo o contraseña incorrectos", "detalles": []}
    r = await cliente.post("/api/auth/login", json={"email": "nadie@acma.dev", "contrasena": "x"})
    assert r.json()["codigo"] == "CREDENCIALES_INVALIDAS"


async def test_flujo_completo_mfa_enrolamiento_verificacion_y_recuperacion(cliente_factory, auth, datos):
    async with cliente_factory() as c:
        email = await _crear_usuario(c, auth, "admin_empresa", tenant_id=datos["tenant"])

        # 1. Rol con MFA obligatorio sin enrolar: login exige enrolamiento.
        r = await c.post("/api/auth/login", json={"email": email, "contrasena": "Prueba#Segura2026"})
        cuerpo = r.json()
        assert cuerpo["mfa_requerido"] and cuerpo["mfa_enrolamiento_requerido"] and cuerpo["tokens"] is None
        token_mfa = cuerpo["token_mfa"]

        # El token MFA no sirve como token de acceso.
        assert (await c.get("/api/auth/yo", headers={"Authorization": f"Bearer {token_mfa}"})).status_code == 401

        setup = (await c.post("/api/auth/mfa/setup", json={"token_mfa": token_mfa})).json()
        assert setup["qr_svg"].startswith("data:image/svg+xml")
        assert setup["uri"].startswith("otpauth://totp/ACMA")
        totp = pyotp.TOTP(setup["secreto"])

        malo = await c.post("/api/auth/mfa/verify", json={"token_mfa": token_mfa, "codigo": "000000"})
        assert malo.status_code == 401 and malo.json()["codigo"] == "CODIGO_MFA_INVALIDO"

        ok = (await c.post("/api/auth/mfa/verify", json={"token_mfa": token_mfa, "codigo": totp.now()})).json()
        assert ok["tokens"]["access_token"] and len(ok["codigos_recuperacion"]) == 10
        assert ok["usuario"]["mfa_habilitado"] is True
        codigos = ok["codigos_recuperacion"]

        # 2. Login posterior: verificación TOTP normal (sin códigos nuevos).
        r = (await c.post("/api/auth/login", json={"email": email, "contrasena": "Prueba#Segura2026"})).json()
        assert r["mfa_requerido"] and not r["mfa_enrolamiento_requerido"]
        await olvidar_paso_totp(email)
        v = (await c.post("/api/auth/mfa/verify", json={"token_mfa": r["token_mfa"], "codigo": totp.now()})).json()
        assert v["tokens"] and v["codigos_recuperacion"] is None

        # 3. Código de recuperación: sirve una sola vez.
        r = (await c.post("/api/auth/login", json={"email": email, "contrasena": "Prueba#Segura2026"})).json()
        assert (await c.post("/api/auth/mfa/verify", json={"token_mfa": r["token_mfa"], "codigo": codigos[0]})).status_code == 200
        r = (await c.post("/api/auth/login", json={"email": email, "contrasena": "Prueba#Segura2026"})).json()
        assert (await c.post("/api/auth/mfa/verify", json={"token_mfa": r["token_mfa"], "codigo": codigos[0]})).status_code == 401

        # 4. Rol con MFA obligatorio no puede deshabilitarlo; sí regenerar códigos.
        h = {"Authorization": f"Bearer {v['tokens']['access_token']}"}
        assert (await c.post("/api/auth/mfa/disable", headers=h, json={"codigo": totp.now()})).json()["codigo"] == "MFA_OBLIGATORIO"
        await olvidar_paso_totp(email)
        nuevos = await c.post("/api/auth/mfa/codigos-recuperacion", headers=h, json={"codigo": totp.now()})
        assert nuevos.status_code == 200 and len(set(nuevos.json()["codigos_recuperacion"]) - set(codigos)) == 10


async def test_mfa_voluntario_rol_no_obligatorio(cliente_factory, auth, datos):
    async with cliente_factory() as c:
        email = await _crear_usuario(c, auth, "despachador", prestador_id=datos["prestador"])
        tokens = await iniciar_sesion(c, email, "Prueba#Segura2026")
        h = {"Authorization": f"Bearer {tokens['access_token']}"}
        secreto = (await c.post("/api/auth/mfa/setup", headers=h, json={})).json()["secreto"]
        activado = await c.post("/api/auth/mfa/verify", headers=h, json={"codigo": pyotp.TOTP(secreto).now()})
        assert activado.status_code == 200 and len(activado.json()["codigos_recuperacion"]) == 10
        # Desde ahora su login pide MFA; y puede deshabilitarlo porque su rol no lo exige.
        r = (await c.post("/api/auth/login", json={"email": email, "contrasena": "Prueba#Segura2026"})).json()
        assert r["mfa_requerido"] and not r["mfa_enrolamiento_requerido"]
        await olvidar_paso_totp(email)
        assert (await c.post("/api/auth/mfa/disable", headers=h, json={"codigo": pyotp.TOTP(secreto).now()})).status_code == 200
        r = (await c.post("/api/auth/login", json={"email": email, "contrasena": "Prueba#Segura2026"})).json()
        assert r["mfa_requerido"] is False


async def test_sesion_en_cookie_httponly_y_csrf(cliente, datos):
    """§6.9.5: el refresh viaja en cookie httpOnly con ruta limitada y el refresh exige la cabecera CSRF. P11a."""
    tokens = await iniciar_sesion(cliente, "tecnico1@acma.dev", datos["contrasena"])
    assert "refresh_token" not in tokens          # ya no viaja en el cuerpo
    assert tokens["csrf"] and tokens["sesion_expira_en"] > 0
    galleta = next(c for c in cliente.cookies.jar if c.name == "acma_refresh")
    assert galleta.path == "/api/auth" and galleta.has_nonstandard_attr("HttpOnly")
    assert cliente.cookies.get("acma_csrf") == tokens["csrf"]
    # Sin la cabecera CSRF el refresh se rechaza; con ella, rota.
    sin_csrf = await cliente.post("/api/auth/refresh")
    assert sin_csrf.status_code == 403 and sin_csrf.json()["codigo"] == "CSRF_INVALIDO"
    malo = await cliente.post("/api/auth/refresh", headers={"X-ACMA-CSRF": "otro-valor"})
    assert malo.status_code == 403
    r1 = await refrescar(cliente)
    assert r1.status_code == 200 and r1.json()["access_token"] != tokens["access_token"]
    assert (await cliente.get("/api/auth/yo", headers={"Authorization": f"Bearer {r1.json()['access_token']}"})).status_code == 200


async def test_refresh_rotativo_y_reuso_invalida_familia(cliente, datos):
    tokens = await iniciar_sesion(cliente, "tecnico1@acma.dev", datos["contrasena"])
    viejo = cliente.cookies.get("acma_refresh")
    r1 = await refrescar(cliente)
    assert r1.status_code == 200
    nuevos = r1.json()
    assert cliente.cookies.get("acma_refresh") != viejo
    assert (await cliente.get("/api/auth/yo", headers={"Authorization": f"Bearer {nuevos['access_token']}"})).status_code == 200

    # Reúso del refresh anterior: se detecta y se revoca toda la familia.
    cliente.cookies.set("acma_refresh", viejo, path="/api/auth")
    reuso = await cliente.post("/api/auth/refresh", headers=csrf(cliente))
    assert reuso.status_code == 401 and reuso.json()["codigo"] == "TOKEN_REUTILIZADO"
    # El token de acceso de esa familia también deja de valer.
    assert (await cliente.get("/api/auth/yo", headers={"Authorization": f"Bearer {nuevos['access_token']}"})).status_code == 401
    # Una sesión nueva funciona normalmente.
    assert (await iniciar_sesion(cliente, "tecnico1@acma.dev", datos["contrasena"]))["access_token"]


async def test_refresh_invalido(cliente, datos):
    sin_cookie = await cliente.post("/api/auth/refresh", headers={"X-ACMA-CSRF": "x"})
    assert sin_cookie.status_code in (401, 403)
    cliente.cookies.set("acma_refresh", "x" * 64, path="/api/auth")
    cliente.cookies.set("acma_csrf", "token-csrf", path="/")
    r = await cliente.post("/api/auth/refresh", headers={"X-ACMA-CSRF": "token-csrf"})
    assert r.status_code == 401


async def test_logout_revoca_sesion(cliente, datos):
    tokens = await iniciar_sesion(cliente, "tecnico2@acma.dev", datos["contrasena"])
    h = {"Authorization": f"Bearer {tokens['access_token']}", **csrf(cliente)}
    assert (await cliente.post("/api/auth/logout", headers=h)).status_code == 200
    assert (await cliente.get("/api/auth/yo", headers=h)).status_code == 401
    # La cookie de sesión se borra y el refresh ya no sirve.
    assert not cliente.cookies.get("acma_refresh")
    cliente.cookies.set("acma_refresh", "x" * 64, path="/api/auth")
    cliente.cookies.set("acma_csrf", "t", path="/")
    assert (await cliente.post("/api/auth/refresh", headers={"X-ACMA-CSRF": "t"})).status_code == 401


async def test_bloqueo_temporal_por_usuario(cliente_factory, auth, datos):
    async with cliente_factory() as c:
        email = await _crear_usuario(c, auth, "operador", tenant_id=datos["tenant"])
    for _ in range(5):  # cada intento desde otra IP para aislar el bloqueo por usuario
        async with cliente_factory() as c:
            assert (await c.post("/api/auth/login", json={"email": email, "contrasena": "mala"})).status_code == 401
    async with cliente_factory() as c:
        r = await c.post("/api/auth/login", json={"email": email, "contrasena": "Prueba#Segura2026"})
        assert r.status_code == 423 and r.json()["codigo"] == "USUARIO_BLOQUEADO"


async def test_limite_por_ip(cliente_factory, datos):
    async with cliente_factory(ip="192.0.2.77") as c:
        for i in range(5):
            r = await c.post("/api/auth/login", json={"email": f"x{i}@nadie.dev", "contrasena": "mala"})
            assert r.status_code == 401
        r = await c.post("/api/auth/login", json={"email": "operador@acma.dev", "contrasena": datos["contrasena"]})
        assert r.status_code == 429 and r.json()["codigo"] == "DEMASIADOS_INTENTOS"
        assert "retry-after" in r.headers


async def test_cambio_de_contrasena_politica_e_historial(cliente_factory, auth, datos):
    async with cliente_factory() as c:
        email = await _crear_usuario(c, auth, "operador", tenant_id=datos["tenant"])
        tokens = await iniciar_sesion(c, email, "Prueba#Segura2026")
        h = {"Authorization": f"Bearer {tokens['access_token']}"}
        debil = await c.post("/api/auth/cambiar-contrasena", headers=h, json={"actual": "Prueba#Segura2026", "nueva": "solominusculas"})
        assert debil.json()["codigo"] == "POLITICA_CONTRASENA"
        repetida = await c.post("/api/auth/cambiar-contrasena", headers=h,
                                json={"actual": "Prueba#Segura2026", "nueva": "Prueba#Segura2026"})
        assert repetida.json()["codigo"] == "CONTRASENA_REPETIDA"
        ok = await c.post("/api/auth/cambiar-contrasena", headers=h, json={"actual": "Prueba#Segura2026", "nueva": "Nueva#Segura2027"})
        assert ok.status_code == 200
        assert (await c.post("/api/auth/login", json={"email": email, "contrasena": "Nueva#Segura2027"})).status_code == 200


async def test_cabeceras_de_seguridad_y_error_estandar(cliente):
    r = await cliente.get("/api/no-existe")
    assert r.status_code == 404
    assert r.json()["codigo"] == "NO_ENCONTRADO"
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    # HSTS solo se manda en produccion: cacheado desde un localhost sin TLS dejaria el navegador exigiendo https (P11a).
    assert "strict-transport-security" not in r.headers
    sin_token = await cliente.get("/api/usuarios")
    assert sin_token.status_code == 401 and sin_token.json()["codigo"] == "NO_AUTENTICADO"
    validacion = await cliente.post("/api/auth/login", json={"email": "no-es-correo"})
    assert validacion.status_code == 422 and validacion.json()["codigo"] == "VALIDACION"
    assert {d["campo"] for d in validacion.json()["detalles"]} >= {"email", "contrasena"}


async def test_cors_por_entorno(cliente):
    r = await cliente.options("/api/auth/login", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
    r = await cliente.options("/api/auth/login", headers={"Origin": "https://malicioso.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in r.headers


async def test_cambio_de_rol_invalida_token(cliente_factory, auth, datos):
    async with cliente_factory() as c:
        email = await _crear_usuario(c, auth, "operador", tenant_id=datos["tenant"])
        tokens = await iniciar_sesion(c, email, "Prueba#Segura2026")
        h = {"Authorization": f"Bearer {tokens['access_token']}"}
        uid = (await c.get("/api/auth/yo", headers=h)).json()["id"]
        r = await c.patch(f"/api/usuarios/{uid}", headers=await auth("admin.empresa@acma.dev"), json={"rol": "admin_un"})
        assert r.status_code == 200
        assert (await c.get("/api/auth/yo", headers=h)).status_code == 401
