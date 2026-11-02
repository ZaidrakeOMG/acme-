"""Datos demo de P10: contrato en modalidad iguala (20 correctivos y 8 preventivos al mes) con SLA y penalización por las
5 severidades, `folio_sla` calculado para todos los folios del seed (con al menos 3 incumplidos, 1 pausa por reasignación y
2 exclusiones —una aprobada y una pendiente—), penalizaciones de los últimos 3 meses, configuración de alertas por tenant
con una supresión activa y 2 escalaciones a Dirección en el historial, y 2 reportes programados. Idempotente."""
import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from core.rls import CONTEXTO_SISTEMA
from models.alertas import AlertaCatalogo, AlertaConfiguracion, AlertaHistorial, AlertaSupresion
from models.base import (
    CausaExclusionSLA, EstadoAlerta, EstadoPenalizacion, FormatoReporte, ModalidadContrato, MotivoPausaSLA,
    NivelSeveridad, PeriodicidadReporte, Rol,
)
from models.contratos import Contrato, ContratoSLA
from models.folios import EstadoFolio, Folio, FolioSLA
from models.organizaciones import Prestador, Tenant
from models.reportes import ReporteProgramado
from models.sla import FolioSLAExclusion, FolioSLAPausa
from models.usuarios import Usuario
from scripts.seed_folios import actor_de
from services import sla_service

# §6.10.1: respuesta y resolución en la unidad firmada, con su equivalente en horas y la penalización por severidad.
SLAS_IGUALA = {
    NivelSeveridad.critica: (2, "horas", 8, "horas", "porcentaje", Decimal("10")),
    NivelSeveridad.alta: (4, "horas", 1, "dias", "porcentaje", Decimal("7")),
    NivelSeveridad.media: (8, "horas", 3, "dias", "porcentaje", Decimal("5")),
    NivelSeveridad.baja: (1, "dias", 1, "semanas", "monto", Decimal("1500")),
    NivelSeveridad.muy_baja: (3, "dias", 1, "meses", "monto", Decimal("500")),
}
EN_HORAS = {"horas": 1, "dias": 24, "semanas": 168, "meses": 720}
# Umbrales propios del cliente, dentro del rango del catálogo (§6.9.6).
CONFIGS_TENANT = [("SLA_RESPUESTA_EN_RIESGO", 70), ("PRESUPUESTO_ALERTA_2", 85), ("FOLIO_SIN_CLASIFICAR", 12)]


async def sembrar_sla(db) -> bool:
    prestador = (await db.execute(select(Prestador).where(Prestador.rfc == "PDE200101AB1"))).scalar_one_or_none()
    tenant = (await db.execute(select(Tenant).where(Tenant.rfc == "CDE200101XY2"))).scalar_one_or_none()
    if prestador is None or tenant is None:
        return False
    if (await db.execute(select(Contrato.id).where(Contrato.modalidad == ModalidadContrato.iguala))).first():
        return False
    # §6.10.1: la relación tenant–prestador se formaliza en UN contrato. P10 convierte el demo a modalidad iguala en
    # lugar de agregar un segundo contrato activo (que dejaría indefinido qué SLA y qué horario de servicio aplican).
    vigente = (await db.execute(select(Contrato).where(
        Contrato.tenant_id == tenant.id, Contrato.prestador_id == prestador.id,
        Contrato.fecha_fin >= date.today()).order_by(Contrato.fecha_inicio.desc()))).scalars().first()
    usuarios = {u.email: u for u in (await db.execute(select(Usuario))).scalars()}
    admin_prestador, admin_empresa = usuarios["admin.prestador@acma.dev"], usuarios["admin.empresa@acma.dev"]
    mesa = usuarios["mesa.control@acma.dev"]
    a_ap, a_ae, a_mesa = (actor_de(u) for u in (admin_prestador, admin_empresa, mesa))
    hoy = date.today()
    ahora = datetime.now(UTC)

    # ------------------------------------------------ contrato de iguala
    from models.catalogos import NivelSeveridadCatalogo

    niveles = {n.clave: n for n in (await db.execute(select(NivelSeveridadCatalogo).where(
        NivelSeveridadCatalogo.prestador_id == prestador.id))).scalars()}
    from models.base import TipoPenalizacion, UnidadTiempo

    if vigente is None:
        return False
    contrato = vigente
    contrato.modalidad = ModalidadContrato.iguala
    contrato.folios_correctivos_iguala = 20
    contrato.tarifa_iguala_mensual = Decimal("48000.00")
    contrato.moneda = "MXN"
    contrato.preventivos_iguala_json = {"cantidad": 8, "periodicidad": "mensual",
                                        "puntos_a_revisar": "Según la biblioteca de manuales del prestador"}
    await db.flush()
    existentes = {s.nivel_severidad: s for s in (await db.execute(select(ContratoSLA).where(
        ContratoSLA.contrato_id == contrato.id))).scalars()}
    for nivel, (resp, u_resp, resol, u_resol, tipo, valor) in SLAS_IGUALA.items():
        fila = existentes.get(nivel)
        campos = dict(tiempo_respuesta=resp, tiempo_resolucion=resol,
                      tiempo_respuesta_horas=resp * EN_HORAS[u_resp], tiempo_resolucion_horas=resol * EN_HORAS[u_resol],
                      unidad_expresion=UnidadTiempo(u_resol), penalizacion_tipo=TipoPenalizacion(tipo),
                      penalizacion_valor=valor)
        if fila is None:
            db.add(ContratoSLA(tenant_id=tenant.id, prestador_id=prestador.id, contrato_id=contrato.id,
                               nivel_severidad=nivel, nivel_severidad_id=niveles[nivel.value].id, **campos))
        else:
            for k, v in campos.items():
                setattr(fila, k, v)
    await db.flush()

    # ----------------------------------------- contador de todos los folios
    folios = list((await db.execute(select(Folio).where(Folio.tenant_id == tenant.id).order_by(Folio.numero_folio))).scalars())
    cerrados = [f for f in folios if f.estado == EstadoFolio.cerrado]
    for folio in folios:
        f = await sla_service.fijar_limites(db, folio)
        if f is None:
            continue
        if f.tiempo_inicio is None:
            f.tiempo_inicio = folio.capturado_at
        if folio.estado != EstadoFolio.capturado and f.tiempo_respuesta_at is None:
            f.tiempo_respuesta_at = (folio.fecha_inicio_atencion or folio.capturado_at + timedelta(hours=1))
        if folio.estado == EstadoFolio.cerrado:
            f.tiempo_fin = folio.fecha_cierre
    await db.flush()

    # 1 pausa por reasignación: el folio reasignado del seed de P06.
    reasignado = next((f for f in folios if f.estado in (EstadoFolio.asignado, EstadoFolio.en_ejecucion)), None)
    if reasignado is not None:
        inicio = (reasignado.fecha_inicio_atencion or reasignado.capturado_at) + timedelta(minutes=10)
        db.add(FolioSLAPausa(folio_id=reasignado.id, tenant_id=reasignado.tenant_id, prestador_id=reasignado.prestador_id,
                             motivo=MotivoPausaSLA.reasignacion, inicio=inicio, fin=inicio + timedelta(minutes=35), minutos=35,
                             notas="Reasignación forzada del despachador (§6.10.1)"))
    await db.flush()

    # 2 exclusiones: una aprobada (descuenta) y una pendiente de decisión del Admin empresa.
    if len(cerrados) >= 2:
        uno, dos = cerrados[0], cerrados[1]
        aprobada = await sla_service.registrar_exclusion(
            db, a_mesa, uno, causa=CausaExclusionSLA.cliente_sin_acceso,
            descripcion="La sucursal no dio acceso al cuarto de máquinas hasta el cierre del turno de la tarde.",
            inicio=uno.capturado_at + timedelta(hours=1), fin=uno.capturado_at + timedelta(hours=5))
        await sla_service.decidir_exclusion(db, a_ae, aprobada, aprobada=True, razon="Confirmado con el gerente de la UN")
        await sla_service.registrar_exclusion(
            db, a_mesa, dos, causa=CausaExclusionSLA.refaccion_no_disponible_mercado,
            descripcion="El compresor estuvo descontinuado en el mercado nacional durante tres días hábiles.",
            inicio=dos.capturado_at + timedelta(hours=6), fin=dos.capturado_at + timedelta(hours=30))
    await db.flush()

    # Al menos 3 incumplidos: se aprieta el límite de los 3 folios cerrados más lentos.
    for folio in cerrados[:3]:
        f = await sla_service.fila(db, folio)
        if f is None or f.tiempo_inicio is None or f.tiempo_fin is None:
            continue
        reales = max(60, int((f.tiempo_fin - f.tiempo_inicio).total_seconds() // 60))
        f.limite_sla_min = max(30, reales // 2)
        f.limite_respuesta_min = max(15, f.limite_sla_min // 3)
    await db.flush()
    for folio in cerrados:
        await sla_service.recalcular(db, folio)
    await db.flush()

    # --------------------------------------- penalizaciones de 3 meses
    for atras in (3, 2, 1):
        mes = (date(hoy.year, hoy.month, 1) - timedelta(days=1)).replace(day=1)
        for _ in range(atras - 1):
            mes = (mes - timedelta(days=1)).replace(day=1)
        registro = await sla_service.consolidar_penalizaciones(db, contrato, mes.strftime("%Y-%m"))
        if atras == 3:
            registro.estado = EstadoPenalizacion.cerrado
            registro.revisado_por, registro.revisado_at = admin_prestador.id, ahora - timedelta(days=60)
            registro.cerrado_at = ahora - timedelta(days=58)
        elif atras == 2:
            registro.estado = EstadoPenalizacion.revisado
            registro.revisado_por, registro.revisado_at = admin_prestador.id, ahora - timedelta(days=28)
    await sla_service.consumo_iguala(db, contrato, hoy.strftime("%Y-%m"))
    await db.flush()

    # ----------------------------------- configuración central de alertas
    catalogo = {c.clave: c for c in (await db.execute(select(AlertaCatalogo))).scalars()}
    for clave, umbral in CONFIGS_TENANT:
        cat = catalogo.get(clave)
        if cat is None:
            continue
        db.add(AlertaConfiguracion(clave_alerta=clave, tenant_id=tenant.id, umbral_valor=Decimal(umbral),
                                   canales_json=["app", "email"], destinatarios_roles_json=["admin_empresa", "admin_un"],
                                   activa=True))
    db.add(AlertaConfiguracion(clave_alerta="SLA_INCUMPLIDO", prestador_id=prestador.id, umbral_valor=Decimal("0"),
                               canales_json=["app", "email", "push"],
                               destinatarios_roles_json=["admin_prestador", "mesa_control"], activa=True))
    # Supresión activa: el cliente pidió silenciar la alerta de clasificación durante el inventario anual.
    if folios:
        db.add(AlertaSupresion(clave_alerta="FOLIO_SIN_CLASIFICAR", tenant_id=tenant.id, entidad_id=folios[0].id,
                               suprimida_por=admin_empresa.id,
                               razon=f"Inventario anual en la UN del folio {folios[0].numero_folio}: se clasifica la próxima semana",
                               desde=ahora - timedelta(days=1), hasta=ahora + timedelta(days=6), activa=True))
    # 2 escalaciones a Dirección en el historial, con su alerta origen.
    for clave_origen, clave_escala, dias in (("COTIZACION_SIN_RESPUESTA", "COTIZACION_ESCALADA_DIRECCION", 12),
                                             ("SLA_INCUMPLIDO", "SLA_INCUMPLIDO_ESCALADO_DIRECCION", 5)):
        if clave_origen not in catalogo or clave_escala not in catalogo:
            continue
        origen = AlertaHistorial(clave_alerta=clave_origen, tenant_id=tenant.id, prestador_id=prestador.id,
                                 entidad_tipo="demo", umbral_en_momento=Decimal("7"), estado=EstadoAlerta.disparada,
                                 datos_contexto_json={"demo": True}, timestamp_disparo=ahora - timedelta(days=dias),
                                 escalada=True)
        db.add(origen)
        await db.flush()
        db.add(AlertaHistorial(clave_alerta=clave_escala, tenant_id=tenant.id, prestador_id=prestador.id,
                               entidad_tipo="demo", umbral_en_momento=Decimal("7"), estado=EstadoAlerta.disparada,
                               datos_contexto_json={"alerta_origen_id": str(origen.id), "clave_origen": clave_origen,
                                                    "disparo_origen": (ahora - timedelta(days=dias)).isoformat()},
                               timestamp_disparo=ahora - timedelta(days=dias - 4)))
    await db.flush()

    # ------------------------------------------------ reportes programados
    db.add(ReporteProgramado(tenant_id=tenant.id, nombre="Reporte ejecutivo mensual", tipo_reporte="cliente",
                             formato=FormatoReporte.pdf, periodicidad=PeriodicidadReporte.mensual, dia_hora="1 08:00",
                             destinatarios_json=[str(admin_empresa.id)], created_by=admin_empresa.id,
                             filtros_json={"comparativos": True}))
    db.add(ReporteProgramado(prestador_id=prestador.id, nombre="Cierre de jornada", tipo_reporte="jornada",
                             formato=FormatoReporte.pdf, periodicidad=PeriodicidadReporte.diaria, dia_hora="22:30",
                             destinatarios_json=[str(usuarios["supervisor.prestador@acma.dev"].id)]
                             if "supervisor.prestador@acma.dev" in usuarios else [],
                             created_by=admin_prestador.id))
    await db.flush()
    return True


async def main() -> None:
    from core.db import nueva_sesion

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        ok = await sembrar_sla(db)
        await db.commit()
    print("Contrato de iguala, contador de SLA, penalizaciones, alertas y reportes demo creados."
          if ok else "Ya existían (o falta el seed base).")


if __name__ == "__main__":
    asyncio.run(main())
