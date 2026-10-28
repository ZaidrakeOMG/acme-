"""SLA prometido del folio (§6.10.1): se llena al autorizar con `contrato_sla` del contrato vigente del equipo
(por nivel de severidad); el tiempo real y las pausas los calcula P10."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.base import EstadoRegistro
from models.catalogos import CoberturaContrato, Equipo, NivelSeveridadCatalogo
from models.contratos import Contrato, ContratoSLA
from models.folios import EstadoFolio, Folio, FolioSLA
from services import folio_estados


async def contrato_vigente(db: AsyncSession, equipo: Equipo, hoy: date | None = None) -> Contrato | None:
    """Mismo criterio que acma_equipo_con_contrato_activo(): el contrato del equipo o el de cobertura total del tenant."""
    hoy = hoy or date.today()
    consulta = select(Contrato).where(Contrato.tenant_id == equipo.tenant_id, Contrato.estado == EstadoRegistro.activo,
                                      Contrato.fecha_inicio <= hoy, Contrato.fecha_fin >= hoy)
    if equipo.contrato_id:
        consulta = consulta.where(Contrato.id == equipo.contrato_id)
    else:
        consulta = consulta.where(Contrato.cobertura == CoberturaContrato.todas_las_un)
    return (await db.execute(consulta.order_by(Contrato.fecha_fin.desc()))).scalars().first()


async def registrar_prometido(db: AsyncSession, folio: Folio) -> FolioSLA | None:
    if (await db.execute(select(FolioSLA.id).where(FolioSLA.folio_id == folio.id))).first():
        return None
    if folio.severidad_id is None:
        return None
    equipo = await db.get(Equipo, folio.equipo_id)
    contrato = await contrato_vigente(db, equipo) if equipo else None
    resp = resol = None
    if contrato:
        sla = (await db.execute(select(ContratoSLA).where(
            ContratoSLA.contrato_id == contrato.id, ContratoSLA.nivel_severidad_id == folio.severidad_id))).scalars().first()
        if sla:
            resp, resol = sla.tiempo_respuesta_horas, sla.tiempo_resolucion_horas
    if resp is None:
        nivel = await db.get(NivelSeveridadCatalogo, folio.severidad_id)
        if nivel is None:
            return None
        resp, resol = nivel.tiempo_respuesta_horas, nivel.tiempo_resolucion_horas
    fila = FolioSLA(folio_id=folio.id, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, nivel_severidad_id=folio.severidad_id,
                    tiempo_respuesta_prometido_horas=resp, tiempo_resolucion_prometido_horas=resol)
    db.add(fila)
    await db.flush()
    return fila


@folio_estados.suscribir
async def _al_autorizar(db: AsyncSession, folio: Folio, _anterior, nuevo: EstadoFolio, _actor, _contexto) -> None:
    if nuevo == EstadoFolio.autorizado:
        fila = await registrar_prometido(db, folio)
        if fila is None:
            fila = (await db.execute(select(FolioSLA).where(FolioSLA.folio_id == folio.id))).scalar_one_or_none()
        if fila is not None and fila.autorizado_en is None:
            from datetime import UTC, datetime

            fila.autorizado_en = datetime.now(UTC)  # P07/P10: el SLA corre desde la autorización
