"""Minuta del día por WhatsApp (§7.5): resumen ejecutivo de máximo 5 puntos con enlace firmado al PDF completo,
enlace corto propio de ACMA y registro del clic. F2-02."""
import uuid
from datetime import date

from sqlalchemy import select

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from tests.folios_utiles import AP, AUN
from tests.mensajeria_utiles import limpiar_stub, ultimo_envio
from tests.seguimiento_utiles import configurar_minuta, folio_con_hallazgo, generar_minuta, limpiar_minutas_hoy


async def test_la_minuta_llega_por_whatsapp_con_maximo_cinco_puntos_y_enlace_al_pdf(cliente, auth, datos):
    """§7.5: «resumen ejecutivo en texto, máx. 5 bullets, + enlace al PDF completo» para el Admin UN."""
    limpiar_stub()
    await limpiar_minutas_hoy(datos["tenant"])
    await configurar_minuta(cliente, auth, datos, modo="automatica")
    folio, _ = await folio_con_hallazgo(cliente, auth, datos, "Fuga de refrigerante en la unidad condensadora",
                                        "critica")
    minutas = await generar_minuta(cliente, auth, datos)
    minuta = next(m for m in minutas if m["tipo"] == "un" and m["un_id"] == folio["un_id"])

    envio = await ultimo_envio(AUN, "whatsapp")
    assert envio is not None and envio["plantilla"] == "minuta_disponible", envio
    assert envio["estado"] == "enviado" and envio["evento"] == "minuta.enviada"
    assert "Minuta del" in envio["cuerpo"] and "{{" not in envio["cuerpo"]
    # El resumen va en un solo parámetro con los puntos separados por « · » (Meta no acepta saltos de línea en
    # los parámetros de una plantilla): como máximo cinco puntos.
    resumen = envio["cuerpo"].split("Lo más crítico de hoy: ")[1].split("\n")[0]
    assert 1 <= len(resumen.split(" · ")) <= 5, resumen
    assert "urgencia alta" in resumen or "en rojo" in resumen or "responder" in resumen

    # El botón abre el PDF con un enlace firmado de corta duración, no la pantalla con sesión.
    assert envio["destino"].startswith("/api/mensajeria/minutas/") and envio["destino"].endswith(".pdf")
    r = await cliente.get(envio["destino"])
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"
    assert minuta["hash_pdf"]

    # Un token inventado no abre nada.
    assert (await cliente.get("/api/mensajeria/minutas/token-falso.pdf")).status_code == 403


async def test_el_enlace_corto_resuelve_el_destino_y_registra_el_clic(cliente, auth, datos):
    limpiar_stub()
    await limpiar_minutas_hoy(datos["tenant"])
    await configurar_minuta(cliente, auth, datos, modo="automatica")
    await folio_con_hallazgo(cliente, auth, datos, "Compresor con ruido anormal y vibración", "alta")
    await generar_minuta(cliente, auth, datos)
    envio = await ultimo_envio(AUN, "whatsapp")
    codigo = envio["codigo_enlace"]
    assert codigo and len(codigo) <= 16

    # Sin sesión: lo abre quien recibió el mensaje en su teléfono.
    r = await cliente.get(f"/api/mensajeria/enlaces/{codigo}")
    assert r.status_code == 200, r.text
    assert r.json()["destino"] == envio["destino"] and r.json()["canal"] == "whatsapp"
    r = await cliente.get("/api/mensajeria/enlaces/noexiste")
    assert r.status_code == 404

    # El clic queda registrado una sola vez (para saber si el aviso sirvió de algo).
    from models.mensajeria import MensajeriaEnvio

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        fila = (await db.execute(select(MensajeriaEnvio).where(MensajeriaEnvio.id == envio["id"]))).scalar_one()
        assert fila.abierto_at is not None


async def _minuta_vacia(datos) -> uuid.UUID:
    """Una minuta sin secciones, para probar el resumen cuando no hay nada crítico."""
    from models.minutas import Minuta, TipoMinuta

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        m = Minuta(id=uuid.uuid4(), tenant_id=datos["tenant"], prestador_id=datos["prestador"], un_id=None,
                   fecha=date(2026, 1, 15), tipo=TipoMinuta.global_)
        db.add(m)
        await db.commit()
        return m.id


async def test_sin_nada_critico_el_resumen_lo_dice(datos):
    from models.minutas import Minuta
    from services import mensajeria_service

    minuta_id = await _minuta_vacia(datos)
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        m = await db.get(Minuta, minuta_id)
        puntos = await mensajeria_service.resumen_minuta(db, m)
    assert puntos == ["sin pendientes críticos"]


async def test_el_resumen_se_queda_en_cinco_puntos(datos):
    """Con más candidatos que cupo, se mandan los cinco primeros en el orden de §7.5."""
    from models.minutas import Minuta, MinutaSeccion
    from services import mensajeria_service

    minuta_id = await _minuta_vacia(datos)
    secciones = {
        "contadores": {"cotizaciones": {"total": 9, "color": "rojo"}, "reprogramacion": {"total": 4, "color": "rojo"},
                       "seguimiento_interno": {"total": 1, "color": "verde"}},
        "hallazgos": {"items": [{"urgencia": "critica", "estado_respuesta": "pendiente"},
                                {"urgencia": "alta", "estado_respuesta": "pendiente"},
                                {"urgencia": "media", "estado_respuesta": "pendiente"}]},
        "preventivos": {"items": [{"retraso": True}, {"retraso": True}]},
        "cotizaciones": {"por_vencer": [{"folio": "F-1"}, {"folio": "F-2"}], "total": 2},
    }
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        for orden, (clave, contenido) in enumerate(secciones.items()):
            db.add(MinutaSeccion(minuta_id=minuta_id, tenant_id=datos["tenant"], prestador_id=datos["prestador"],
                                 seccion=clave, orden=orden, contenido_json=contenido))
        await db.flush()
        m = await db.get(Minuta, minuta_id)
        puntos = await mensajeria_service.resumen_minuta(db, m)
        await db.commit()
    assert len(puntos) == 5
    assert "2 indicador(es) en rojo" in puntos[0]
    assert "2 hallazgo(s) de urgencia alta, 1 crítico(s)" == puntos[1]
    assert puntos[2] == "2 preventivo(s) con retraso"
    assert puntos[3] == "2 cotización(es) por vencer"
    assert "esperan tu respuesta" in puntos[4]


async def test_la_plantilla_de_la_minuta_no_lleva_montos(cliente, auth):
    """La minuta por WhatsApp resume el día sin un solo dato financiero (§6.9.5)."""
    r = await cliente.get("/api/mensajeria/plantillas", headers=await auth(AP), params={"canal": "whatsapp"})
    minuta = next(p for p in r.json() if p["clave"] == "minuta_disponible")
    assert set(minuta["variables"]) == {"fecha", "ambito", "resumen"}
    assert "$" not in minuta["cuerpo"] and "monto" not in minuta["cuerpo"].lower()
