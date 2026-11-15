"""Configuración central de alertas (§6.9.6): umbral efectivo = personalizado del dueño o default del catálogo.

P10 agrega la fase (las alertas cuya fuente llega en Fase 2 se ven etiquetadas e inactivas), las escalaciones
(`escalacion_de`: el umbral se mide desde el disparo de la alerta origen, no desde el hecho original), la resolución de
destinatarios por rol y el panel de alertas de cada usuario (vista, atendida y supresión temporal).
"""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, prohibido
from models.alertas import AlertaCatalogo, AlertaConfiguracion, AlertaHistorial, AlertaSupresion
from models.base import Dominio, EstadoAlerta, Rol

# Claves que P01-P09 crearon con otro nombre y que §6.9.6 nombra de otra forma: la del documento es la canónica y la
# anterior queda como alias para que el código viejo (y los evaluadores) sigan funcionando. P10.
ALIAS = {
    "PRESUPUESTO_UMBRAL_ALCANZADO": "PRESUPUESTO_ALERTA_1",
    "PRESUPUESTO_EXCEDIDO": "PRESUPUESTO_ALERTA_3",
    "SEGUIMIENTO_INTERNO_SIN_ACTUALIZAR": "SEGUIMIENTO_SIN_UPDATE",
    "TECNICO_SIN_SEÑAL": "TECNICO_SIN_SENAL",
}
# Roles que pueden suprimir temporalmente una alerta (§6.9.6: «solo roles administradores»).
SUPRIMEN = {Rol.superadmin, Rol.admin_empresa, Rol.admin_prestador}


def canonica(clave: str) -> str:
    return ALIAS.get(clave, clave)


def _filtro_duenio(modelo, tenant_id: UUID | None, prestador_id: UUID | None):
    if tenant_id is not None:
        return (modelo.tenant_id == tenant_id, modelo.prestador_id.is_(None))
    return (modelo.prestador_id == prestador_id, modelo.tenant_id.is_(None))


def efectiva(cat: AlertaCatalogo, conf: AlertaConfiguracion | None) -> dict:
    parametros = {**cat.parametros_default, **(conf.parametros if conf else {})}
    return {
        "clave": cat.clave, "descripcion": cat.descripcion, "tipo_umbral": cat.tipo_umbral,
        "umbral_min": cat.umbral_min, "umbral_max": cat.umbral_max, "umbral_default": cat.umbral_default,
        "umbral_valor": conf.umbral_valor if conf else cat.umbral_default,
        "parametros": parametros,
        "canales": conf.canales_json if conf else cat.canales_default,
        "destinatarios_roles": (conf.destinatarios_roles_json if conf and conf.destinatarios_roles_json
                                else cat.destinatarios_default),
        "activa": conf.activa if conf else cat.activa_por_defecto,
        "personalizada": conf is not None,
        "prompt_origen": cat.prompt_origen, "modulo_origen": cat.modulo_origen,
        "fase": cat.fase,
        # La cadena de escalación: la del dueño si la configuró, la del catálogo si no (§6.9.6).
        "escalacion_de": parametros.get("escalacion_de", cat.escalacion_de),
    }


async def listar_efectivas(db: AsyncSession, tenant_id: UUID | None, prestador_id: UUID | None) -> list[dict]:
    catalogo = (await db.execute(select(AlertaCatalogo).order_by(AlertaCatalogo.clave))).scalars().all()
    confs = {c.clave_alerta: c for c in (await db.execute(
        select(AlertaConfiguracion).where(*_filtro_duenio(AlertaConfiguracion, tenant_id, prestador_id)))).scalars()}
    return [efectiva(cat, confs.get(cat.clave)) for cat in catalogo]


async def obtener_catalogo(db: AsyncSession, clave: str) -> AlertaCatalogo:
    clave = canonica(clave)
    cat = (await db.execute(select(AlertaCatalogo).where(AlertaCatalogo.clave == clave))).scalar_one_or_none()
    if cat is None:
        raise ErrorAPI(404, "NO_ENCONTRADO", f"Alerta {clave} no existe en el catálogo")
    return cat


def validar_fase(cat: AlertaCatalogo, *, activa: bool) -> None:
    """Una alerta cuya fuente de datos todavía no existe se puede dejar preparada, pero no activar.

    Desde F2-06 el catálogo no tiene ninguna de Fase 2 (el desvío de ruta era la última), pero el candado se queda
    para la siguiente que se registre sin fuente: activarla por error sería prometer un aviso que nunca llega.
    """
    if cat.fase == 2 and activa:
        raise ErrorAPI(422, "ALERTA_FASE_2", f"{cat.clave} depende de datos que llegan en Fase 2 y no puede activarse",
                       [{"campo": "activa", "fase": 2}])


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
    clave = canonica(clave)
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


# ------------------------------------------------------------------- P10
async def configuracion(db: AsyncSession, clave: str, *, tenant_id: UUID | None, prestador_id: UUID | None) -> AlertaConfiguracion | None:
    return (await db.execute(select(AlertaConfiguracion).where(
        AlertaConfiguracion.clave_alerta == canonica(clave),
        *_filtro_duenio(AlertaConfiguracion, tenant_id, prestador_id)))).scalar_one_or_none()


async def umbral(db: AsyncSession, clave: str, *, tenant_id: UUID | None = None, prestador_id: UUID | None = None) -> Decimal:
    """Umbral efectivo: el del dueño si lo configuró, el default del catálogo si no (§6.9.6)."""
    cat = await obtener_catalogo(db, clave)
    conf = await configuracion(db, clave, tenant_id=tenant_id, prestador_id=prestador_id)
    return Decimal(efectiva(cat, conf)["umbral_valor"])


async def destinatarios(db: AsyncSession, clave: str, *, tenant_id: UUID | None, prestador_id: UUID | None,
                        un_id: UUID | None = None) -> list[UUID]:
    """Usuarios de los roles destinatarios efectivos de la alerta, en el tenant y en el prestador del evento."""
    from services import notificaciones_service

    cat = await obtener_catalogo(db, clave)
    conf = await configuracion(db, clave, tenant_id=tenant_id, prestador_id=prestador_id)
    roles = [r for r in efectiva(cat, conf)["destinatarios_roles"] if r in {x.value for x in Rol}]
    ids: list[UUID] = []
    for duenio in ({"tenant_id": tenant_id, "un_id": un_id} if tenant_id else {}, {"prestador_id": prestador_id} if prestador_id else {}):
        if duenio:
            ids += await notificaciones_service.destinatarios_por_rol(db, roles, **duenio)
    return list(dict.fromkeys(ids))


def _visible_para(actor: Actor):
    """Cada usuario ve las alertas de su dominio; el superadmin, todas."""
    if actor.rol == Rol.superadmin:
        return AlertaHistorial.id.is_not(None)
    if actor.dominio == Dominio.tenant:
        return AlertaHistorial.tenant_id == actor.tenant_id
    return AlertaHistorial.prestador_id == actor.prestador_id


async def panel(db: AsyncSession, actor: Actor, *, clave: str | None = None, pendientes: bool = True,
                limite: int = 100) -> list[AlertaHistorial]:
    """Feed de alertas del usuario: las de su dominio cuyos roles destinatarios lo incluyen."""
    consulta = select(AlertaHistorial).where(_visible_para(actor))
    if clave:
        consulta = consulta.where(AlertaHistorial.clave_alerta == canonica(clave))
    if pendientes:
        consulta = consulta.where(AlertaHistorial.atendida_at.is_(None))
    filas = list((await db.execute(consulta.order_by(AlertaHistorial.timestamp_disparo.desc()).limit(limite))).scalars())
    if actor.rol == Rol.superadmin:
        return filas
    claves = {f.clave_alerta for f in filas}
    mios = set()
    for c in claves:
        cat = (await db.execute(select(AlertaCatalogo).where(AlertaCatalogo.clave == c))).scalar_one_or_none()
        if cat is None:
            continue
        conf = await configuracion(db, c, tenant_id=actor.tenant_id, prestador_id=actor.prestador_id)
        if actor.rol.value in efectiva(cat, conf)["destinatarios_roles"]:
            mios.add(c)
    return [f for f in filas if f.clave_alerta in mios]


async def marcar_vista(db: AsyncSession, actor: Actor, alerta: AlertaHistorial) -> AlertaHistorial:
    if alerta.timestamp_vista is None:
        alerta.timestamp_vista, alerta.vista_por = datetime.now(UTC), actor.id
        if alerta.estado == EstadoAlerta.disparada:
            alerta.estado = EstadoAlerta.vista
        await db.flush()
    return alerta


async def atender(db: AsyncSession, actor: Actor, alerta: AlertaHistorial, nota: str = "") -> AlertaHistorial:
    if alerta.atendida_at is not None:
        raise ErrorAPI(409, "ALERTA_YA_ATENDIDA", "La alerta ya fue atendida")
    alerta.atendida_at, alerta.atendida_por = datetime.now(UTC), actor.id
    alerta.nota_atencion = nota.strip()
    alerta.estado = EstadoAlerta.resuelta
    if alerta.timestamp_vista is None:
        alerta.timestamp_vista, alerta.vista_por = alerta.atendida_at, actor.id
    await db.flush()
    return alerta


async def suprimir(db: AsyncSession, actor: Actor, clave: str, *, razon: str, hasta: datetime,
                   entidad_id: UUID | None = None) -> AlertaSupresion:
    if actor.rol not in SUPRIMEN:
        raise prohibido("Solo los roles administradores suprimen alertas temporalmente (§6.9.6)")
    if len(razon.strip()) < 3:
        raise ErrorAPI(422, "RAZON_REQUERIDA", "Escribe la razón de la supresión")
    ahora = datetime.now(UTC)
    if hasta <= ahora:
        raise ErrorAPI(422, "FECHA_INVALIDA", "La supresión debe terminar en el futuro")
    await obtener_catalogo(db, clave)
    s = AlertaSupresion(clave_alerta=canonica(clave), tenant_id=actor.tenant_id, prestador_id=actor.prestador_id,
                        entidad_id=entidad_id, suprimida_por=actor.id, razon=razon.strip(), desde=ahora, hasta=hasta)
    db.add(s)
    await db.flush()
    return s


async def escalaciones(db: AsyncSession, *, tenant_id: UUID | None = None,
                       prestador_id: UUID | None = None) -> list[dict]:
    """Alertas que escalan desde otra, ya resueltas para el dueño (§6.9.6: el umbral corre desde el disparo del origen)."""
    efectivas = await listar_efectivas(db, tenant_id, prestador_id)
    return [e for e in efectivas if e["escalacion_de"]]


async def configurar_escalacion(db: AsyncSession, actor: Actor, clave: str, origen: str | None) -> dict:
    """El Superadmin cambia la cadena del catálogo; el Admin prestador la ajusta solo para su prestador (§6.9.6).

    Guardarla en `alertas_configuracion.parametros` mantiene el catálogo como propiedad de la plataforma (y la RLS lo
    impone: el prestador no escribe `alertas_catalogo`).
    """
    if actor.rol not in {Rol.superadmin, Rol.admin_prestador}:
        raise prohibido("Solo el Superadmin y el Admin prestador configuran escalaciones")
    cat = await obtener_catalogo(db, clave)
    if origen is not None:
        await obtener_catalogo(db, origen)
        if canonica(origen) == cat.clave:
            raise ErrorAPI(422, "ESCALACION_CIRCULAR", "Una alerta no puede escalar de sí misma")
    if actor.rol == Rol.superadmin:
        cat.escalacion_de = canonica(origen) if origen else None
        await db.flush()
        return efectiva(cat, None)
    conf = await configuracion(db, clave, tenant_id=None, prestador_id=actor.prestador_id)
    if conf is None:
        conf = AlertaConfiguracion(clave_alerta=cat.clave, prestador_id=actor.prestador_id,
                                   umbral_valor=cat.umbral_default, canales_json=list(cat.canales_default),
                                   destinatarios_roles_json=list(cat.destinatarios_default),
                                   activa=cat.activa_por_defecto)
        db.add(conf)
    conf.parametros = {**(conf.parametros or {}), "escalacion_de": canonica(origen) if origen else None}
    await db.flush()
    return efectiva(cat, conf)


async def cadena_de(db: AsyncSession, clave: str, *, tenant_id: UUID | None = None,
                    prestador_id: UUID | None = None) -> str | None:
    cat = await obtener_catalogo(db, clave)
    conf = await configuracion(db, clave, tenant_id=tenant_id, prestador_id=prestador_id)
    return efectiva(cat, conf)["escalacion_de"]


async def por_escalar(db: AsyncSession, clave: str) -> list[AlertaHistorial]:
    """Disparos de la alerta origen que ya pasaron el umbral de la escalación y siguen sin atenderse.

    El umbral y la cadena se resuelven por dueño: un prestador puede encadenar una alerta que otro no.
    """
    cat = await obtener_catalogo(db, clave)
    origenes_posibles = {cat.escalacion_de} if cat.escalacion_de else set()
    for conf in (await db.execute(select(AlertaConfiguracion).where(AlertaConfiguracion.clave_alerta == cat.clave))).scalars():
        propio = (conf.parametros or {}).get("escalacion_de")
        if propio:
            origenes_posibles.add(propio)
    if not origenes_posibles:
        return []
    ahora = datetime.now(UTC)
    origenes = list((await db.execute(select(AlertaHistorial).where(
        AlertaHistorial.clave_alerta.in_(origenes_posibles), AlertaHistorial.atendida_at.is_(None),
        AlertaHistorial.escalada.is_(False)))).scalars())
    pendientes = []
    for o in origenes:
        cadena = await cadena_de(db, cat.clave, tenant_id=o.tenant_id, prestador_id=o.prestador_id)
        if cadena != o.clave_alerta:
            continue
        dias = int(await umbral(db, cat.clave, tenant_id=o.tenant_id, prestador_id=o.prestador_id))
        if o.timestamp_disparo + timedelta(days=dias) <= ahora:
            pendientes.append(o)
    return pendientes
