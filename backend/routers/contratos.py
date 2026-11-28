"""Contratos tenant–prestador y SLAs por severidad (§6.10.1). Solo estructura; el contador de SLA llega en P10."""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from core.dependencias import DB, Actor, requiere_rol
from core.errors import ErrorAPI, no_encontrado
from models.base import EstadoRegistro, Rol
from models.contratos import Contrato, ContratoSLA
from models.organizaciones import Prestador, Tenant, TenantPrestador
from schemas.comun import RESPUESTAS_ERROR
from schemas.organizaciones import ContratoCambios, ContratoEntrada, ContratoSalida, SLAEntrada, SLASalida
from services import auditoria

router = APIRouter(prefix="/api/contratos", tags=["Contratos"], responses=RESPUESTAS_ERROR)

ADMIN = requiere_rol(Rol.superadmin)
LECTORES = requiere_rol(Rol.superadmin, Rol.admin_prestador, Rol.direccion_prestador, Rol.mesa_control, Rol.admin_empresa)


async def _salida(db, c: Contrato) -> ContratoSalida:
    slas = (await db.execute(select(ContratoSLA).where(ContratoSLA.contrato_id == c.id))).scalars().all()
    orden = ["muy_baja", "baja", "media", "alta", "critica"]
    slas = sorted(slas, key=lambda s: orden.index(s.nivel_severidad.value))
    return ContratoSalida(**{k: getattr(c, k) for k in ContratoSalida.model_fields if k != "slas"},
                          slas=[SLASalida.model_validate(s) for s in slas])


async def _obtener(db, actor: Actor, contrato_id: UUID) -> Contrato:
    c = await db.get(Contrato, contrato_id)
    if c is None:
        raise no_encontrado("Contrato")
    if actor.dominio.value == "prestador" and c.prestador_id != actor.prestador_id:
        raise no_encontrado("Contrato")
    if actor.dominio.value == "tenant" and c.tenant_id != actor.tenant_id:
        raise no_encontrado("Contrato")
    return c


async def _sin_traslape(db, tenant_id, prestador_id, inicio, fin, excluir=None) -> None:
    """§6.10.1: la relación cliente–prestador se formaliza en UN contrato. Dos contratos activos que se traslapan dejan
    indefinido qué SLA y qué horario de servicio aplican, así que se rechazan. P10."""
    consulta = select(Contrato.id, Contrato.nombre).where(
        Contrato.tenant_id == tenant_id, Contrato.prestador_id == prestador_id, Contrato.estado == EstadoRegistro.activo,
        Contrato.fecha_inicio <= fin, Contrato.fecha_fin >= inicio)
    if excluir is not None:
        consulta = consulta.where(Contrato.id != excluir)
    otro = (await db.execute(consulta)).first()
    if otro is not None:
        raise ErrorAPI(409, "CONTRATO_TRASLAPADO",
                       f"«{otro.nombre}» ya cubre ese período para este cliente; §6.10.1 pide un solo contrato por relación",
                       [{"campo": "fecha_inicio", "contrato_id": str(otro.id)}])


def _guardar_slas(db, c: Contrato, slas: list[SLAEntrada], existentes: list[ContratoSLA] | None = None) -> None:
    por_nivel = {s.nivel_severidad: s for s in (existentes or [])}
    for s in slas:
        fila = por_nivel.get(s.nivel_severidad)
        if fila is None:
            db.add(ContratoSLA(tenant_id=c.tenant_id, prestador_id=c.prestador_id, contrato_id=c.id, **s.model_dump()))
        else:
            for k, v in s.model_dump().items():
                setattr(fila, k, v)


@router.get("", response_model=list[ContratoSalida], summary="Listar contratos",
            description="El prestador ve sus contratos; admin_empresa los de su tenant.")
async def listar(db: DB, actor: Actor = Depends(LECTORES), tenant_id: UUID | None = None):
    consulta = select(Contrato).order_by(Contrato.fecha_inicio.desc())
    if actor.prestador_id:
        consulta = consulta.where(Contrato.prestador_id == actor.prestador_id)
    if actor.tenant_id:
        consulta = consulta.where(Contrato.tenant_id == actor.tenant_id)
    if tenant_id:
        consulta = consulta.where(Contrato.tenant_id == tenant_id)
    return [await _salida(db, c) for c in (await db.execute(consulta)).scalars()]


@router.post("", response_model=ContratoSalida, status_code=201, summary="Crear contrato",
             description="Requiere los 5 niveles de severidad con tiempos de respuesta y resolución entre 1 y 4,320 horas. "
                         "Superadmin puede autorizar la vinculación al guardar el contrato.")
async def crear(datos: ContratoEntrada, request: Request, db: DB, actor: Actor = Depends(ADMIN)):
    prestador_id = datos.prestador_id if actor.es_superadmin else actor.prestador_id
    if prestador_id is None:
        raise ErrorAPI(422, "PRESTADOR_REQUERIDO", "Indica prestador_id")
    # Serializa altas de contratos/vínculos de un cliente y comprueba las organizaciones.
    tenant = (await db.execute(select(Tenant).where(Tenant.id == datos.tenant_id).with_for_update())).scalar_one_or_none()
    if tenant is None:
        raise no_encontrado("Cliente")
    prestador = await db.get(Prestador, prestador_id)
    if prestador is None:
        raise no_encontrado("Prestador")
    if tenant.estado != EstadoRegistro.activo or prestador.estado != EstadoRegistro.activo:
        raise ErrorAPI(422, "ORGANIZACION_INACTIVA", "El cliente y el prestador deben estar activos")
    hoy = date.today()
    vinculos = (await db.execute(select(TenantPrestador).where(
        TenantPrestador.tenant_id == datos.tenant_id, TenantPrestador.prestador_id == prestador_id
    ).order_by(TenantPrestador.vigencia_inicio.desc()).with_for_update())).scalars().all()
    vinculo = next((v for v in vinculos if v.estado == EstadoRegistro.activo
                    and v.vigencia_inicio <= hoy and (v.vigencia_fin is None or v.vigencia_fin >= hoy)), None)
    if vinculo is None and not (actor.es_superadmin and datos.vincular_prestador):
        raise ErrorAPI(422, "TENANT_NO_VINCULADO", "El cliente no tiene un vínculo vigente con este prestador")
    await _sin_traslape(db, datos.tenant_id, prestador_id, datos.fecha_inicio, datos.fecha_fin)
    if vinculo is None:
        # Conserva las relaciones históricas. Si ya existe una fila de hoy, reutilízala.
        vinculo = next((v for v in vinculos if v.vigencia_inicio == hoy), None)
        antes = auditoria.instantanea(vinculo) if vinculo is not None else None
        if vinculo is None:
            vinculo = TenantPrestador(tenant_id=datos.tenant_id, prestador_id=prestador_id,
                                       vigencia_inicio=hoy, estado=EstadoRegistro.activo)
            db.add(vinculo)
        else:
            vinculo.estado = EstadoRegistro.activo
            vinculo.vigencia_fin = None
        await db.flush()
        await auditoria.registrar_actor(db, actor, "tenants.vinculo_prestador", request,
                                        tenant_id=datos.tenant_id, prestador_id=prestador_id,
                                        recurso_tipo="tenant_prestador", recurso_id=vinculo.id,
                                        antes=antes, despues=auditoria.instantanea(vinculo))
    # Vínculo, contrato, SLA y auditoría se confirman en la misma transacción.
    c = Contrato(prestador_id=prestador_id, **datos.model_dump(exclude={"slas", "prestador_id", "vincular_prestador"}))
    db.add(c)
    await db.flush()
    _guardar_slas(db, c, datos.slas)
    await db.flush()
    salida = await _salida(db, c)
    await auditoria.registrar_actor(db, actor, "contratos.alta", request, tenant_id=c.tenant_id, prestador_id=c.prestador_id,
                                    recurso_tipo="contrato", recurso_id=c.id, despues=salida.model_dump(mode="json"))
    await db.commit()
    return salida


@router.get("/{contrato_id}", response_model=ContratoSalida, summary="Detalle de contrato")
async def detalle(contrato_id: UUID, db: DB, actor: Actor = Depends(LECTORES)):
    return await _salida(db, await _obtener(db, actor, contrato_id))


@router.patch("/{contrato_id}", response_model=ContratoSalida, summary="Modificar contrato y SLAs",
              description="La modificación de SLAs queda en auditoría con valor anterior y nuevo (§6.9.5).")
async def modificar(contrato_id: UUID, datos: ContratoCambios, request: Request, db: DB, actor: Actor = Depends(ADMIN)):
    c = await _obtener(db, actor, contrato_id)
    antes = (await _salida(db, c)).model_dump(mode="json")
    cambios = datos.model_dump(exclude_unset=True, exclude={"slas"})
    for k, v in cambios.items():
        if v is not None or k in ("folios_correctivos_iguala", "penalizacion_tope_porcentaje", "horario_servicio_json"):
            setattr(c, k, v)
    if c.fecha_fin < c.fecha_inicio:
        raise ErrorAPI(422, "VIGENCIA_INVALIDA", "La fecha de fin debe ser posterior a la de inicio")
    if c.estado == EstadoRegistro.activo:
        await _sin_traslape(db, c.tenant_id, c.prestador_id, c.fecha_inicio, c.fecha_fin, excluir=c.id)
    if datos.slas is not None:
        existentes = (await db.execute(select(ContratoSLA).where(ContratoSLA.contrato_id == c.id))).scalars().all()
        _guardar_slas(db, c, datos.slas, list(existentes))
    await db.flush()
    await db.refresh(c)
    salida = await _salida(db, c)
    evento = "contratos.modificacion_sla" if datos.slas is not None else "contratos.modificacion"
    await auditoria.registrar_actor(db, actor, evento, request, tenant_id=c.tenant_id, prestador_id=c.prestador_id,
                                    recurso_tipo="contrato", recurso_id=c.id, antes=antes, despues=salida.model_dump(mode="json"))
    await db.commit()
    return salida
