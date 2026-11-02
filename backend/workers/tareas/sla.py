"""Tareas de P10: penalizaciones y consumo de iguala del mes, reportes programados y cierre de jornada."""
import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from core.dependencias import Actor
from models.base import Dominio, EstadoRegistro, FormatoReporte, ModalidadContrato, PeriodicidadReporte, Rol
from models.contratos import Contrato
from models.reportes import ReporteProgramado
from models.usuarios import Usuario
from services import bi_service, notificaciones_service, reportes_service, sla_service
from workers.celery_app import celery_app
from workers.tareas import sesion_tarea

log = logging.getLogger("acma.tareas.sla")


def _actor_sistema(tenant_id=None, prestador_id=None) -> Actor:
    return Actor(id=None, email="sistema@acma", nombre="sistema", rol=Rol.superadmin, dominio=Dominio.plataforma,
                 tenant_id=tenant_id, prestador_id=prestador_id, sesion_id=None)


def _mes_anterior(hoy: date | None = None) -> str:
    hoy = hoy or date.today()
    primero = hoy.replace(day=1)
    return (primero - timedelta(days=1)).strftime("%Y-%m")


async def consolidar_periodo_async(periodo: str | None = None, url: str | None = None) -> dict:
    """Consolida penalizaciones de todos los contratos y el consumo de iguala de los que la tienen (§6.10.1)."""
    periodo = periodo or _mes_anterior()
    resumen = {"periodo": periodo, "contratos": 0, "penalizaciones": 0, "iguala": 0, "monto": "0"}
    total = 0
    async with sesion_tarea(url=url) as db:
        contratos = list((await db.execute(select(Contrato).where(Contrato.estado == EstadoRegistro.activo))).scalars())
        for c in contratos:
            resumen["contratos"] += 1
            registro = await sla_service.consolidar_penalizaciones(db, c, periodo)
            if registro.folios_incumplidos:
                resumen["penalizaciones"] += 1
                total += int(registro.monto_penalizacion)
            if c.modalidad == ModalidadContrato.iguala:
                await sla_service.consumo_iguala(db, c, periodo)
                resumen["iguala"] += 1
        await db.commit()
    resumen["monto"] = str(total)
    return resumen


async def enviar_reportes_async(url: str | None = None, hoy: date | None = None) -> dict:
    """Genera y envía por correo los reportes programados que toca hoy (ACT-8.4)."""
    hoy = hoy or date.today()
    resumen = {"revisados": 0, "enviados": 0, "errores": 0}
    async with sesion_tarea(url=url) as db:
        programados = list((await db.execute(select(ReporteProgramado).where(ReporteProgramado.activo.is_(True)))).scalars())
        for r in programados:
            resumen["revisados"] += 1
            if not reportes_service.toca_hoy(r, hoy):
                continue
            try:
                desde, hasta = reportes_service.periodo_de(r, hoy)
                f = bi_service.Filtro(desde, hasta, tenant_id=r.tenant_id, prestador_id=r.prestador_id)
                actor = _actor_sistema(r.tenant_id, r.prestador_id)
                registro, archivo = await reportes_service.generar(db, actor, tipo=r.tipo_reporte, formato=r.formato,
                                                                   filtro=f, programado=r)
                destinos = [u for u in r.destinatarios_json]
                if destinos:
                    ext = "pdf" if r.formato == FormatoReporte.pdf else "xlsx"
                    await notificaciones_service.notificar(
                        db, "reporte.programado", destinos,
                        {"tipo": r.tipo_reporte, "periodo": f"{desde} a {hasta}", "reporte_id": str(registro.id)},
                        asunto=f"{r.nombre} · {desde} a {hasta}",
                        cuerpo=f"Adjuntamos el reporte «{r.nombre}» del período {desde} a {hasta}.",
                        url="/bi/reportes", tenant_id=r.tenant_id, prestador_id=r.prestador_id, canales=["email", "app"],
                        adjuntos=[{"nombre": f"{r.tipo_reporte}-{desde}.{ext}", "clave": registro.archivo_key,
                                   "mime": ("application/pdf" if ext == "pdf"
                                            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}])
                r.ultimo_envio_at = datetime.now(UTC)
                resumen["enviados"] += 1
            except Exception:
                resumen["errores"] += 1
                log.exception("Error generando el reporte programado %s", r.id)
        await db.commit()
    return resumen


async def cierre_jornada_async(url: str | None = None) -> dict:
    """Reporte de cierre de jornada por correo al Supervisor del prestador (§5.2)."""
    from models.organizaciones import Prestador

    resumen = {"prestadores": 0, "enviados": 0}
    hoy = date.today()
    async with sesion_tarea(url=url) as db:
        prestadores = list((await db.execute(select(Prestador).where(Prestador.estado == EstadoRegistro.activo))).scalars())
        for p in prestadores:
            resumen["prestadores"] += 1
            destinos = list((await db.execute(select(Usuario.id).where(
                Usuario.prestador_id == p.id, Usuario.estado == EstadoRegistro.activo,
                Usuario.rol.in_([Rol.supervisor_prestador, Rol.admin_prestador])))).scalars())
            if not destinos:
                continue
            f = bi_service.Filtro(hoy, hoy, prestador_id=p.id)
            actor = _actor_sistema(prestador_id=p.id)
            registro, _ = await reportes_service.generar(db, actor, tipo="jornada", formato=FormatoReporte.pdf, filtro=f)
            await notificaciones_service.notificar(
                db, "reporte.cierre_jornada", destinos, {"fecha": str(hoy), "reporte_id": str(registro.id)},
                asunto=f"Cierre de jornada · {hoy:%d/%m/%Y}", cuerpo="Adjuntamos el cierre de jornada del día.",
                url="/bi", prestador_id=p.id, canales=["email", "app"],
                adjuntos=[{"nombre": f"cierre-jornada-{hoy}.pdf", "clave": registro.archivo_key, "mime": "application/pdf"}])
            resumen["enviados"] += 1
        await db.commit()
    return resumen


@celery_app.task(name="acma.consolidar_penalizaciones")
def consolidar_penalizaciones() -> dict:
    import asyncio

    return asyncio.run(consolidar_periodo_async())


@celery_app.task(name="acma.enviar_reportes_programados")
def enviar_reportes_programados() -> dict:
    import asyncio

    return asyncio.run(enviar_reportes_async())


@celery_app.task(name="acma.reporte_cierre_jornada")
def reporte_cierre_jornada() -> dict:
    import asyncio

    return asyncio.run(cierre_jornada_async())
