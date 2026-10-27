"""Contratos tenant–prestador y SLAs por severidad (§6.10.1). Solo estructura; el contador de SLA llega en P10."""
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from core.dependencias import DB, Actor, requiere_rol
from core.errors import ErrorAPI, no_encontrado
from models.base import EstadoRegistro, Rol
from models.contratos import Contrato, ContratoSLA
from models.organizaciones import TenantPrestador
from schemas.comun import RESPUESTAS_ERROR
from schemas.organizaciones import ContratoCambios, ContratoEntrada, ContratoSalida, SLAEntrada, SLASalida
from services import auditoria

router = APIRouter(prefix="/api/contratos", tags=["Contratos"], responses=RESPUESTAS_ERROR)

ADMIN = requiere_rol(Rol.superadmin, Rol.admin_prestador)
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
                         "El tenant debe estar vinculado al prestador.")
async def crear(datos: ContratoEntrada, request: Request, db: DB, actor: Actor = Depends(ADMIN)):
    prestador_id = datos.prestador_id if actor.es_superadmin else actor.prestador_id
    if prestador_id is None:
        raise ErrorAPI(422, "PRESTADOR_REQUERIDO", "Indica prestador_id")
    vinculo = (await db.execute(select(TenantPrestador.id).where(
        TenantPrestador.tenant_id == datos.tenant_id, TenantPrestador.prestador_id == prestador_id,
        TenantPrestador.estado == EstadoRegistro.activo))).first()
    if vinculo is None:
        raise ErrorAPI(422, "TENANT_NO_VINCULADO", "El tenant no está vinculado a este prestador")
    c = Contrato(prestador_id=prestador_id, **datos.model_dump(exclude={"slas", "prestador_id"}))
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
