"""Acceso cruzado entre tenants y prestadores por HTTP (ACT-1.6). P11a.

La lista de rutas se saca de la propia app: para cada GET con un solo parámetro de ruta se pide un recurso **real del
cliente demo** con la sesión de un usuario de otro cliente y de otro prestador. Ninguna debe responder 200. Así, cuando
un prompt agrega un router nuevo, la prueba lo cubre sola; si no hay con qué probarlo, lo reporta como no cubierto.
"""
import re

import pytest
from sqlalchemy import text

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA

# Usuarios del «otro» cliente y del «otro» prestador que crea conftest.
OTRO_AE = "admin.otro@acma.dev"
OTRO_OP = "operador.otro@acma.dev"
OTRO_AP = "admin.otroprestador@acma.dev"
AJENOS = [OTRO_AE, OTRO_OP, OTRO_AP]

# Parámetro de ruta → de dónde sale un id real del cliente demo. None = no se puede probar con un id ajeno
# (recursos de plataforma o parámetros que no son identificadores).
FUENTES: dict[str, str | None] = {
    "folio_id": "SELECT id FROM folios ORDER BY capturado_at LIMIT 1",
    # Las plantillas base de plataforma (prestador_id NULL) son compartidas a propósito: para el barrido se usa
    # un formulario del cliente demo, que nadie de fuera debe ver.
    "formulario_id": "SELECT id FROM formularios WHERE tenant_id IS NOT NULL ORDER BY created_at LIMIT 1",
    "contrato_id": "SELECT id FROM contratos LIMIT 1",
    "tenant_id": "SELECT id FROM tenants WHERE rfc = 'CDE200101XY2'",
    "unidad_id": "SELECT id FROM unidades_negocio LIMIT 1",
    "un_id": "SELECT id FROM unidades_negocio LIMIT 1",
    "tecnico_id": "SELECT id FROM tecnicos LIMIT 1",
    "equipo_id": "SELECT id FROM equipos LIMIT 1",
    "respuesta_id": "SELECT id FROM formulario_respuestas LIMIT 1",
    "chat_id": "SELECT id FROM chats LIMIT 1",
    "minuta_id": "SELECT id FROM minutas LIMIT 1",
    "registro_id": "SELECT id FROM cotizaciones LIMIT 1",
    "presupuesto_id": "SELECT id FROM presupuestos LIMIT 1",
    "usuario_id": "SELECT id FROM usuarios WHERE email = 'operador@acma.dev'",
    "grupo_id": "SELECT id FROM grupos_un LIMIT 1",
    "plan_id": "SELECT id FROM planes_mantenimiento LIMIT 1",
    "hallazgo_id": "SELECT id FROM hallazgos LIMIT 1",
    "te_id": "SELECT id FROM trabajos_especiales LIMIT 1",
    "oc_id": "SELECT id FROM ordenes_compra LIMIT 1",
    "gasto_id": "SELECT id FROM gastos_caja_chica LIMIT 1",
    "poliza_id": "SELECT id FROM polizas_exportacion LIMIT 1",
    "exportacion_id": "SELECT id FROM erp_exportaciones LIMIT 1",
    "reporte_id": "SELECT id FROM reportes_generados LIMIT 1",
    "alerta_id": "SELECT id FROM alertas_historial LIMIT 1",
    "exclusion_id": "SELECT id FROM folio_sla_exclusiones LIMIT 1",
    "programado_id": "SELECT id FROM reportes_programados LIMIT 1",
    "importacion_id": "SELECT id FROM importaciones_catalogo LIMIT 1",
    "prestador_id": "SELECT id FROM prestadores WHERE rfc = 'PDE200101AB1'",
    # F2-01: biblioteca del prestador demo y contenido de servicio del cliente demo.
    "manual_id": "SELECT id FROM biblioteca_manuales WHERE activo ORDER BY created_at LIMIT 1",
    "contenido_id": "SELECT id FROM contenido_servicio WHERE activo ORDER BY created_at LIMIT 1",
    # F2-02: las plantillas de mensajería del prestador demo. Las base de plataforma (prestador_id NULL) son
    # compartidas a propósito, como las plantillas base de formularios, así que el barrido usa una propia.
    "plantilla_id": "SELECT id FROM mensajeria_plantillas WHERE prestador_id IS NOT NULL ORDER BY created_at LIMIT 1",
    # F2-04: un medidor de un equipo del cliente demo (su historial de reinicios y reemplazos).
    "medidor_id": "SELECT id FROM equipo_medidores WHERE activo ORDER BY created_at LIMIT 1",
    # No son identificadores de recursos de un cliente: el valor no revela datos ajenos.
    "catalogo": None,
    "modulo": None,
    "nombre": None,
    "clave": None,
    # F2-02: el enlace corto `/l/{codigo}` y el PDF firmado de la minuta son **públicos a propósito**: los abre
    # quien recibió el mensaje en su teléfono, que no tiene sesión en ese navegador. El secreto es el código (8
    # caracteres aleatorios) y el token firmado, no la sesión; ver decisiones 152 y 153 de CONTEXTO.md.
    "codigo": None,
    "token": None,
}


def rutas_de_un_parametro() -> list[tuple[str, str]]:
    """(ruta, parámetro) de cada GET de la app con exactamente un parámetro de ruta."""
    import main

    salida = []
    for ruta, ops in main.app.openapi()["paths"].items():
        if "get" not in ops or not ruta.startswith("/api/"):
            continue
        nombres = re.findall(r"\{(\w+)\}", ruta)
        if len(nombres) == 1:
            salida.append((ruta, nombres[0]))
    return sorted(salida)


async def _id_real(consulta: str) -> str | None:
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        fila = (await db.execute(text(consulta))).first()
        return str(fila[0]) if fila else None


async def test_todo_parametro_de_ruta_tiene_fuente_declarada():
    """Si un prompt agrega una ruta con un parámetro nuevo, aquí se nota y hay que declararlo arriba."""
    faltantes = sorted({p for _, p in rutas_de_un_parametro()} - set(FUENTES))
    assert not faltantes, f"declara en FUENTES de dónde sacar un id real para: {faltantes}"


@pytest.mark.parametrize("email", AJENOS)
async def test_ningun_recurso_ajeno_responde_200(cliente_factory, auth, datos, email):
    """ACT-1.6: ningún GET con id de otro cliente o prestador devuelve 200 para un usuario ajeno."""
    probadas: list[str] = []
    sin_dato: list[str] = []
    fugas: list[str] = []
    errores: list[str] = []
    async with cliente_factory() as c:
        h = await auth(email)
        for ruta, parametro in rutas_de_un_parametro():
            consulta = FUENTES[parametro]
            if consulta is None:
                continue
            valor = await _id_real(consulta)
            if valor is None:
                sin_dato.append(ruta)
                continue
            url = ruta.replace(f"{{{parametro}}}", valor)
            r = await c.get(url, headers=h)
            probadas.append(url)
            if r.status_code == 200:
                fugas.append(url)
            elif r.status_code >= 500:  # 401/403/404/409/422 son respuestas válidas; caerse no lo es
                errores.append(f"{url} -> {r.status_code}")
    # La prueba debe estar cubriendo de verdad: si casi nada se probó, algo se rompió en el armado.
    assert len(probadas) >= 44, f"solo se probaron {len(probadas)} rutas; sin datos: {sin_dato}"
    assert not fugas, f"{email} leyó recursos de otro dueño: " + ", ".join(fugas)
    assert not errores, f"la RLS no debe tumbar la API: " + ", ".join(errores)


async def test_el_prestador_ajeno_no_ve_folios_ni_costos_del_cliente_demo(cliente_factory, auth, datos):
    """Las dos rutas más sensibles, con su assert explícito además del barrido."""
    folio = await _id_real("SELECT id FROM folios WHERE estado = 'cerrado' ORDER BY fecha_cierre DESC LIMIT 1")
    assert folio, "el seed debe dejar folios cerrados"
    async with cliente_factory() as c:
        for email in (OTRO_AP, OTRO_AE):
            h = await auth(email)
            assert (await c.get(f"/api/folios/{folio}", headers=h)).status_code in (403, 404)
            assert (await c.get(f"/api/folios/{folio}/costos", headers=h)).status_code in (403, 404)
            assert (await c.get(f"/api/sla/folios/{folio}", headers=h)).status_code in (403, 404)
        # Y sus listados no mezclan datos del cliente demo.
        lista = (await c.get("/api/folios", headers=await auth(OTRO_AE))).json()
        assert all(f["tenant_id"] != str(datos["tenant"]) for f in lista)


async def test_la_plantilla_base_de_plataforma_si_es_compartida(cliente_factory, auth, datos):
    """El contrapeso del barrido: lo que la RLS comparte a propósito debe seguir visible (§4.3 plantillas base)."""
    plantilla = await _id_real("SELECT id FROM formularios WHERE es_plantilla_base AND prestador_id IS NULL LIMIT 1")
    assert plantilla, "el seed debe dejar plantillas base de plataforma"
    async with cliente_factory() as c:
        for email in AJENOS:
            r = await c.get(f"/api/formularios/{plantilla}", headers=await auth(email))
            assert r.status_code == 200, f"{email} debería ver la plantilla base: {r.text}"
            assert r.json()["es_plantilla_base"] is True
