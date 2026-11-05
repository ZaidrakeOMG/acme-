"""Endurecimiento de §6.9.5 y §6.7 (P11a): sesión en cookie con CSRF y expiración, política y vencimiento de
contraseña, restablecimiento por correo, TOTP sin reutilización, aviso de bloqueo de IP, auditoría de datos sensibles,
retención de la bitácora de API y las restricciones duras del negocio."""
import uuid
from datetime import UTC, datetime, timedelta

import pyotp
from sqlalchemy import select, text, update

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from models.auditoria import AuditLog
from models.usuarios import Sesion, Usuario
from services import correo
from tests.conftest import csrf, iniciar_sesion, olvidar_paso_totp, refrescar
from tests.folios_utiles import AE, AP, MC, OP, TEC

SA = "superadmin@acma.dev"
# Las sesiones que se envejecen a mano se limitan a su usuario: la suite completa comparte la base.
SOLO_DE_ESTE = "WHERE revocada_at IS NULL AND usuario_id = (SELECT id FROM usuarios WHERE email = :e)"
NUEVA = "Nueva#Clave2026x"


async def _crear_usuario(cliente, auth, rol: str, tenant_id=None, prestador_id=None, contrasena="Prueba#Segura2026") -> str:
    email = f"{rol}.{uuid.uuid4().hex[:8]}@prueba.dev"
    r = await cliente.post("/api/usuarios", headers=await auth(SA), json={
        "email": email, "nombre": f"Prueba {rol}", "rol": rol, "contrasena": contrasena,
        **({"tenant_id": str(tenant_id)} if tenant_id else {}),
        **({"prestador_id": str(prestador_id)} if prestador_id else {}),
    })
    assert r.status_code == 201, r.text
    return email


async def _sql(consulta: str, **params):
    """Consulta o modifica con el rol sistema. Devuelve las filas cuando la sentencia las produce."""
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        resultado = await db.execute(text(consulta), params)
        filas = resultado.all() if resultado.returns_rows else []
        await db.commit()
        return filas


async def _sql_dueno(consulta: str, **params):
    """Lo mismo pero con el rol dueño del esquema: necesario para DDL (crear particiones de prueba)."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from core.config import config

    url = config.test_database_migrations_url or config.database_migrations_url
    motor = create_async_engine(url, poolclass=NullPool)
    try:
        async with motor.begin() as conexion:
            resultado = await conexion.execute(text(consulta), params)
            return resultado.all() if resultado.returns_rows else []
    finally:
        await motor.dispose()


# --------------------------------------------------------------- sesiones

async def test_vida_de_la_sesion_por_rol(cliente_factory, auth, datos):
    """§6.9.5: 8 h de sesión y 2 h para los roles administrativos. P11a (cierra la decisión pendiente n.º 1)."""
    async with cliente_factory() as c:
        tecnico = await iniciar_sesion(c, TEC, datos["contrasena"])
        assert 7.5 * 3600 < tecnico["sesion_expira_en"] <= 8 * 3600
    async with cliente_factory() as c:
        admin = await iniciar_sesion(c, AP, datos["contrasena"])
        assert 1.5 * 3600 < admin["sesion_expira_en"] <= 2 * 3600


async def test_la_rotacion_no_alarga_la_sesion(cliente_factory, datos):
    async with cliente_factory() as c:
        primero = await iniciar_sesion(c, TEC, datos["contrasena"])
        segundo = (await refrescar(c)).json()
        # El tope absoluto se hereda: renovar el token de acceso no regala otras 8 h.
        assert segundo["sesion_expira_en"] <= primero["sesion_expira_en"]


async def test_sesion_expirada_y_cierre_por_inactividad(cliente, cliente_factory, auth, datos):
    """§6.9.5: agotada la vida máxima o pasada la inactividad, el refresh no renueva y la familia queda revocada.

    Usa un usuario propio: envejecer las sesiones de un usuario del seed le tumbaría la sesión a las demás pruebas,
    que comparten la misma base.
    """
    email = await _crear_usuario(cliente, auth, "tecnico", prestador_id=datos["prestador"])
    async with cliente_factory() as c:
        await iniciar_sesion(c, email, "Prueba#Segura2026")
        # Vida máxima agotada: el refresh se rechaza y la familia queda revocada.
        await _sql(f"UPDATE sesiones SET expira_at = now() - interval '1 minute' {SOLO_DE_ESTE}", e=email)
        vencida = await refrescar(c)
        assert vencida.status_code == 401
    async with cliente_factory() as c:
        await iniciar_sesion(c, email, "Prueba#Segura2026")
        # Inactividad: la sesión sigue viva pero sin uso por más de lo configurado.
        await _sql(f"UPDATE sesiones SET ultimo_acceso_at = now() - interval '10 hours' {SOLO_DE_ESTE}", e=email)
        inactiva = await refrescar(c)
        assert inactiva.status_code == 401
        motivos = await _sql("SELECT DISTINCT motivo_revocacion FROM sesiones"
                             " WHERE motivo_revocacion IS NOT NULL AND usuario_id = "
                             "(SELECT id FROM usuarios WHERE email = :e)", e=email)
        assert {"inactividad", "expirada"} & {m.motivo_revocacion for m in motivos}


# ------------------------------------------------------------ contraseñas

async def test_politica_de_contrasena(cliente_factory, auth, datos):
    """§6.9.5: mínimo 10 caracteres con complejidad y sin repetir las últimas 10."""
    async with cliente_factory() as c:
        email = await _crear_usuario(c, auth, "operador", tenant_id=datos["tenant"])
        tokens = await iniciar_sesion(c, email, "Prueba#Segura2026")
        h = {"Authorization": f"Bearer {tokens['access_token']}"}
        for mala in ("corta1!A", "sinmayuscula1!", "SINMINUSCULA1!", "SinNumeros!!", "SinSimbolo123"):
            r = await c.post("/api/auth/cambiar-contrasena", headers=h, json={"actual": "Prueba#Segura2026", "nueva": mala})
            assert r.status_code == 422, mala
        ok = await c.post("/api/auth/cambiar-contrasena", headers=h, json={"actual": "Prueba#Segura2026", "nueva": NUEVA})
        assert ok.status_code == 200, ok.text
        # No se puede volver a la anterior (historial de 10).
        repetida = await c.post("/api/auth/cambiar-contrasena", headers=h, json={"actual": NUEVA, "nueva": "Prueba#Segura2026"})
        assert repetida.status_code == 422 and repetida.json()["codigo"] == "CONTRASENA_REPETIDA"


async def test_contrasena_vencida_bloquea_todo_menos_el_cambio(cliente_factory, auth, datos):
    """§6.9.5: 90 días para roles administrativos, con cambio obligatorio al entrar. P11a."""
    async with cliente_factory() as c:
        email = await _crear_usuario(c, auth, "admin_un", tenant_id=datos["tenant"])
        await _sql("UPDATE usuarios SET password_actualizado_at = now() - interval '120 days' WHERE email = :e", e=email)
        entrada = await c.post("/api/auth/login", json={"email": email, "contrasena": "Prueba#Segura2026"})
        assert entrada.status_code == 200 and entrada.json()["cambio_contrasena_requerido"] is True
        h = {"Authorization": f"Bearer {entrada.json()['tokens']['access_token']}"}
        # Su perfil sí; cualquier otro módulo no.
        assert (await c.get("/api/auth/yo", headers=h)).status_code == 200
        bloqueado = await c.get("/api/folios", headers=h)
        assert bloqueado.status_code == 403 and bloqueado.json()["codigo"] == "CONTRASENA_VENCIDA"
        # Al cambiarla, todo vuelve a funcionar.
        assert (await c.post("/api/auth/cambiar-contrasena", headers=h,
                             json={"actual": "Prueba#Segura2026", "nueva": NUEVA})).status_code == 200
        assert (await c.get("/api/folios", headers=h)).status_code == 200
        de_nuevo = await c.post("/api/auth/login", json={"email": email, "contrasena": NUEVA})
        assert de_nuevo.json()["cambio_contrasena_requerido"] is False


async def test_el_tecnico_no_tiene_vencimiento_de_contrasena(cliente_factory, auth, datos):
    async with cliente_factory() as c:
        email = await _crear_usuario(c, auth, "tecnico", prestador_id=datos["prestador"])
        await _sql("UPDATE usuarios SET password_actualizado_at = now() - interval '400 days' WHERE email = :e", e=email)
        r = await c.post("/api/auth/login", json={"email": email, "contrasena": "Prueba#Segura2026"})
        assert r.status_code == 200 and r.json()["cambio_contrasena_requerido"] is False


async def test_restablecimiento_por_correo_con_token_de_un_solo_uso(cliente_factory, auth, datos):
    async with cliente_factory() as c:
        email = await _crear_usuario(c, auth, "operador", tenant_id=datos["tenant"])
        # Un correo inexistente responde igual (no revela qué cuentas hay).
        desconocido = await c.post("/api/auth/restablecer/solicitar", json={"email": "nadie@prueba.dev"})
        assert desconocido.status_code == 200
        r = await c.post("/api/auth/restablecer/solicitar", json={"email": email})
        assert r.status_code == 200
        enviados = [x for x in correo.ENVIADOS if email in x["destinatarios"]]
        assert enviados and "restablecer" in enviados[-1]["html"].lower()
        token = enviados[-1]["html"].split("token=")[1].split('"')[0].split("&")[0]
        # Token válido: fija la contraseña nueva y cierra las sesiones abiertas.
        ok = await c.post("/api/auth/restablecer/confirmar", json={"token": token, "nueva": NUEVA})
        assert ok.status_code == 200, ok.text
        assert (await c.post("/api/auth/login", json={"email": email, "contrasena": NUEVA})).status_code == 200
        # El mismo token ya no sirve.
        reuso = await c.post("/api/auth/restablecer/confirmar", json={"token": token, "nueva": "Otra#Clave2026x"})
        assert reuso.status_code == 400 and reuso.json()["codigo"] == "TOKEN_RESET_USADO"
        # Y la política también aplica aquí.
        r2 = await c.post("/api/auth/restablecer/solicitar", json={"email": email})
        token2 = [x for x in correo.ENVIADOS if email in x["destinatarios"]][-1]["html"].split("token=")[1].split('"')[0].split("&")[0]
        mala = await c.post("/api/auth/restablecer/confirmar", json={"token": token2, "nueva": "corta1!A"})
        assert r2.status_code == 200 and mala.status_code == 422


# -------------------------------------------------------------------- MFA

async def test_totp_no_se_reutiliza(cliente_factory, auth, datos):
    """§6.9.5: el mismo código TOTP no se acepta dos veces dentro de su ventana de 30 s. P11a."""
    async with cliente_factory() as c:
        email = await _crear_usuario(c, auth, "despachador", prestador_id=datos["prestador"])
        tokens = await iniciar_sesion(c, email, "Prueba#Segura2026")
        h = {"Authorization": f"Bearer {tokens['access_token']}"}
        secreto = (await c.post("/api/auth/mfa/setup", headers=h, json={})).json()["secreto"]
        codigo = pyotp.TOTP(secreto).now()
        assert (await c.post("/api/auth/mfa/verify", headers=h, json={"codigo": codigo})).status_code == 200
        # El mismo código, de nuevo: rechazado aunque siga dentro de su ventana.
        repetido = await c.post("/api/auth/mfa/codigos-recuperacion", headers=h, json={"codigo": codigo})
        assert repetido.status_code == 401 and repetido.json()["codigo"] == "CODIGO_MFA_INVALIDO"
        # El del paso siguiente sí vale.
        totp = pyotp.TOTP(secreto)
        siguiente = totp.at(int(datetime.now(UTC).timestamp()) + totp.interval)
        assert (await c.post("/api/auth/mfa/codigos-recuperacion", headers=h, json={"codigo": siguiente})).status_code == 200


# ------------------------------------------------------- intentos fallidos

async def test_bloqueo_de_ip_avisa_al_administrador(cliente_factory, auth, datos):
    """§6.9.5 «Notificación al admin» al bloquear una IP por intentos fallidos. P11a (pendiente de P01)."""
    async with cliente_factory() as c:
        for _ in range(5):
            await c.post("/api/auth/login", json={"email": "inexistente@prueba.dev", "contrasena": "mala"})
        bloqueado = await c.post("/api/auth/login", json={"email": "inexistente@prueba.dev", "contrasena": "mala"})
        assert bloqueado.status_code == 429 and bloqueado.json()["codigo"] == "DEMASIADOS_INTENTOS"
    # La bandeja del superadmin recibe el aviso del bloqueo.
    async with cliente_factory() as c:
        lista = (await c.get("/api/notificaciones", headers=await auth(SA), params={"limite": 100})).json()
    assert any(n["evento"] == "seguridad.bloqueo_ip" for n in lista), "el superadmin debe recibir el aviso"


# ----------------------------------------------------------- auditoría

async def _eventos(tipo: str, limite: int = 20):
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        return (await db.execute(select(AuditLog).where(AuditLog.evento_tipo == tipo)
                                 .order_by(AuditLog.created_at.desc()).limit(limite))).scalars().all()


async def test_auditoria_de_login_guarda_ip_y_geolocalizacion(cliente_factory, datos):
    async with cliente_factory() as c:
        await iniciar_sesion(c, TEC, datos["contrasena"])
    filas = await _eventos("auth.login_exitoso")
    assert filas, "el login debe quedar auditado"
    datos_json = filas[0].valor_nuevo_json or {}
    assert "ip" in datos_json and "geo" in datos_json  # §6.9.5: IP y geolocalización aproximada
    assert filas[0].ip_origen and filas[0].user_agent is not None


async def test_auditoria_de_acceso_a_datos_sensibles(cliente, auth, datos):
    """§6.9.5 «Acceso a datos sensibles»: tabla, ID y cantidad de registros."""
    from tests.inventario_utiles import cerrar_folio, folio_en_ejecucion

    f = await folio_en_ejecucion(cliente, auth, datos)
    await cerrar_folio(cliente, auth, datos, f)
    # 1. Consulta de datos financieros.
    assert (await cliente.get(f"/api/folios/{f['id']}/costos", headers=await auth(MC))).status_code == 200
    financieros = await _eventos("acceso.datos_sensibles", 50)
    costos = [x for x in financieros if (x.valor_nuevo_json or {}).get("tabla") == "folio_costos"]
    assert costos and costos[0].recurso_id == f["id"]
    assert "registros" in (costos[0].valor_nuevo_json or {})
    # 2. Historial de un folio cerrado.
    assert (await cliente.get(f"/api/folios/{f['id']}", headers=await auth(AE))).status_code == 200
    cerrados = [x for x in await _eventos("acceso.datos_sensibles", 50)
                if (x.valor_nuevo_json or {}).get("tabla") == "folios"]
    assert cerrados and (cerrados[0].valor_nuevo_json or {}).get("estado") == "cerrado"
    # 3. Descarga de un reporte ejecutivo.
    r = await cliente.post("/api/bi/reportes/generar", headers=await auth(AE),
                           json={"tipo_reporte": "cliente", "formato": "pdf"})
    assert r.status_code == 200
    reportes = [x for x in await _eventos("acceso.datos_sensibles", 50)
                if (x.valor_nuevo_json or {}).get("tabla") == "reportes_generados"]
    assert reportes and (reportes[0].valor_nuevo_json or {}).get("tipo") == "cliente"


async def test_retencion_de_la_bitacora_de_api(cliente, auth, datos):
    """§6.9.5: 90 días las llamadas normales y 1 año los errores, purgando particiones con DETACH + DROP. P11a."""
    await cliente.get("/api/folios", headers=await auth(AP))
    await cliente.get("/api/no-existe", headers=await auth(AP))

    def particion(meses_atras: int) -> tuple[str, str, str, str]:
        hoy = datetime.now(UTC).date().replace(day=1)
        mes = hoy
        for _ in range(meses_atras):
            mes = (mes - timedelta(days=1)).replace(day=1)
        siguiente = (mes + timedelta(days=31)).replace(day=1)
        return (f"audit_accesos_api_{mes:%Y_%m}", str(mes), str(siguiente),
                datetime(mes.year, mes.month, 15, 10, tzinfo=UTC))

    # Un mes de hace 5: pasó los 90 días de las llamadas normales pero no el año de los errores.
    nombre, desde, hasta, cuando = particion(5)
    ruta = "/api/prueba-retencion"
    await _sql_dueno(f"""CREATE TABLE IF NOT EXISTS {nombre} PARTITION OF audit_accesos_api
                         FOR VALUES FROM ('{desde}') TO ('{hasta}')""")
    for codigo in (200, 404):
        await _sql("""INSERT INTO audit_accesos_api (id, created_at, metodo, ruta, codigo_respuesta, duracion_ms)
                      VALUES (gen_random_uuid(), :cuando, 'GET', :ruta, :c, 5)""", c=codigo, cuando=cuando, ruta=ruta)
    # Y otro de hace 14 meses: ahí ya ni los errores se conservan.
    viejo, desde_v, hasta_v, cuando_v = particion(14)
    await _sql_dueno(f"""CREATE TABLE IF NOT EXISTS {viejo} PARTITION OF audit_accesos_api
                         FOR VALUES FROM ('{desde_v}') TO ('{hasta_v}')""")
    await _sql("""INSERT INTO audit_accesos_api (id, created_at, metodo, ruta, codigo_respuesta, duracion_ms)
                  VALUES (gen_random_uuid(), :cuando, 'GET', '/api/prueba-retencion-vieja', 500, 5)""", cuando=cuando_v)

    from workers.tareas import purgar_accesos_api_async

    resumen = await purgar_accesos_api_async()
    soltadas = {x["particion"]: x for x in resumen}
    assert nombre in soltadas and viejo in soltadas, resumen
    assert soltadas[nombre]["errores_conservados"] == 1
    assert soltadas[nombre]["accion"] == "errores_copiados_y_soltada"
    # El error de hace 5 meses se conserva; el de hace 14 ya no.
    guardados = await _sql("SELECT ruta, codigo_respuesta FROM audit_accesos_api_errores WHERE ruta LIKE '/api/prueba-retencion%'")
    assert [(g.ruta, g.codigo_respuesta) for g in guardados] == [(ruta, 404)]
    # Las particiones viejas quedan soltadas (DETACH + DROP, sin DELETE sobre la tabla append-only).
    for tabla in (nombre, viejo):
        existe = await _sql("SELECT to_regclass(:n) AS t", n=tabla)
        assert existe[0][0] is None, f"{tabla} debe quedar soltada"


async def test_la_bitacora_de_api_no_se_puede_modificar(cliente, auth, datos):
    """§6.9.5: append-only a nivel de base de datos, también para la tabla de retención de errores."""
    for tabla in ("audit_log", "audit_accesos_api", "audit_accesos_api_errores"):
        async with nueva_sesion(CONTEXTO_SISTEMA) as db:
            try:
                await db.execute(text(f"DELETE FROM {tabla}"))
                asumio = True
            except Exception:
                asumio = False
            await db.rollback()
        assert not asumio, f"{tabla} debe rechazar DELETE incluso con el rol sistema"
        # Tampoco el dueño del esquema borra nada: la RLS de solo lectura/inserción deja el DELETE en cero filas
        # y el trigger salta en cuanto alguna coincide.
        antes = (await _sql_dueno(f"SELECT count(*) AS n FROM {tabla}"))[0].n
        try:
            await _sql_dueno(f"DELETE FROM {tabla}")
        except Exception:
            pass
        despues = (await _sql_dueno(f"SELECT count(*) AS n FROM {tabla}"))[0].n
        assert despues == antes, f"{tabla} no debe perder filas ni con el dueño del esquema"


# --------------------------------------------------- restricciones de §6.7

async def test_el_sello_de_fecha_y_la_geolocalizacion_no_son_editables(cliente, auth, datos):
    """§6.7: ningún campo de sello de fecha y hora ni de geolocalización automática puede editarlo el usuario.

    El sello lo calcula siempre el servidor (lo que manda el cliente se descarta) y la lectura original del dispositivo
    la fija el servidor: el cliente no puede hacer pasar otra por original. Un ajuste declarado queda auditado.
    """
    from tests.test_formularios import crear_formulario, publicar

    config_geo = {"precision_minima_m": 50, "radio_ajuste_m": 500, "geofencing_radio_m": 300}
    esquema = {"secciones": [{"clave": "s", "titulo": "S", "campos": [
        {"clave": "cuando", "tipo": "sello_fecha_hora", "etiqueta": "Sello", "obligatorio": False,
         "config": {"trigger": "al_enviar"}},
        {"clave": "donde", "tipo": "geolocalizacion", "etiqueta": "Ubicación", "obligatorio": False,
         "config": config_geo},
    ]}]}
    f = await crear_formulario(cliente, auth, AP, "Sellos de prueba", tipo="atencion_tecnico", esquema=esquema)
    await publicar(cliente, auth, f["id"])
    h = await auth(TEC)

    # 1. El sello y la lectura original los pone el servidor: lo que mande el cliente se descarta.
    inventado = "2001-01-01T00:00:00+00:00"
    r = await cliente.post(f"/api/formularios/{f['id']}/respuestas", headers=h, json={
        "respuestas": {"cuando": inventado,
                       "donde": {"lat": 19.4326, "lng": -99.1332, "lat_original": 1.0, "lng_original": 1.0}}})
    assert r.status_code == 201, r.text
    enviada = await cliente.post(f"/api/formularios/respuestas/{r.json()['id']}/enviar", headers=h)
    assert enviada.status_code == 200, enviada.text
    guardado = enviada.json()["respuestas_json"]
    assert guardado["cuando"] != inventado and guardado["cuando"].startswith(str(datetime.now(UTC).year))
    donde = guardado["donde"]
    assert donde["lat_original"] == donde["lat"] == 19.4326 and donde["lng_original"] == donde["lng"]
    assert donde["ajustada"] is False  # no se declaró ajuste: la original es la capturada

    # 2. Un ajuste declarado sí se acepta, pero queda en la auditoría con el valor anterior y el nuevo (§6.9.5).
    r2 = await cliente.post(f"/api/formularios/{f['id']}/respuestas", headers=h, json={
        "respuestas": {"donde": {"lat": 19.4335, "lng": -99.1332, "lat_original": 19.4326,
                                 "lng_original": -99.1332, "ajustada": True}}})
    assert r2.status_code == 201, r2.text
    enviada2 = await cliente.post(f"/api/formularios/respuestas/{r2.json()['id']}/enviar", headers=h)
    assert enviada2.status_code == 200, enviada2.text
    ajustada = enviada2.json()["respuestas_json"]["donde"]
    assert ajustada["ajustada"] is True and ajustada["lat_original"] == 19.4326
    ajustes = await _eventos("formularios.geolocalizacion_ajustada", 10)
    assert ajustes and ajustes[0].valor_anterior_json["lat"] == 19.4326
    assert ajustes[0].valor_nuevo_json["lat"] == 19.4335

    # 3. Un ajuste que excede el radio permitido se rechaza al enviar (el borrador sí se guarda).
    lejos = await cliente.post(f"/api/formularios/{f['id']}/respuestas", headers=h, json={
        "respuestas": {"donde": {"lat": 20.0, "lng": -99.1332, "lat_original": 19.4326,
                                 "lng_original": -99.1332, "ajustada": True}}})
    assert lejos.status_code == 201, lejos.text
    rechazado = await cliente.post(f"/api/formularios/respuestas/{lejos.json()['id']}/enviar", headers=h)
    assert rechazado.status_code == 422 and "radio" in rechazado.text


async def test_el_fondo_de_caja_chica_nunca_queda_negativo(cliente, auth, datos):
    """§6.7: ACMA bloquea la aprobación si el saldo del fondo es insuficiente."""
    from tests.inventario_utiles import fondo_de, gasto

    f = await fondo_de(cliente, auth, TEC)
    assert f is not None
    excesivo = await gasto(cliente, auth, subtotal=str(float(f["saldo_actual"]) + 10_000), iva="0")
    r = await cliente.post(f"/api/caja-chica/gastos/{excesivo['id']}/aprobar", headers=await auth(AP))
    assert r.status_code == 409 and r.json()["codigo"] == "SALDO_INSUFICIENTE"
    actual = await fondo_de(cliente, auth, TEC)
    assert float(actual["saldo_actual"]) >= 0


async def test_la_evidencia_de_un_folio_cerrado_no_se_puede_borrar(cliente, auth, datos):
    """§6.7: la evidencia de una orden cerrada es inmutable (retención de 5 años documentada)."""
    from tests.inventario_utiles import cerrar_folio, folio_en_ejecucion

    f = await folio_en_ejecucion(cliente, auth, datos)
    await cerrar_folio(cliente, auth, datos, f)
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        try:
            await db.execute(text("DELETE FROM folio_evidencias WHERE folio_id = :f"), {"f": f["id"]})
            await db.commit()
            borro = True
        except Exception:
            await db.rollback()
            borro = False
    assert not borro, "la evidencia del folio cerrado no debe poder borrarse"
    # El folio cerrado tampoco se puede modificar.
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        try:
            await db.execute(text("UPDATE folios SET descripcion = 'cambiada' WHERE id = :f"), {"f": f["id"]})
            await db.commit()
            cambio = True
        except Exception:
            await db.rollback()
            cambio = False
    assert not cambio


# ------------------------------------------------- cabeceras, CORS y guardias de produccion

async def test_cabeceras_de_seguridad_de_la_api(cliente, auth):
    """§6.9.5: la API no ejecuta ni embebe nada, no filtra referer y no se cachea."""
    r = await cliente.get("/api/auth/yo", headers=await auth(OP))
    csp = r.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "frame-ancestors 'none'" in csp and "base-uri 'none'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "microphone=()" in r.headers["permissions-policy"]
    assert r.headers["cross-origin-opener-policy"] == "same-origin"
    assert r.headers["cross-origin-resource-policy"] == "same-origin"
    assert r.headers["cache-control"] == "no-store"  # ninguna respuesta de datos queda en el cache del navegador


async def test_en_produccion_se_manda_hsts_y_no_hay_documentacion_publica(cliente, auth, monkeypatch):
    """La politica dura se prueba forzando el entorno: HSTS presente y CSP estricta incluso en /docs. P11a."""
    from core.config import config

    monkeypatch.setattr(type(config), "es_produccion", property(lambda self: True))
    r = await cliente.get("/api/salud")
    assert r.headers["strict-transport-security"].startswith("max-age=63072000")
    assert "includeSubDomains" in r.headers["strict-transport-security"]
    # /docs no se publica en produccion (main.py) y, si alguien lo expusiera, la CSP ya no trae unsafe-inline.
    docs = await cliente.get("/docs")
    assert "unsafe-inline" not in docs.headers["content-security-policy"]


async def test_cors_acepta_la_cabecera_csrf_y_solo_los_origenes_configurados(cliente):
    """Sin X-ACMA-CSRF en la lista, el navegador no podria renovar la sesion desde el frontend. P11a."""
    r = await cliente.options("/api/auth/refresh", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "x-acma-csrf",
    })
    assert r.status_code == 200, r.text
    permitidas = r.headers.get("access-control-allow-headers", "").lower()
    assert "x-acma-csrf" in permitidas and "authorization" in permitidas
    assert r.headers.get("access-control-allow-credentials") == "true"  # la cookie de sesion viaja con credenciales
    ajeno = await cliente.options("/api/auth/refresh", headers={
        "Origin": "https://malicioso.example", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "x-acma-csrf",
    })
    assert "access-control-allow-origin" not in ajeno.headers


def test_la_configuracion_de_produccion_rechaza_secretos_de_ejemplo():
    """§6.9.5: produccion no arranca con los valores de ejemplo del .env. P11a."""
    import pytest

    from core.config import Configuracion

    base = {"acma_entorno": "produccion", "mfa_obligatorio": True, "cors_origenes": "https://acma.example",
            "database_url": "postgresql+asyncpg://u:p@h/d", "database_migrations_url": "postgresql+asyncpg://u:p@h/d"}
    with pytest.raises(ValueError):
        Configuracion(**{**base, "jwt_secreto": "cambiar_en_produccion"})
    with pytest.raises(ValueError):
        Configuracion(**{**base, "jwt_secreto": "x" * 64, "cors_origenes": "*"})
    with pytest.raises(ValueError):
        Configuracion(**{**base, "jwt_secreto": "x" * 64, "mfa_obligatorio": False})


# -------------------------------------------------- cifrado en reposo (diseño §2.5: llaves por tenant)

async def test_los_archivos_se_guardan_cifrados_con_llave_por_dueno(cliente, auth, datos):
    """Nada queda en claro en el Object Storage y cada dueño tiene su propia llave. P11a."""
    from core.security import SOBRE_MAGIA, clave_por_dueno, descifrar_archivo
    from services.almacenamiento import obtener_almacenamiento

    almacen = obtener_almacenamiento()
    png = (b"\x89PNG\r\n\x1a\n" + b"logo-en-claro-" * 20)
    r = await cliente.post(f"/api/prestadores/{datos['prestador']}/logo", headers=await auth(AP),
                           files={"archivo": ("logo.png", png, "image/png")})
    assert r.status_code == 200, r.text
    clave = r.json()["logo_key"]

    crudo = almacen.backend.leer(clave)  # lo que de verdad quedó escrito
    assert crudo.startswith(SOBRE_MAGIA), "el archivo debe guardarse dentro del sobre cifrado"
    assert b"logo-en-claro-" not in crudo, "el contenido no puede quedar en claro"
    assert str(datos["prestador"]).encode() in crudo[:64], "el sobre declara de quién es la llave"
    assert almacen.leer(clave) == png  # y la lectura normal lo devuelve intacto

    # La llave es por dueño: la del cliente demo no abre el archivo del prestador.
    assert clave_por_dueno(str(datos["tenant"])) != clave_por_dueno(str(datos["prestador"]))
    import pytest
    with pytest.raises(Exception):
        descifrar_archivo(crudo.replace(str(datos["prestador"]).encode(), str(datos["otro_prestador"]).encode(), 1),
                          clave_objeto=clave)


async def test_un_archivo_no_sirve_en_otra_ruta_ni_sin_sobre_se_pierde(cliente, auth, datos):
    """La ruta va firmada (no se puede mover un PDF de un cliente al folio de otro) y lo viejo sigue legible."""
    import pytest

    from core.security import cifrar_archivo, descifrar_archivo

    sobre = cifrar_archivo(b"evidencia", clave_objeto="folios/a/foto.jpg", dueno=str(datos["tenant"]))
    assert descifrar_archivo(sobre, clave_objeto="folios/a/foto.jpg") == b"evidencia"
    with pytest.raises(Exception):
        descifrar_archivo(sobre, clave_objeto="folios/b/foto.jpg")
    # Compatibilidad: lo escrito antes de P11a no tiene sobre y se devuelve tal cual.
    assert descifrar_archivo(b"bytes de antes de P11a", clave_objeto="folios/a/foto.jpg") == b"bytes de antes de P11a"
