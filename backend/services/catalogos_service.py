"""Reglas de catálogos maestros que usan P03/P04: contrato activo del equipo, resolución de severidad, matriz."""
from datetime import date
from uuid import UUID

from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.catalogos import (
    Equipo, EstadoActivo, FamiliaEquipo, NivelSeveridadCatalogo, TipoEquipo, TipoFalla, TipoFallaSeveridad,
)
from models.organizaciones import TenantPrestador
from models.base import EstadoRegistro

# §6.10.1: los 5 niveles (clave, nombre, orden, color, respuesta h, resolución h). Igual que la migración 0002.
NIVELES_DEFAULT = [
    ("muy_baja", "Muy baja", 1, "#1976D2", 72, 720),
    ("baja", "Baja", 2, "#388E3C", 24, 168),
    ("media", "Media", 3, "#FBC02D", 8, 72),
    ("alta", "Alta", 4, "#F57C00", 4, 24),
    ("critica", "Crítica", 5, "#D32F2F", 2, 8),
]


async def sembrar_niveles(db: AsyncSession, prestador_id: UUID) -> None:
    for clave, nombre, orden, color, resp, resol in NIVELES_DEFAULT:
        db.add(NivelSeveridadCatalogo(prestador_id=prestador_id, clave=clave, nombre=nombre, orden=orden, color_hex=color,
                                      tiempo_respuesta_horas=resp, tiempo_resolucion_horas=resol))
    await db.flush()


# ------------------------------------------------------- contrato activo

CON_CONTRATO = func.acma_equipo_con_contrato_activo(Equipo.id)


async def equipo_con_contrato_activo(db: AsyncSession, equipo_id: UUID) -> bool:
    """Regla de cobertura contractual (función SQL acma_equipo_con_contrato_activo). La usa P04 al capturar."""
    return bool((await db.execute(text("SELECT acma_equipo_con_contrato_activo(:e)"), {"e": equipo_id})).scalar())


def en_garantia(equipo: Equipo, hoy: date | None = None) -> bool:
    return equipo.garantia_vigente_hasta is not None and equipo.garantia_vigente_hasta >= (hoy or date.today())


# ---------------------------------------------------- prestadores del tenant

async def prestadores_del_tenant(db: AsyncSession, tenant_id: UUID) -> list[UUID]:
    hoy = date.today()
    return list((await db.execute(select(TenantPrestador.prestador_id).where(
        TenantPrestador.tenant_id == tenant_id, TenantPrestador.estado == EstadoRegistro.activo,
        TenantPrestador.vigencia_inicio <= hoy,
        (TenantPrestador.vigencia_fin.is_(None)) | (TenantPrestador.vigencia_fin >= hoy),
    ))).scalars())


# ----------------------------------------------------- matriz de severidad

def _tipos_equipo_del_tenant(tenant_id: UUID):
    return select(TipoEquipo).where(
        TipoEquipo.activa.is_(True), (TipoEquipo.tenant_id.is_(None)) | (TipoEquipo.tenant_id == tenant_id)
    )


async def tipos_equipo_en_uso(db: AsyncSession, tenant_id: UUID) -> set[UUID]:
    return set((await db.execute(select(Equipo.tipo_equipo_id).where(
        Equipo.tenant_id == tenant_id, Equipo.estado == EstadoActivo.activo).distinct())).scalars())


async def matriz(db: AsyncSession, tenant_id: UUID) -> dict:
    prestadores = await prestadores_del_tenant(db, tenant_id)
    fallas = (await db.execute(select(TipoFalla).where(
        TipoFalla.prestador_id.in_(prestadores), TipoFalla.activa.is_(True)).order_by(TipoFalla.descripcion))).scalars().all()
    tipos = (await db.execute(_tipos_equipo_del_tenant(tenant_id).order_by(TipoEquipo.nombre))).scalars().all()
    niveles = (await db.execute(select(NivelSeveridadCatalogo).where(
        NivelSeveridadCatalogo.prestador_id.in_(prestadores), NivelSeveridadCatalogo.activo.is_(True))
        .order_by(NivelSeveridadCatalogo.orden))).scalars().all()
    celdas = (await db.execute(select(TipoFallaSeveridad).where(
        TipoFallaSeveridad.tenant_id == tenant_id, TipoFallaSeveridad.activa.is_(True)))).scalars().all()
    en_uso = await tipos_equipo_en_uso(db, tenant_id)
    configuradas = {(c.tipo_falla_id, c.tipo_equipo_id) for c in celdas}
    faltantes = sum(1 for f in fallas for t in tipos
                    if t.id in en_uso and t.familia_id == f.familia_equipo_id and (f.id, t.id) not in configuradas)
    return {
        "tenant_id": tenant_id,
        "tipos_falla": [{"id": f.id, "descripcion": f.descripcion, "familia_equipo_id": f.familia_equipo_id,
                         "prestador_id": f.prestador_id} for f in fallas],
        "tipos_equipo": [{"id": t.id, "nombre": t.nombre, "familia_id": t.familia_id, "en_uso": t.id in en_uso} for t in tipos],
        "niveles": [{"id": n.id, "prestador_id": n.prestador_id, "clave": n.clave, "nombre": n.nombre, "orden": n.orden,
                     "color_hex": n.color_hex} for n in niveles],
        "celdas": [{"tipo_falla_id": c.tipo_falla_id, "tipo_equipo_id": c.tipo_equipo_id,
                    "nivel_severidad_id": c.nivel_severidad_id} for c in celdas],
        "faltantes_en_uso": faltantes,
    }


async def combinaciones_faltantes(db: AsyncSession, tenant_id: UUID) -> list[tuple[str, str]]:
    """(tipo de falla, tipo de equipo) de la misma familia, con equipos activos del tenant, sin severidad configurada."""
    prestadores = await prestadores_del_tenant(db, tenant_id)
    en_uso = await tipos_equipo_en_uso(db, tenant_id)
    if not prestadores or not en_uso:
        return []
    filas = (await db.execute(
        select(TipoFalla.descripcion, TipoEquipo.nombre)
        .join(TipoEquipo, and_(TipoEquipo.familia_id == TipoFalla.familia_equipo_id, TipoEquipo.id.in_(en_uso)))
        .outerjoin(TipoFallaSeveridad, and_(
            TipoFallaSeveridad.tenant_id == tenant_id, TipoFallaSeveridad.tipo_falla_id == TipoFalla.id,
            TipoFallaSeveridad.tipo_equipo_id == TipoEquipo.id, TipoFallaSeveridad.activa.is_(True)))
        .where(TipoFalla.prestador_id.in_(prestadores), TipoFalla.activa.is_(True), TipoFallaSeveridad.id.is_(None))
        .order_by(TipoFalla.descripcion, TipoEquipo.nombre)
    )).all()
    return [(f, t) for f, t in filas]


async def resolver_severidad(db: AsyncSession, tenant_id: UUID, tipo_falla_id: UUID, tipo_equipo_id: UUID):
    """Nivel de severidad de la matriz para la combinación, o None si no está configurada (P04 la consume)."""
    fila = (await db.execute(
        select(NivelSeveridadCatalogo, TipoFalla.requiere_revision_manual)
        .join(TipoFallaSeveridad, TipoFallaSeveridad.nivel_severidad_id == NivelSeveridadCatalogo.id)
        .join(TipoFalla, TipoFalla.id == TipoFallaSeveridad.tipo_falla_id)
        .where(TipoFallaSeveridad.tenant_id == tenant_id, TipoFallaSeveridad.tipo_falla_id == tipo_falla_id,
               TipoFallaSeveridad.tipo_equipo_id == tipo_equipo_id, TipoFallaSeveridad.activa.is_(True))
    )).first()
    return fila


async def familia_visible(db: AsyncSession, familia_id: UUID, tenant_id: UUID | None) -> FamiliaEquipo | None:
    f = await db.get(FamiliaEquipo, familia_id)
    if f is None or (f.tenant_id is not None and f.tenant_id != tenant_id):
        return None
    return f
