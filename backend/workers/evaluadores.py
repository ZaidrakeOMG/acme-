"""Evaluadores de alertas de los catálogos (P02). Cada módulo agrega los suyos con @registrar_evaluador."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.alertas import AlertaCatalogo, AlertaHistorial
from models.base import EstadoAlerta, EstadoRegistro
from models.organizaciones import Tenant
from services import alertas_service, catalogos_service
from workers.tareas import registrar_evaluador


@registrar_evaluador("MATRIZ_SEVERIDAD_INCOMPLETA")
async def matriz_incompleta(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """Por tenant activo: combinaciones falla × equipo en uso sin severidad. Dispara si superan el umbral (default 0)
    y no hay ya una alerta de este tipo sin atender para el tenant (la tarea corre cada 60 s)."""
    disparadas = 0
    tenants = (await db.execute(select(Tenant).where(Tenant.estado == EstadoRegistro.activo))).scalars().all()
    for tenant in tenants:
        faltantes = await catalogos_service.combinaciones_faltantes(db, tenant.id)
        if not faltantes:
            continue
        conf = await alertas_service.listar_efectivas(db, tenant.id, None)
        umbral = next(c["umbral_valor"] for c in conf if c["clave"] == alerta.clave)
        if len(faltantes) <= umbral:
            continue
        pendiente = (await db.execute(select(AlertaHistorial.id).where(
            AlertaHistorial.clave_alerta == alerta.clave, AlertaHistorial.tenant_id == tenant.id,
            AlertaHistorial.estado == EstadoAlerta.disparada))).first()
        if pendiente:
            continue
        h = await alertas_service.disparar(
            db, alerta.clave, tenant_id=tenant.id, prestador_id=None, entidad_tipo="tenant", entidad_id=tenant.id,
            datos={"faltantes": len(faltantes), "ejemplos": [f"{f} × {t}" for f, t in faltantes[:10]]},
        )
        disparadas += 1 if h else 0
    return disparadas
