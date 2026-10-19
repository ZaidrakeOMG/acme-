"""Configuración central de alertas (§6.9.6): umbral efectivo = personalizado del dueño o default del catálogo."""
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ErrorAPI
from models.alertas import AlertaCatalogo, AlertaConfiguracion, AlertaHistorial, AlertaSupresion


def _filtro_duenio(modelo, tenant_id: UUID | None, prestador_id: UUID | None):
    if tenant_id is not None:
        return (modelo.tenant_id == tenant_id, modelo.prestador_id.is_(None))
    return (modelo.prestador_id == prestador_id, modelo.tenant_id.is_(None))


def efectiva(cat: AlertaCatalogo, conf: AlertaConfiguracion | None) -> dict:
    return {
        "clave": cat.clave, "descripcion": cat.descripcion, "tipo_umbral": cat.tipo_umbral,
        "umbral_min": cat.umbral_min, "umbral_max": cat.umbral_max, "umbral_default": cat.umbral_default,
        "umbral_valor": conf.umbral_valor if conf else cat.umbral_default,
        "parametros": {**cat.parametros_default, **(conf.parametros if conf else {})},
        "canales": conf.canales_json if conf else cat.canales_default,
        "destinatarios_roles": (conf.destinatarios_roles_json if conf and conf.destinatarios_roles_json
                                else cat.destinatarios_default),
        "activa": conf.activa if conf else cat.activa_por_defecto,
        "personalizada": conf is not None,
        "prompt_origen": cat.prompt_origen, "modulo_origen": cat.modulo_origen,
    }


async def listar_efectivas(db: AsyncSession, tenant_id: UUID | None, prestador_id: UUID | None) -> list[dict]:
    catalogo = (await db.execute(select(AlertaCatalogo).order_by(AlertaCatalogo.clave))).scalars().all()
    confs = {c.clave_alerta: c for c in (await db.execute(
        select(AlertaConfiguracion).where(*_filtro_duenio(AlertaConfiguracion, tenant_id, prestador_id)))).scalars()}
    return [efectiva(cat, confs.get(cat.clave)) for cat in catalogo]


async def obtener_catalogo(db: AsyncSession, clave: str) -> AlertaCatalogo:
    cat = (await db.execute(select(AlertaCatalogo).where(AlertaCatalogo.clave == clave))).scalar_one_or_none()
    if cat is None:
        raise ErrorAPI(404, "NO_ENCONTRADO", f"Alerta {clave} no existe en el catálogo")
    return cat


async def configurar(db: AsyncSession, clave: str, tenant_id: UUID | None, prestador_id: UUID | None, *,
                     umbral_valor: Decimal, parametros: dict, canales: list[str], destinatarios_roles: list[str],
                     activa: bool) -> tuple[dict | None, dict]:
    cat = await obtener_catalogo(db, clave)
    if not (cat.umbral_min <= umbral_valor <= cat.umbral_max):
        raise ErrorAPI(422, "UMBRAL_FUERA_DE_RANGO",
                       f"El umbral de {clave} debe estar entre {cat.umbral_min} y {cat.umbral_max}",
                       [{"campo": "umbral_valor", "minimo": str(cat.umbral_min), "maximo": str(cat.umbral_max)}])
    conf = (await db.execute(select(AlertaConfiguracion).where(
        AlertaConfiguracion.clave_alerta == clave, *_filtro_duenio(AlertaConfiguracion, tenant_id, prestador_id)))).scalar_one_or_none()
    antes = efectiva(cat, conf) if conf else None
    if conf is None:
        conf = AlertaConfiguracion(clave_alerta=clave, tenant_id=tenant_id, prestador_id=prestador_id, umbral_valor=umbral_valor)
        db.add(conf)
    conf.umbral_valor = umbral_valor
    conf.parametros = parametros
    conf.canales_json = list(canales)
    conf.destinatarios_roles_json = list(destinatarios_roles)
    conf.activa = activa
    await db.flush()
    return antes, efectiva(cat, conf)


async def restablecer(db: AsyncSession, clave: str, tenant_id: UUID | None, prestador_id: UUID | None) -> dict:
    cat = await obtener_catalogo(db, clave)
    conf = (await db.execute(select(AlertaConfiguracion).where(
        AlertaConfiguracion.clave_alerta == clave, *_filtro_duenio(AlertaConfiguracion, tenant_id, prestador_id)))).scalar_one_or_none()
    if conf is not None:
        await db.delete(conf)
        await db.flush()
    return efectiva(cat, None)


async def suprimida(db: AsyncSession, clave: str, tenant_id: UUID | None, prestador_id: UUID | None,
                    entidad_id: UUID | None = None) -> bool:
    ahora = datetime.now(UTC)
    filas = (await db.execute(select(AlertaSupresion).where(
        AlertaSupresion.clave_alerta == clave, AlertaSupresion.activa.is_(True),
        AlertaSupresion.desde <= ahora, AlertaSupresion.hasta > ahora,
        *_filtro_duenio(AlertaSupresion, tenant_id, prestador_id)))).scalars().all()
    return any(s.entidad_id is None or s.entidad_id == entidad_id for s in filas)


async def disparar(db: AsyncSession, clave: str, *, tenant_id: UUID | None, prestador_id: UUID | None,
                   entidad_tipo: str | None = None, entidad_id: UUID | None = None, datos: dict | None = None) -> AlertaHistorial | None:
    """Registra una alerta en el historial salvo que esté inactiva o suprimida. Lo usarán los módulos P02–P10."""
    cat = await obtener_catalogo(db, clave)
    conf = (await db.execute(select(AlertaConfiguracion).where(
        AlertaConfiguracion.clave_alerta == clave, *_filtro_duenio(AlertaConfiguracion, tenant_id, prestador_id)))).scalar_one_or_none()
    ef = efectiva(cat, conf)
    if not ef["activa"] or await suprimida(db, clave, tenant_id, prestador_id, entidad_id):
        return None
    h = AlertaHistorial(clave_alerta=clave, tenant_id=tenant_id, prestador_id=prestador_id, entidad_tipo=entidad_tipo,
                        entidad_id=entidad_id, umbral_en_momento=ef["umbral_valor"], datos_contexto_json=datos or {})
    db.add(h)
    await db.flush()
    return h
