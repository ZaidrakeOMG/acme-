"""Medidores de activos, lecturas y llaves de API para recibir lecturas (§6.9.2). F2-04."""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request

from core.dependencias import DB, ActorActual, usuario_actual
from core.errors import no_encontrado
from core.rls import ContextoRLS, fijar_contexto
from models.base import Rol
from models.medidores import EstadoLecturaMedidor, MedidorLectura, MetodoActualizacionMedidor
from schemas.comun import RESPUESTAS_ERROR, Mensaje
from schemas.medidores import (
    CambioEntrada, CambioSalida, EstimacionEntrada, EstimacionSalida, LecturaEntrada, LecturaResultado, LecturaSalida,
    LlaveCreada, LlaveEntrada, LlaveSalida, LoteEntrada, LoteSalida, MedidorCambios, MedidorEntrada, MedidorSalida,
    PendienteRevision, ResumenMedidor, RevisionEntrada, TipoMedidorCambios, TipoMedidorEntrada, TipoMedidorSalida,
)
from services import auditoria, medidores_service as svc

router = APIRouter(prefix="/api/medidores", tags=["Medidores de activos"], responses=RESPUESTAS_ERROR)


# ------------------------------------------------------------------ catálogo de tipos
@router.get("/tipos", response_model=list[TipoMedidorSalida], summary="Catálogo de tipos de medidor",
            description="El global (sin dueño) lo ve cualquiera con contexto; además, los del prestador o del cliente. "
                        "Los seis tipos de §6.9.2 vienen sembrados: horas, ciclos, distancia, energía, unidades y personalizado.")
async def listar_tipos(db: DB, actor: ActorActual, solo_activos: bool = False, q: str | None = Query(default=None, max_length=100)):
    return await svc.listar_tipos(db, actor, solo_activos=solo_activos, q=q)


@router.post("/tipos", response_model=TipoMedidorSalida, status_code=201, summary="Crear tipo de medidor")
async def crear_tipo(datos: TipoMedidorEntrada, request: Request, db: DB, actor: ActorActual):
    tipo = await svc.crear_tipo(db, actor, datos.model_dump(by_alias=True), request)
    await db.commit()
    await db.refresh(tipo)
    return tipo


@router.put("/tipos/{tipo_id}", response_model=TipoMedidorSalida, summary="Editar tipo de medidor")
async def editar_tipo(tipo_id: UUID, datos: TipoMedidorCambios, request: Request, db: DB, actor: ActorActual):
    tipo = await svc.editar_tipo(db, actor, tipo_id, datos.model_dump(exclude_unset=True), request)
    await db.commit()
    await db.refresh(tipo)
    return tipo


# ------------------------------------------------------------------ app del operador
@router.get("/operador/equipos", summary="Equipos con medidor que lee el operador",
            description="Pantalla «Registrar lectura» de la app de campo: los equipos de la UN del operador que "
                        "tienen un medidor con método `operador`, con su valor actual y si el tipo pide foto del "
                        "marcador. Funciona sin señal: la app la cachea y encola la lectura (§6.2).")
async def equipos_del_operador(db: DB, actor: ActorActual, un_id: UUID | None = None):
    return await svc.equipos_para_operador(db, actor, un_id)


# ------------------------------------------------------------------ medidores del equipo
@router.get("/equipos/{equipo_id}", response_model=list[ResumenMedidor], summary="Medidores de un equipo",
            description="Valor actual, acumulado (corregido por reinicios), último PM, estimación y el próximo "
                        "mantenimiento por uso con su fecha estimada.")
async def medidores_del_equipo(equipo_id: UUID, db: DB, actor: ActorActual):
    equipo = await svc.equipo_visible(db, actor, equipo_id)
    return await svc.resumen_de_equipo(db, actor, equipo)


@router.post("/equipos/{equipo_id}", response_model=MedidorSalida, status_code=201, summary="Dar de alta un medidor")
async def alta_medidor(equipo_id: UUID, datos: MedidorEntrada, request: Request, db: DB, actor: ActorActual):
    equipo = await svc.equipo_visible(db, actor, equipo_id)
    m = await svc.alta_medidor(db, actor, equipo, datos.model_dump(), request)
    await db.commit()
    await db.refresh(m)
    return m


@router.put("/{medidor_id}", response_model=MedidorSalida, summary="Editar la configuración de un medidor",
            description="El valor no se edita: se mueve con lecturas y con reinicios o reemplazos registrados.")
async def editar_medidor(medidor_id: UUID, datos: MedidorCambios, request: Request, db: DB, actor: ActorActual):
    m = await svc.medidor_visible(db, actor, medidor_id)
    m = await svc.editar_medidor(db, actor, m, datos.model_dump(exclude_unset=True), request)
    await db.commit()
    await db.refresh(m)
    return m


@router.get("/{medidor_id}/cambios", response_model=list[CambioSalida], summary="Reinicios y reemplazos del medidor")
async def cambios(medidor_id: UUID, db: DB, actor: ActorActual):
    await svc.medidor_visible(db, actor, medidor_id)
    return await svc.cambios_de(db, medidor_id)


@router.post("/{medidor_id}/cambios", response_model=CambioSalida, status_code=201,
             summary="Registrar un reinicio del marcador o un reemplazo de medidor",
             description="Lo andado hasta ahora queda guardado, así que el acumulado no retrocede. El reemplazo "
                         "además es un evento que puede disparar planes (`cambio_medidor`).")
async def registrar_cambio(medidor_id: UUID, datos: CambioEntrada, request: Request, db: DB, actor: ActorActual):
    m = await svc.medidor_visible(db, actor, medidor_id)
    cambio = await svc.registrar_cambio(db, actor, m, tipo=datos.tipo, valor_nuevo=datos.valor_nuevo,
                                        motivo=datos.motivo, numero_serie_nuevo=datos.numero_serie_nuevo, request=request)
    await db.commit()
    await db.refresh(cambio)
    return cambio


@router.put("/{medidor_id}/estimacion", response_model=EstimacionSalida, summary="Configurar la lectura estimada",
            description="`incremento_por_dia` por día de operación y `horario_operacion_json` con los días (y las "
                        "horas, informativas). La tarea diaria escribe una lectura `estimado`; una lectura real "
                        "posterior la corrige y recalcula el incremento real promedio.")
async def estimacion(medidor_id: UUID, datos: EstimacionEntrada, request: Request, db: DB, actor: ActorActual):
    m = await svc.medidor_visible(db, actor, medidor_id)
    est = await svc.configurar_estimacion(db, actor, m, datos.model_dump(exclude_unset=True), request)
    await db.commit()
    await db.refresh(est)
    return est


# ------------------------------------------------------------------ lecturas
@router.get("/lecturas", response_model=list[LecturaSalida], summary="Lecturas con filtros")
async def lecturas(db: DB, actor: ActorActual, equipo_id: UUID | None = None, equipo_medidor_id: UUID | None = None,
                   estado: EstadoLecturaMedidor | None = None, desde: date | None = None, hasta: date | None = None,
                   limite: int = Query(default=200, ge=1, le=1000)):
    return await svc.listar_lecturas(db, actor, equipo_id=equipo_id, equipo_medidor_id=equipo_medidor_id,
                                     estado=estado, desde=desde, hasta=hasta, limite=limite)


@router.get("/lecturas/por-revisar", response_model=list[PendienteRevision],
            summary="Bandeja de lecturas por revisar",
            description="Lecturas anómalas (retroceso o salto) esperando que el Despachador o el Admin prestador "
                        "las apruebe o las rechace. Mientras no se resuelvan no disparan planes.")
async def por_revisar(db: DB, actor: ActorActual):
    return await svc.pendientes_revision(db, actor)


@router.post("/lecturas", response_model=LecturaResultado, status_code=201, summary="Registrar una lectura",
             description="El técnico, el operador o el despachador. Si la lectura retrocede o salta más de lo "
                         "esperado queda `en_revision` y dispara `MEDIDOR_LECTURA_ANOMALA`; si es válida, mueve el "
                         "medidor y evalúa los planes por uso de inmediato.")
async def registrar_lectura(datos: LecturaEntrada, request: Request, db: DB, actor: ActorActual):
    m = await svc.medidor_visible(db, actor, datos.equipo_medidor_id)
    svc._exigir(actor, svc.REGISTRAN_LECTURA, "registra lecturas de medidor")
    resultado = await svc.registrar_lectura(
        db, actor, m, valor=datos.valor, metodo=datos.metodo or m.metodo_actualizacion,
        timestamp_dispositivo=datos.timestamp_dispositivo, folio_id=datos.folio_id,
        evidencia_id=datos.evidencia_id, request=request)
    await db.commit()
    return {"lectura": resultado["lectura"], "duplicada": resultado["duplicada"], "anomalia": resultado["anomalia"],
            "folios_generados": resultado["generados"]}


@router.post("/lecturas/{lectura_id}/revision", response_model=LecturaResultado,
             summary="Aprobar o rechazar una lectura anómala",
             description="Aprobarla la aplica (recalculando el acumulado con el estado actual del medidor, por si "
                         "entre tanto se registró el reinicio) y puede generar el folio preventivo. Rechazarla "
                         "exige razón.")
async def revisar(lectura_id: UUID, datos: RevisionEntrada, request: Request, db: DB, actor: ActorActual):
    lectura = await db.get(MedidorLectura, lectura_id)
    if lectura is None:
        raise no_encontrado("Lectura")
    await svc.equipo_visible(db, actor, lectura.equipo_id)
    resultado = await svc.revisar_lectura(db, actor, lectura, datos.aprobar, datos.razon, request)
    await db.commit()
    return {"lectura": resultado["lectura"], "duplicada": False, "anomalia": resultado["lectura"].motivo,
            "folios_generados": resultado["generados"]}


# ------------------------------------------------------------------ lote: importación y sistema del cliente
async def _actor_o_llave(request: Request, db: DB, x_acma_llave: str | None = Header(default=None, alias="X-ACMA-Llave")):
    """Autenticación doble de `/lecturas/lote`: sesión normal, o llave de API del cliente.

    Con llave, la sesión queda en el contexto del **cliente** (nunca de plataforma), así que la RLS la limita a sus
    propios equipos aunque el servicio se equivoque, y el uso queda en la auditoría."""
    if x_acma_llave:
        # La llave se busca por su hash y la tabla tiene RLS forzada, así que la **búsqueda** va con contexto de
        # sistema (la petición no trae sesión de nadie). En cuanto se sabe de quién es la llave, la sesión queda en
        # el contexto de ese cliente para todo lo demás.
        from core.rls import CONTEXTO_SISTEMA

        await fijar_contexto(db, CONTEXTO_SISTEMA)
        llave = await svc.resolver_llave(db, x_acma_llave)
        await fijar_contexto(db, ContextoRLS(tenant_id=llave.tenant_id, rol=Rol.admin_empresa.value))
        return None, llave
    return await usuario_actual(request, db), None


@router.post("/lecturas/lote", response_model=LoteSalida, summary="Lecturas en lote (archivo o sistema del cliente)",
             description="Autenticación por sesión o por **llave de API del cliente** en la cabecera `X-ACMA-Llave`. "
                         "Cada fila se resuelve aparte: una mala no tira el lote. El formato está documentado en "
                         "`docs/integracion/lecturas_medidor.md`.")
async def lote(datos: LoteEntrada, request: Request, db: DB, auth=Depends(_actor_o_llave)):
    actor, llave = auth
    if llave is not None:
        tenant_id, llave_id = llave.tenant_id, llave.id
    else:
        tenant_id = datos.tenant_id if actor.es_superadmin and datos.tenant_id else actor.tenant_id
        llave_id = None
        if tenant_id is None:
            raise no_encontrado("Cliente")
        svc._exigir(actor, svc.IMPORTAN_LECTURAS, "carga lecturas en lote")
    resultado = await svc.registrar_lote(db, actor, tenant_id, [f.model_dump() for f in datos.lecturas],
                                         metodo=MetodoActualizacionMedidor.importacion, llave_api_id=llave_id,
                                         request=request)
    if llave is not None:
        await auditoria.registrar(db, "medidores.lote_por_llave", actor_rol="llave_api", tenant_id=tenant_id,
                                  recurso_tipo="llave_api_tenant", recurso_id=llave.id, request=request,
                                  despues={"prefijo": llave.prefijo, "total": resultado["total"],
                                           "aplicadas": resultado["aplicadas"], "rechazadas": resultado["rechazadas"]})
    await db.commit()
    return resultado


# ------------------------------------------------------------------ llaves de API
@router.get("/llaves", response_model=list[LlaveSalida], summary="Llaves de API del cliente",
            description="Solo el Admin empresa y el Superadmin. La llave completa no se vuelve a mostrar: de cada "
                        "una queda su prefijo, su último uso y cuántas veces se usó.")
async def llaves(db: DB, actor: ActorActual, tenant_id: UUID | None = None):
    return await svc.listar_llaves(db, actor, tenant_id)


@router.post("/llaves", response_model=LlaveCreada, status_code=201, summary="Crear una llave de API",
             description="Devuelve la llave completa **una sola vez**: ACMA solo guarda su hash. Sirve únicamente "
                         "para registrar lecturas de medidor.")
async def crear_llave(datos: LlaveEntrada, request: Request, db: DB, actor: ActorActual):
    destino = datos.tenant_id if actor.es_superadmin and datos.tenant_id else actor.tenant_id
    if destino is None:
        raise no_encontrado("Cliente")
    fila, secreto = await svc.crear_llave(db, actor, destino, datos.nombre, request)
    await db.commit()
    await db.refresh(fila)
    return {"llave": fila, "secreto": secreto}


@router.delete("/llaves/{llave_id}", response_model=Mensaje, summary="Revocar una llave de API")
async def revocar_llave(llave_id: UUID, request: Request, db: DB, actor: ActorActual):
    fila = await svc.revocar_llave(db, actor, llave_id, request)
    await db.commit()
    return {"mensaje": f"Llave {fila.prefijo}… revocada"}
