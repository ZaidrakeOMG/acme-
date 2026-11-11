"""Medidores de activos (§6.9.2): catálogo de tipos, medidores por equipo, lecturas con sus cuatro métodos,
validación de anomalías, reinicios y reemplazos, estimación diaria y llaves de API por cliente. F2-04.

**El acumulado es la cifra que mandan los planes por uso.** `valor_actual` es lo que dice el marcador; el acumulado
es lo que el equipo lleva de verdad:

    valor_acumulado = acumulado_offset + (valor - ciclo_inicio)

Cuando el marcador se reinicia (llega a 99,999 y vuelve a 0) o cuando se cambia el medidor físico, se registra un
`medidor_cambios` y el servicio mueve `acumulado_offset` y `ciclo_inicio`, así que el acumulado nunca retrocede y
los planes por intervalo no se vuelven locos.

**Reglas elegidas donde el diseño no las fijaba** (anotadas como decisiones pendientes en `CONTEXTO.md`):
- Lectura **menor** que la anterior o con un **salto** mayor al esperado → `en_revision`, no rechazada: puede ser un
  reinicio que nadie registró, y eso lo sabe la persona, no el servidor. Dispara `MEDIDOR_LECTURA_ANOMALA` y no
  mueve el medidor ni dispara planes hasta que el Despachador o el Admin prestador la apruebe.
- Lectura con **fecha futura** → 422: no es una duda, es un dato mal capturado (reloj del dispositivo o archivo mal
  armado); aceptarla adelantaría los mantenimientos de todo el equipo.
- Lectura **duplicada** (mismo medidor, mismo instante del dispositivo y mismo valor) → se devuelve la que ya
  existía con `duplicada: true`. Es lo que necesitan la cola sin señal y la importación para poder reintentar.
"""
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, no_encontrado, prohibido
from core.security import hash_token, nuevo_token_opaco
from models.base import Dominio, Rol
from models.catalogos import Equipo
from models.medidores import (
    PERMISO_LECTURAS, CategoriaMedidor, EquipoMedidor, EstadoLecturaMedidor, LlaveApiTenant, MedidorCambio,
    MedidorEstimacion, MedidorLectura, MetodoActualizacionMedidor, TipoCambioMedidor, TipoMedidor,
)
from models.unidades import UnidadNegocio
from services import alertas_service, auditoria

CERO = Decimal("0")
CENTAVO = Decimal("0.01")
TOLERANCIA_FUTURO_MIN = 5  # el reloj del teléfono del técnico se adelanta unos minutos; más que eso es un error

# Quién hace qué (§6.9.2 y §6.8.3).
GESTIONAN_CATALOGO = {Rol.superadmin, Rol.admin_prestador, Rol.admin_empresa, Rol.mesa_control}
GESTIONAN_MEDIDOR = {Rol.superadmin, Rol.admin_prestador, Rol.despachador, Rol.mesa_control, Rol.admin_empresa, Rol.admin_un}
REGISTRAN_LECTURA = GESTIONAN_MEDIDOR | {Rol.tecnico, Rol.operador, Rol.supervisor_operadores}
REVISAN = {Rol.superadmin, Rol.despachador, Rol.admin_prestador}
# El lote resuelve equipos por código en todo el cliente, así que lo usan los roles que ven al cliente completo; el
# operador registra las lecturas de su unidad una por una, donde su alcance sí se valida.
IMPORTAN_LECTURAS = {Rol.superadmin, Rol.admin_empresa, Rol.mesa_control, Rol.admin_prestador, Rol.despachador}
CONSULTAN = REGISTRAN_LECTURA | {Rol.supervisor_prestador, Rol.direccion_prestador}

DIAS_SEMANA = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")


# ------------------------------------------------------------------ utilidades de alcance

async def _prestadores_del_tenant(db: AsyncSession, tenant_id: UUID) -> list[UUID]:
    from services import catalogos_service

    return await catalogos_service.prestadores_del_tenant(db, tenant_id)


async def prestador_responsable(db: AsyncSession, tenant_id: UUID) -> UUID | None:
    """Las alertas de medidores van al Despachador (§6.9.6) y el panel de un usuario del prestador solo muestra las
    de **su** prestador, así que hay que ponerle dueño aunque la lectura la haya capturado el operador del cliente.
    Con varios prestadores vinculados se usa el primero: el modelo de `alertas_historial` guarda uno solo."""
    prestadores = await _prestadores_del_tenant(db, tenant_id)
    return prestadores[0] if prestadores else None


async def equipo_visible(db: AsyncSession, actor: Actor, equipo_id: UUID) -> Equipo:
    """Regla 2: el alcance se valida en el servicio además de la RLS. El operador y el Admin UN solo ven los equipos
    de sus unidades; el prestador, los de los clientes que atiende."""
    equipo = await db.get(Equipo, equipo_id)
    if equipo is None:
        raise no_encontrado("Equipo")
    if actor.es_superadmin:
        return equipo
    if actor.dominio == Dominio.tenant:
        if equipo.tenant_id != actor.tenant_id:
            raise no_encontrado("Equipo")
        from services.preventivos_service import _unidades_visibles

        unidades = await _unidades_visibles(db, actor)
        if unidades is not None and equipo.un_id not in set(unidades):
            raise no_encontrado("Equipo")
        return equipo
    if actor.prestador_id in await _prestadores_del_tenant(db, equipo.tenant_id):
        return equipo
    raise no_encontrado("Equipo")


async def medidor_visible(db: AsyncSession, actor: Actor, medidor_id: UUID) -> EquipoMedidor:
    m = await db.get(EquipoMedidor, medidor_id)
    if m is None:
        raise no_encontrado("Medidor")
    await equipo_visible(db, actor, m.equipo_id)
    return m


def _exigir(actor: Actor, roles: set[Rol], que: str) -> None:
    if not actor.es_superadmin and actor.rol not in roles:
        raise prohibido(f"Tu rol no {que}")


# ------------------------------------------------------------------ catálogo de tipos de medidor

async def listar_tipos(db: AsyncSession, actor: Actor, solo_activos: bool = False, q: str | None = None) -> list[TipoMedidor]:
    _exigir(actor, CONSULTAN, "consulta el catálogo de medidores")
    consulta = select(TipoMedidor).order_by(TipoMedidor.nombre)
    if solo_activos:
        consulta = consulta.where(TipoMedidor.activo.is_(True))
    if q:
        consulta = consulta.where(TipoMedidor.nombre.ilike(f"%{q}%"))
    # La RLS ya limita a global + propios; el servicio repite el filtro del dueño (regla 2).
    if not actor.es_superadmin:
        consulta = consulta.where(or_(
            (TipoMedidor.prestador_id.is_(None)) & (TipoMedidor.tenant_id.is_(None)),
            TipoMedidor.prestador_id == actor.prestador_id,
            TipoMedidor.tenant_id == actor.tenant_id,
        ))
    return list((await db.execute(consulta)).scalars())


def _duenio_del_tipo(actor: Actor, global_: bool) -> dict[str, UUID | None]:
    if global_:
        if not actor.es_superadmin:
            raise prohibido("Solo el Superadmin mantiene el catálogo global de tipos de medidor")
        return {"prestador_id": None, "tenant_id": None}
    if actor.dominio == Dominio.prestador:
        return {"prestador_id": actor.prestador_id, "tenant_id": None}
    if actor.dominio == Dominio.tenant:
        return {"prestador_id": None, "tenant_id": actor.tenant_id}
    raise ErrorAPI(422, "DUENIO_REQUERIDO", "Indica `global: true` o usa un usuario de prestador o de cliente")


async def crear_tipo(db: AsyncSession, actor: Actor, datos: dict[str, Any], request: Request | None) -> TipoMedidor:
    _exigir(actor, GESTIONAN_CATALOGO, "mantiene el catálogo de tipos de medidor")
    duenio = _duenio_del_tipo(actor, bool(datos.get("global")))
    tipo = TipoMedidor(
        **duenio, nombre=datos["nombre"].strip(), unidad=datos["unidad"].strip(),
        categoria=CategoriaMedidor(datos.get("categoria") or "personalizado"), descripcion=datos.get("descripcion") or "",
        permite_estimacion=datos.get("permite_estimacion", True), decimales=datos.get("decimales", 0),
        requiere_foto=datos.get("requiere_foto", False),
        factor_salto_maximo=Decimal(str(datos.get("factor_salto_maximo") or 3)))
    db.add(tipo)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "medidores.tipo_alta", request, recurso_tipo="tipo_medidor", recurso_id=tipo.id,
                                    tenant_id=tipo.tenant_id, prestador_id=tipo.prestador_id,
                                    despues={"nombre": tipo.nombre, "unidad": tipo.unidad, "categoria": tipo.categoria.value})
    return tipo


async def editar_tipo(db: AsyncSession, actor: Actor, tipo_id: UUID, cambios: dict[str, Any], request: Request | None) -> TipoMedidor:
    _exigir(actor, GESTIONAN_CATALOGO, "mantiene el catálogo de tipos de medidor")
    tipo = await db.get(TipoMedidor, tipo_id)
    if tipo is None:
        raise no_encontrado("Tipo de medidor")
    if tipo.prestador_id is None and tipo.tenant_id is None and not actor.es_superadmin:
        raise prohibido("El catálogo global lo mantiene el Superadmin")
    if not actor.es_superadmin and tipo.prestador_id not in (None, actor.prestador_id) and tipo.tenant_id not in (None, actor.tenant_id):
        raise no_encontrado("Tipo de medidor")
    antes = auditoria.instantanea(tipo)
    for k, v in cambios.items():
        if k == "categoria" and v is not None:
            tipo.categoria = CategoriaMedidor(v)
        elif k == "factor_salto_maximo" and v is not None:
            tipo.factor_salto_maximo = Decimal(str(v))
        elif k in ("nombre", "unidad", "descripcion", "permite_estimacion", "decimales", "requiere_foto", "activo") and v is not None:
            setattr(tipo, k, v)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "medidores.tipo_modificacion", request, recurso_tipo="tipo_medidor", recurso_id=tipo.id,
                                    tenant_id=tipo.tenant_id, prestador_id=tipo.prestador_id, antes=antes, despues=auditoria.instantanea(tipo))
    return tipo


# ------------------------------------------------------------------ medidores por equipo

async def medidores_de(db: AsyncSession, equipo_id: UUID, incluir_inactivos: bool = False) -> list[EquipoMedidor]:
    consulta = select(EquipoMedidor).where(EquipoMedidor.equipo_id == equipo_id).order_by(EquipoMedidor.created_at)
    if not incluir_inactivos:
        consulta = consulta.where(EquipoMedidor.activo.is_(True))
    return list((await db.execute(consulta)).scalars())


async def alta_medidor(db: AsyncSession, actor: Actor, equipo: Equipo, datos: dict[str, Any], request: Request | None) -> EquipoMedidor:
    _exigir(actor, GESTIONAN_MEDIDOR, "da de alta medidores")
    tipo = await db.get(TipoMedidor, datos["tipo_medidor_id"])
    if tipo is None or not tipo.activo:
        raise ErrorAPI(422, "TIPO_MEDIDOR_INVALIDO", "El tipo de medidor no existe o está inactivo")
    # El tipo tiene que alcanzar a este equipo: global, del propio cliente, o de un prestador que lo atienda.
    if tipo.tenant_id is not None and tipo.tenant_id != equipo.tenant_id:
        raise ErrorAPI(422, "TIPO_MEDIDOR_INVALIDO", "Ese tipo de medidor es de otro cliente")
    if tipo.prestador_id is not None and tipo.prestador_id not in await _prestadores_del_tenant(db, equipo.tenant_id):
        raise ErrorAPI(422, "TIPO_MEDIDOR_INVALIDO", "Ese tipo de medidor es de un prestador que no atiende a este cliente")
    ya = (await db.execute(select(EquipoMedidor).where(EquipoMedidor.equipo_id == equipo.id,
                                                       EquipoMedidor.tipo_medidor_id == tipo.id,
                                                       EquipoMedidor.activo.is_(True)))).scalar_one_or_none()
    if ya is not None:
        raise ErrorAPI(409, "MEDIDOR_DUPLICADO", f"El equipo ya tiene un medidor de {tipo.nombre} activo")
    inicial = Decimal(str(datos.get("valor_inicial") or 0))
    maximo = datos.get("valor_maximo")
    m = EquipoMedidor(
        equipo_id=equipo.id, tipo_medidor_id=tipo.id, tenant_id=equipo.tenant_id,
        valor_actual=inicial, valor_acumulado=inicial, valor_ultimo_pm=inicial,
        metodo_actualizacion=MetodoActualizacionMedidor(datos.get("metodo_actualizacion") or "tecnico"),
        valor_maximo=Decimal(str(maximo)) if maximo is not None else None,
        numero_serie_medidor=datos.get("numero_serie_medidor"), instalado_en=datos.get("instalado_en"))
    if m.metodo_actualizacion == MetodoActualizacionMedidor.estimado and not tipo.permite_estimacion:
        raise ErrorAPI(422, "ESTIMACION_NO_PERMITIDA", f"El tipo {tipo.nombre} no admite lecturas estimadas")
    db.add(m)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "medidores.alta", request, recurso_tipo="equipo_medidor", recurso_id=m.id,
                                    tenant_id=equipo.tenant_id, despues={"equipo_id": str(equipo.id), "tipo": tipo.nombre,
                                                                         "valor_inicial": str(inicial)})
    return m


async def editar_medidor(db: AsyncSession, actor: Actor, m: EquipoMedidor, cambios: dict[str, Any], request: Request | None) -> EquipoMedidor:
    """Lo editable es la configuración, no el valor: el valor solo se mueve con lecturas y cambios registrados."""
    _exigir(actor, GESTIONAN_MEDIDOR, "edita medidores")
    antes = auditoria.instantanea(m)
    for k, v in cambios.items():
        if v is None:
            continue
        if k == "metodo_actualizacion":
            metodo = MetodoActualizacionMedidor(v)
            tipo = await db.get(TipoMedidor, m.tipo_medidor_id)
            if metodo == MetodoActualizacionMedidor.estimado and tipo is not None and not tipo.permite_estimacion:
                raise ErrorAPI(422, "ESTIMACION_NO_PERMITIDA", f"El tipo {tipo.nombre} no admite lecturas estimadas")
            m.metodo_actualizacion = metodo
        elif k == "valor_maximo":
            m.valor_maximo = Decimal(str(v))
        elif k in ("numero_serie_medidor", "instalado_en", "activo"):
            setattr(m, k, v)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "medidores.modificacion", request, recurso_tipo="equipo_medidor", recurso_id=m.id,
                                    tenant_id=m.tenant_id, antes=antes, despues=auditoria.instantanea(m))
    return m


# ------------------------------------------------------------------ acumulado, reinicios y reemplazos

def acumulado_de(m: EquipoMedidor, valor: Decimal) -> Decimal:
    """Unidades reales que lleva el equipo con ese marcador (ver el encabezado del módulo)."""
    return (m.acumulado_offset + (valor - m.ciclo_inicio)).quantize(CENTAVO)


async def registrar_cambio(db: AsyncSession, actor: Actor, m: EquipoMedidor, *, tipo: TipoCambioMedidor,
                           valor_nuevo: Decimal, motivo: str, numero_serie_nuevo: str | None = None,
                           request: Request | None = None, momento: datetime | None = None) -> MedidorCambio:
    """Reinicio del marcador o reemplazo del medidor. Las dos operaciones hacen la misma cuenta: lo andado hasta
    ahora se guarda en `acumulado_offset` y el ciclo nuevo arranca en `valor_nuevo`. La diferencia es que el
    reemplazo es un evento que puede disparar planes (`cambio_medidor`)."""
    _exigir(actor, GESTIONAN_MEDIDOR, "registra reinicios ni cambios de medidor")
    if not (motivo or "").strip():
        raise ErrorAPI(422, "MOTIVO_REQUERIDO", "Un reinicio o un cambio de medidor necesita motivo: es lo que explica el salto del historial")
    valor_nuevo = Decimal(str(valor_nuevo))
    if valor_nuevo < CERO:
        raise ErrorAPI(422, "VALOR_INVALIDO", "El valor nuevo del marcador no puede ser negativo")
    anterior, acumulado = m.valor_actual, m.valor_acumulado
    cambio = MedidorCambio(equipo_medidor_id=m.id, tenant_id=m.tenant_id, tipo=tipo, valor_anterior=anterior,
                           valor_nuevo=valor_nuevo, acumulado_al_cambio=acumulado,
                           numero_serie_anterior=m.numero_serie_medidor, numero_serie_nuevo=numero_serie_nuevo,
                           motivo=motivo.strip(), registrado_por=actor.id,
                           timestamp=momento or datetime.now(UTC))
    db.add(cambio)
    m.acumulado_offset = acumulado
    m.ciclo_inicio = valor_nuevo
    m.valor_actual = valor_nuevo
    m.valor_acumulado = acumulado
    if tipo == TipoCambioMedidor.reemplazo_medidor and numero_serie_nuevo is not None:
        m.numero_serie_medidor = numero_serie_nuevo
    await db.flush()
    await auditoria.registrar_actor(db, actor, f"medidores.{tipo.value}", request, recurso_tipo="equipo_medidor", recurso_id=m.id,
                                    tenant_id=m.tenant_id, antes={"valor_actual": str(anterior)},
                                    despues={"valor_actual": str(valor_nuevo), "acumulado": str(acumulado), "motivo": motivo})
    if tipo == TipoCambioMedidor.reemplazo_medidor:
        from services import triggers_service

        await triggers_service.evaluar_evento(db, "cambio_medidor", equipo_id=m.equipo_id,
                                              datos={"equipo_medidor_id": str(m.id), "tipo_medidor_id": str(m.tipo_medidor_id)})
    return cambio


async def cambios_de(db: AsyncSession, equipo_medidor_id: UUID) -> list[MedidorCambio]:
    return list((await db.execute(select(MedidorCambio).where(MedidorCambio.equipo_medidor_id == equipo_medidor_id)
                                  .order_by(MedidorCambio.timestamp.desc()))).scalars())


# ------------------------------------------------------------------ lecturas

async def ultima_valida(db: AsyncSession, equipo_medidor_id: UUID, antes_de: datetime | None = None) -> MedidorLectura | None:
    consulta = select(MedidorLectura).where(MedidorLectura.equipo_medidor_id == equipo_medidor_id,
                                            MedidorLectura.estado == EstadoLecturaMedidor.valida)
    if antes_de is not None:
        consulta = consulta.where(MedidorLectura.timestamp < antes_de)
    return (await db.execute(consulta.order_by(MedidorLectura.timestamp.desc()).limit(1))).scalar_one_or_none()


def dias_operativos(horario: dict[str, Any] | None, desde: date, hasta: date) -> int:
    """Días de operación en (desde, hasta]. `horario_operacion_json = {"dias": [...], "horas_por_dia": N}`;
    sin `dias` configurados cuentan los siete."""
    dias = {str(d).lower() for d in (horario or {}).get("dias", [])} or set(DIAS_SEMANA)
    total, cursor = 0, desde + timedelta(days=1)
    while cursor <= hasta:
        if DIAS_SEMANA[cursor.weekday()] in dias:
            total += 1
        cursor += timedelta(days=1)
    return total


async def incremento_diario(db: AsyncSession, m: EquipoMedidor) -> tuple[Decimal, str]:
    """Incremento por día que se usa para proyectar y para detectar saltos. Devuelve (valor, origen)."""
    est = (await db.execute(select(MedidorEstimacion).where(MedidorEstimacion.equipo_medidor_id == m.id))).scalar_one_or_none()
    if est is not None and est.incremento_real_promedio and est.incremento_real_promedio > CERO:
        return Decimal(est.incremento_real_promedio), "promedio_real"
    if est is not None and est.incremento_por_dia > CERO:
        return Decimal(est.incremento_por_dia), "configurado"
    # Sin configuración: promedio de las lecturas reales que ya existen.
    filas = (await db.execute(select(MedidorLectura).where(
        MedidorLectura.equipo_medidor_id == m.id, MedidorLectura.estado == EstadoLecturaMedidor.valida,
        MedidorLectura.metodo != MetodoActualizacionMedidor.estimado).order_by(MedidorLectura.timestamp))).scalars().all()
    if len(filas) < 2:
        return CERO, "sin_datos"
    dias = max(1, (filas[-1].timestamp - filas[0].timestamp).days)
    delta = Decimal(filas[-1].valor_acumulado) - Decimal(filas[0].valor_acumulado)
    if delta <= CERO:
        return CERO, "sin_datos"
    return (delta / Decimal(dias)).quantize(Decimal("0.0001")), "historial"


async def _revisar_anomalia(db: AsyncSession, m: EquipoMedidor, tipo: TipoMedidor, valor: Decimal, acumulado: Decimal,
                            momento: datetime) -> str:
    """Devuelve el motivo si la lectura es anómala, o cadena vacía si es normal."""
    previa = await ultima_valida(db, m.id)
    if previa is None:
        return ""
    if acumulado < Decimal(previa.valor_acumulado):
        return (f"La lectura ({valor} {tipo.unidad}) deja el acumulado en {acumulado} {tipo.unidad}, por debajo de "
                f"{previa.valor_acumulado} {tipo.unidad} del {previa.timestamp.date().isoformat()}. Si el marcador se "
                f"reinició o se cambió el medidor, regístralo antes de capturar la lectura.")
    dias = max(1, (momento.date() - previa.timestamp.date()).days)
    esperado, _origen = await incremento_diario(db, m)
    if esperado <= CERO:
        return ""   # sin referencia no hay salto que medir
    limite = (esperado * Decimal(dias) * Decimal(tipo.factor_salto_maximo)).quantize(CENTAVO)
    salto = acumulado - Decimal(previa.valor_acumulado)
    if salto > limite:
        return (f"El salto de {salto} {tipo.unidad} en {dias} día(s) es más de {tipo.factor_salto_maximo}× lo esperado "
                f"({limite} {tipo.unidad} con {esperado} {tipo.unidad} al día).")
    return ""


async def registrar_lectura(db: AsyncSession, actor: Actor | None, m: EquipoMedidor, *, valor: Decimal,
                            metodo: MetodoActualizacionMedidor, momento: datetime | None = None,
                            timestamp_dispositivo: datetime | None = None, folio_id: UUID | None = None,
                            respuesta_id: UUID | None = None, evidencia_id: UUID | None = None,
                            llave_api_id: UUID | None = None, registrado_por: UUID | None = None,
                            request: Request | None = None, evaluar: bool = True) -> dict[str, Any]:
    """Registra una lectura y, si es válida, mueve el medidor y evalúa los planes por uso de inmediato.

    Devuelve `{lectura, duplicada, anomalia, generados}`: `generados` son los folios preventivos que la lectura
    disparó (evaluación inmediata, para no esperar a la tarea nocturna)."""
    if not m.activo:
        raise ErrorAPI(409, "MEDIDOR_INACTIVO", "Ese medidor está dado de baja")
    tipo = await db.get(TipoMedidor, m.tipo_medidor_id)
    valor = Decimal(str(valor))
    if valor < CERO:
        raise ErrorAPI(422, "VALOR_INVALIDO", "La lectura no puede ser negativa")
    if m.valor_maximo is not None and valor > m.valor_maximo:
        raise ErrorAPI(422, "VALOR_SOBRE_MAXIMO",
                       f"La lectura ({valor}) pasa el máximo del marcador ({m.valor_maximo}): registra el reinicio")
    ahora = datetime.now(UTC)
    del_dispositivo = timestamp_dispositivo or momento
    efectivo = del_dispositivo or ahora
    if efectivo.tzinfo is None:
        efectivo = efectivo.replace(tzinfo=UTC)
    if efectivo > ahora + timedelta(minutes=TOLERANCIA_FUTURO_MIN):
        raise ErrorAPI(422, "LECTURA_FUTURA",
                       f"La lectura tiene fecha futura ({efectivo.isoformat()}): revisa el reloj del dispositivo o el archivo")

    if del_dispositivo is not None:
        duplicada = (await db.execute(select(MedidorLectura).where(
            MedidorLectura.equipo_medidor_id == m.id, MedidorLectura.timestamp_dispositivo == del_dispositivo,
            MedidorLectura.valor == valor))).scalars().first()
        if duplicada is not None:
            return {"lectura": duplicada, "duplicada": True, "anomalia": "", "generados": []}

    acumulado = acumulado_de(m, valor)
    motivo = await _revisar_anomalia(db, m, tipo, valor, acumulado, efectivo)
    equipo = await db.get(Equipo, m.equipo_id)
    prestador_id = (actor.prestador_id if actor is not None and actor.dominio == Dominio.prestador
                    else await prestador_responsable(db, m.tenant_id))
    lectura = MedidorLectura(
        equipo_medidor_id=m.id, equipo_id=m.equipo_id, tipo_medidor_id=m.tipo_medidor_id, tenant_id=m.tenant_id,
        prestador_id=prestador_id, valor=valor, valor_acumulado=acumulado, metodo=metodo,
        registrado_por=registrado_por or (actor.id if actor is not None else None), folio_id=folio_id,
        respuesta_id=respuesta_id, evidencia_id=evidencia_id, llave_api_id=llave_api_id,
        timestamp_dispositivo=del_dispositivo, timestamp=efectivo,
        estado=EstadoLecturaMedidor.en_revision if motivo else EstadoLecturaMedidor.valida, motivo=motivo)
    db.add(lectura)
    await db.flush()

    if motivo:
        await alertas_service.disparar(db, "MEDIDOR_LECTURA_ANOMALA", tenant_id=m.tenant_id, prestador_id=prestador_id,
                                       entidad_tipo="medidor_lectura", entidad_id=lectura.id,
                                       datos={"equipo_id": str(m.equipo_id), "equipo": equipo.nombre if equipo else "",
                                              "medidor": tipo.nombre if tipo else "", "valor": str(valor),
                                              "unidad": tipo.unidad if tipo else "", "motivo": motivo,
                                              "etiqueta": f"Lectura en revisión: {motivo[:160]}"})
        return {"lectura": lectura, "duplicada": False, "anomalia": motivo, "generados": []}

    generados = await _aplicar_lectura(db, m, lectura, evaluar=evaluar)
    if actor is not None:
        await auditoria.registrar_actor(db, actor, "medidores.lectura", request, recurso_tipo="medidor_lectura",
                                        recurso_id=lectura.id, tenant_id=m.tenant_id, prestador_id=prestador_id,
                                        despues={"equipo_medidor_id": str(m.id), "valor": str(valor),
                                                 "acumulado": str(acumulado), "metodo": metodo.value})
    return {"lectura": lectura, "duplicada": False, "anomalia": "", "generados": generados}


async def _aplicar_lectura(db: AsyncSession, m: EquipoMedidor, lectura: MedidorLectura, evaluar: bool = True) -> list[dict]:
    """Mueve el medidor con una lectura válida, corrige los estimados y evalúa los planes por uso."""
    if lectura.timestamp is not None and (m.fecha_ultima_lectura is None or lectura.timestamp >= m.fecha_ultima_lectura):
        m.valor_actual = Decimal(lectura.valor)
        m.valor_acumulado = Decimal(lectura.valor_acumulado)
        m.fecha_ultima_lectura = lectura.timestamp
    await db.flush()
    if lectura.metodo != MetodoActualizacionMedidor.estimado:
        await _corregir_estimados(db, m, lectura)
    if not evaluar:
        return []
    from services import triggers_service

    return await triggers_service.evaluar_medidor(db, m)


async def _corregir_estimados(db: AsyncSession, m: EquipoMedidor, real: MedidorLectura) -> None:
    """Una lectura real **corrige** lo estimado: los estimados posteriores a la última lectura real quedan
    rechazados (append-only: no se borran, se marcan) y el incremento real promedio se recalcula con la distancia
    entre las dos últimas lecturas reales. La pantalla muestra estimado vs. real con esos dos números."""
    previa_real = (await db.execute(select(MedidorLectura).where(
        MedidorLectura.equipo_medidor_id == m.id, MedidorLectura.id != real.id,
        MedidorLectura.estado == EstadoLecturaMedidor.valida,
        MedidorLectura.metodo != MetodoActualizacionMedidor.estimado,
        MedidorLectura.timestamp <= real.timestamp).order_by(MedidorLectura.timestamp.desc()).limit(1))).scalar_one_or_none()
    desde = previa_real.timestamp if previa_real is not None else None
    consulta = select(MedidorLectura).where(MedidorLectura.equipo_medidor_id == m.id,
                                            MedidorLectura.metodo == MetodoActualizacionMedidor.estimado,
                                            MedidorLectura.estado == EstadoLecturaMedidor.valida,
                                            MedidorLectura.timestamp <= real.timestamp)
    if desde is not None:
        consulta = consulta.where(MedidorLectura.timestamp > desde)
    estimados = list((await db.execute(consulta)).scalars())
    for e in estimados:
        e.estado = EstadoLecturaMedidor.rechazada
        e.motivo = f"Corregida por la lectura real del {real.timestamp.date().isoformat()} ({real.valor})"
    est = (await db.execute(select(MedidorEstimacion).where(MedidorEstimacion.equipo_medidor_id == m.id))).scalar_one_or_none()
    if est is not None and previa_real is not None:
        dias = dias_operativos(est.horario_operacion_json, previa_real.timestamp.date(), real.timestamp.date())
        delta = Decimal(real.valor_acumulado) - Decimal(previa_real.valor_acumulado)
        if dias > 0 and delta >= CERO:
            est.incremento_real_promedio = (delta / Decimal(dias)).quantize(Decimal("0.0001"))
    await db.flush()


async def revisar_lectura(db: AsyncSession, actor: Actor, lectura: MedidorLectura, aprobar: bool, razon: str,
                          request: Request | None) -> dict[str, Any]:
    """Despachador o Admin prestador resuelven una lectura anómala. Aprobarla la aplica (y puede generar folios)."""
    _exigir(actor, REVISAN, "revisa lecturas anómalas")
    if lectura.estado != EstadoLecturaMedidor.en_revision:
        raise ErrorAPI(409, "LECTURA_YA_RESUELTA", f"Esa lectura ya está {lectura.estado.value}")
    if not aprobar and not (razon or "").strip():
        raise ErrorAPI(422, "RAZON_REQUERIDA", "Rechazar una lectura exige la razón")
    m = await db.get(EquipoMedidor, lectura.equipo_medidor_id)
    generados: list[dict] = []
    if aprobar:
        # Al aprobar se recalcula el acumulado con el estado actual del medidor: entre la captura y la revisión
        # pudo registrarse el reinicio que explicaba la anomalía.
        lectura.valor_acumulado = acumulado_de(m, Decimal(lectura.valor))
        lectura.estado = EstadoLecturaMedidor.valida
        lectura.motivo = (razon or "").strip() or f"Aprobada en revisión: {lectura.motivo}"[:500]
    else:
        lectura.estado = EstadoLecturaMedidor.rechazada
        lectura.motivo = razon.strip()
    lectura.revisada_por, lectura.revisada_at = actor.id, datetime.now(UTC)
    await db.flush()
    if aprobar:
        generados = await _aplicar_lectura(db, m, lectura)
    await auditoria.registrar_actor(db, actor, "medidores.lectura_revisada", request, recurso_tipo="medidor_lectura",
                                    recurso_id=lectura.id, tenant_id=lectura.tenant_id,
                                    despues={"estado": lectura.estado.value, "razon": lectura.motivo})
    # La alerta queda atendida: ya la resolvió una persona.
    from models.alertas import AlertaHistorial
    from models.base import EstadoAlerta

    pendientes = (await db.execute(select(AlertaHistorial).where(
        AlertaHistorial.clave_alerta == "MEDIDOR_LECTURA_ANOMALA", AlertaHistorial.entidad_id == lectura.id,
        AlertaHistorial.estado != EstadoAlerta.resuelta))).scalars().all()
    for h in pendientes:
        await alertas_service.atender(db, actor, h, nota=lectura.motivo[:200])
    return {"lectura": lectura, "generados": generados}


async def listar_lecturas(db: AsyncSession, actor: Actor, *, equipo_id: UUID | None = None,
                          equipo_medidor_id: UUID | None = None, estado: EstadoLecturaMedidor | None = None,
                          desde: date | None = None, hasta: date | None = None, limite: int = 200) -> list[MedidorLectura]:
    _exigir(actor, CONSULTAN, "consulta lecturas de medidor")
    consulta = select(MedidorLectura).order_by(MedidorLectura.timestamp.desc()).limit(min(limite, 1000))
    if equipo_id:
        await equipo_visible(db, actor, equipo_id)
        consulta = consulta.where(MedidorLectura.equipo_id == equipo_id)
    if equipo_medidor_id:
        await medidor_visible(db, actor, equipo_medidor_id)
        consulta = consulta.where(MedidorLectura.equipo_medidor_id == equipo_medidor_id)
    if estado:
        consulta = consulta.where(MedidorLectura.estado == estado)
    if desde:
        consulta = consulta.where(MedidorLectura.timestamp >= datetime.combine(desde, datetime.min.time(), tzinfo=UTC))
    if hasta:
        consulta = consulta.where(MedidorLectura.timestamp <= datetime.combine(hasta, datetime.max.time(), tzinfo=UTC))
    if not actor.es_superadmin and actor.dominio == Dominio.tenant:
        consulta = consulta.where(MedidorLectura.tenant_id == actor.tenant_id)
    return list((await db.execute(consulta)).scalars())


async def pendientes_revision(db: AsyncSession, actor: Actor) -> list[dict[str, Any]]:
    """Bandeja «Lecturas por revisar» del Despachador y el Admin prestador."""
    _exigir(actor, REVISAN | {Rol.mesa_control}, "ve la bandeja de lecturas por revisar")
    filas = (await db.execute(
        select(MedidorLectura, EquipoMedidor, TipoMedidor, Equipo)
        .join(EquipoMedidor, EquipoMedidor.id == MedidorLectura.equipo_medidor_id)
        .join(TipoMedidor, TipoMedidor.id == MedidorLectura.tipo_medidor_id)
        .join(Equipo, Equipo.id == MedidorLectura.equipo_id)
        .where(MedidorLectura.estado == EstadoLecturaMedidor.en_revision)
        .order_by(MedidorLectura.timestamp.desc()).limit(300))).all()
    visibles = []
    for lectura, medidor, tipo, equipo in filas:
        if not actor.es_superadmin:
            if actor.dominio == Dominio.tenant and equipo.tenant_id != actor.tenant_id:
                continue
            if actor.dominio == Dominio.prestador and actor.prestador_id not in await _prestadores_del_tenant(db, equipo.tenant_id):
                continue
        previa = await ultima_valida(db, medidor.id, antes_de=lectura.timestamp)
        visibles.append({
            "id": lectura.id, "equipo_id": equipo.id, "equipo": equipo.nombre, "equipo_codigo": equipo.codigo,
            "tenant_id": equipo.tenant_id, "medidor": tipo.nombre, "unidad": tipo.unidad,
            "valor": lectura.valor, "valor_acumulado": lectura.valor_acumulado, "metodo": lectura.metodo,
            "motivo": lectura.motivo, "timestamp": lectura.timestamp,
            "valor_anterior": previa.valor if previa is not None else None,
            "fecha_anterior": previa.timestamp if previa is not None else None,
        })
    return visibles


# ------------------------------------------------------------------ estimación

async def estimacion_de(db: AsyncSession, equipo_medidor_id: UUID) -> MedidorEstimacion | None:
    return (await db.execute(select(MedidorEstimacion).where(MedidorEstimacion.equipo_medidor_id == equipo_medidor_id))).scalar_one_or_none()


async def configurar_estimacion(db: AsyncSession, actor: Actor, m: EquipoMedidor, datos: dict[str, Any],
                                request: Request | None) -> MedidorEstimacion:
    _exigir(actor, GESTIONAN_MEDIDOR, "configura la estimación de medidores")
    tipo = await db.get(TipoMedidor, m.tipo_medidor_id)
    if tipo is not None and not tipo.permite_estimacion:
        raise ErrorAPI(422, "ESTIMACION_NO_PERMITIDA", f"El tipo {tipo.nombre} no admite lecturas estimadas")
    est = await estimacion_de(db, m.id)
    if est is None:
        est = MedidorEstimacion(equipo_medidor_id=m.id, tenant_id=m.tenant_id)
        db.add(est)
    antes = auditoria.instantanea(est)
    if datos.get("incremento_por_dia") is not None:
        est.incremento_por_dia = Decimal(str(datos["incremento_por_dia"]))
    if datos.get("horario_operacion_json") is not None:
        horario = datos["horario_operacion_json"] or {}
        for d in horario.get("dias", []):
            if str(d).lower() not in DIAS_SEMANA:
                raise ErrorAPI(422, "HORARIO_INVALIDO", f"Día inválido: {d} (usa {', '.join(DIAS_SEMANA)})")
        est.horario_operacion_json = horario
    if datos.get("activa") is not None:
        est.activa = bool(datos["activa"])
    if datos.get("desde") is not None:
        est.desde = datos["desde"]
    await db.flush()
    await auditoria.registrar_actor(db, actor, "medidores.estimacion", request, recurso_tipo="medidor_estimacion",
                                    recurso_id=est.id, tenant_id=m.tenant_id, antes=antes, despues=auditoria.instantanea(est))
    return est


async def estimar_dia(db: AsyncSession, hoy: date | None = None) -> dict[str, int]:
    """Tarea diaria: por cada medidor con estimación activa escribe una lectura `estimado` con el incremento de los
    días de operación transcurridos. Idempotente: si ya hay una estimación de hoy, no escribe otra."""
    hoy = hoy or date.today()
    resumen = {"estimadas": 0, "omitidas": 0}
    filas = (await db.execute(select(MedidorEstimacion, EquipoMedidor).join(
        EquipoMedidor, EquipoMedidor.id == MedidorEstimacion.equipo_medidor_id).where(
        MedidorEstimacion.activa.is_(True), EquipoMedidor.activo.is_(True)))).all()
    for est, m in filas:
        if est.incremento_por_dia <= CERO:
            resumen["omitidas"] += 1
            continue
        if est.ultima_estimacion_at is not None and est.ultima_estimacion_at.date() >= hoy:
            resumen["omitidas"] += 1
            continue
        base_fecha = (m.fecha_ultima_lectura.date() if m.fecha_ultima_lectura is not None else est.desde)
        dias = dias_operativos(est.horario_operacion_json, base_fecha, hoy)
        if dias <= 0:
            resumen["omitidas"] += 1
            continue
        incremento = Decimal(est.incremento_real_promedio or est.incremento_por_dia) * Decimal(dias)
        valor = (Decimal(m.valor_actual) + incremento).quantize(CENTAVO)
        if m.valor_maximo is not None and valor > m.valor_maximo:
            # El marcador daría la vuelta: eso lo registra una persona (§6.9.2), no la estimación.
            resumen["omitidas"] += 1
            continue
        momento = datetime.combine(hoy, datetime.min.time(), tzinfo=UTC) + timedelta(hours=6)
        try:
            punto = await db.begin_nested()
            await registrar_lectura(db, None, m, valor=valor, metodo=MetodoActualizacionMedidor.estimado,
                                    momento=min(momento, datetime.now(UTC)))
            est.ultima_estimacion_at = datetime.now(UTC)
            await db.flush()
            await punto.commit()
            resumen["estimadas"] += 1
        except Exception:  # noqa: BLE001 — un medidor con problema no detiene a los demás
            await punto.rollback()
            resumen["omitidas"] += 1
    await db.flush()
    return resumen


# ------------------------------------------------------------------ unidades para la depreciación (§6.9.4)

async def unidades_entre(db: AsyncSession, equipo_medidor_id: UUID, desde: date, hasta: date) -> Decimal:
    """Unidades producidas (acumuladas) entre dos fechas, con las lecturas válidas. Para ACT-8.3."""
    inicio = (await db.execute(select(MedidorLectura.valor_acumulado).where(
        MedidorLectura.equipo_medidor_id == equipo_medidor_id, MedidorLectura.estado == EstadoLecturaMedidor.valida,
        MedidorLectura.timestamp <= datetime.combine(desde, datetime.max.time(), tzinfo=UTC))
        .order_by(MedidorLectura.timestamp.desc()).limit(1))).scalar()
    fin = (await db.execute(select(MedidorLectura.valor_acumulado).where(
        MedidorLectura.equipo_medidor_id == equipo_medidor_id, MedidorLectura.estado == EstadoLecturaMedidor.valida,
        MedidorLectura.timestamp <= datetime.combine(hasta, datetime.max.time(), tzinfo=UTC))
        .order_by(MedidorLectura.timestamp.desc()).limit(1))).scalar()
    if fin is None:
        return CERO
    return max(CERO, (Decimal(fin) - Decimal(inicio or 0)).quantize(CENTAVO))


async def acumulado_a_la_fecha(db: AsyncSession, equipo_medidor_id: UUID, hasta: date) -> Decimal:
    valor = (await db.execute(select(MedidorLectura.valor_acumulado).where(
        MedidorLectura.equipo_medidor_id == equipo_medidor_id, MedidorLectura.estado == EstadoLecturaMedidor.valida,
        MedidorLectura.timestamp <= datetime.combine(hasta, datetime.max.time(), tzinfo=UTC))
        .order_by(MedidorLectura.timestamp.desc()).limit(1))).scalar()
    return Decimal(valor or 0)


# ------------------------------------------------------------------ llaves de API del cliente

def _prefijo(llave: str) -> str:
    return llave[:8]


async def crear_llave(db: AsyncSession, actor: Actor, tenant_id: UUID, nombre: str, request: Request | None) -> tuple[LlaveApiTenant, str]:
    """Devuelve (fila, llave en claro). La llave en claro se muestra **una sola vez**."""
    if not actor.es_superadmin and actor.rol != Rol.admin_empresa:
        raise prohibido("Solo el Admin empresa y el Superadmin administran las llaves de API del cliente")
    if not actor.es_superadmin and tenant_id != actor.tenant_id:
        raise no_encontrado("Cliente")
    if not (nombre or "").strip():
        raise ErrorAPI(422, "NOMBRE_REQUERIDO", "Dale un nombre a la llave (el sistema que la va a usar)")
    claro = f"acma_{nuevo_token_opaco()}"
    fila = LlaveApiTenant(tenant_id=tenant_id, nombre=nombre.strip(), prefijo=_prefijo(claro),
                          llave_hash=hash_token(claro), permisos_json=[PERMISO_LECTURAS], creada_por=actor.id)
    db.add(fila)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "medidores.llave_api_alta", request, recurso_tipo="llave_api_tenant",
                                    recurso_id=fila.id, tenant_id=tenant_id,
                                    despues={"nombre": fila.nombre, "prefijo": fila.prefijo, "permisos": fila.permisos_json})
    return fila, claro


async def listar_llaves(db: AsyncSession, actor: Actor, tenant_id: UUID | None) -> list[LlaveApiTenant]:
    if not actor.es_superadmin and actor.rol != Rol.admin_empresa:
        raise prohibido("Solo el Admin empresa y el Superadmin ven las llaves de API del cliente")
    destino = tenant_id if actor.es_superadmin else actor.tenant_id
    consulta = select(LlaveApiTenant).order_by(LlaveApiTenant.created_at.desc())
    if destino is not None:
        consulta = consulta.where(LlaveApiTenant.tenant_id == destino)
    return list((await db.execute(consulta)).scalars())


async def revocar_llave(db: AsyncSession, actor: Actor, llave_id: UUID, request: Request | None) -> LlaveApiTenant:
    if not actor.es_superadmin and actor.rol != Rol.admin_empresa:
        raise prohibido("Solo el Admin empresa y el Superadmin revocan las llaves de API del cliente")
    fila = await db.get(LlaveApiTenant, llave_id)
    if fila is None or (not actor.es_superadmin and fila.tenant_id != actor.tenant_id):
        raise no_encontrado("Llave de API")
    if not fila.activa:
        return fila
    fila.activa, fila.revocada_at, fila.revocada_por = False, datetime.now(UTC), actor.id
    await db.flush()
    await auditoria.registrar_actor(db, actor, "medidores.llave_api_revocada", request, recurso_tipo="llave_api_tenant",
                                    recurso_id=fila.id, tenant_id=fila.tenant_id, despues={"prefijo": fila.prefijo})
    return fila


async def resolver_llave(db: AsyncSession, llave: str, permiso: str = PERMISO_LECTURAS) -> LlaveApiTenant:
    """Para la autenticación por llave: la llave viaja hasheada en la base, así que se compara el hash."""
    if not llave:
        raise ErrorAPI(401, "LLAVE_REQUERIDA", "Falta la cabecera X-ACMA-Llave")
    fila = (await db.execute(select(LlaveApiTenant).where(LlaveApiTenant.llave_hash == hash_token(llave)))).scalar_one_or_none()
    if fila is None:
        raise ErrorAPI(401, "LLAVE_INVALIDA", "La llave de API no existe")
    if not fila.activa:
        raise ErrorAPI(401, "LLAVE_REVOCADA", "Esa llave de API está revocada")
    if permiso not in (fila.permisos_json or []):
        raise ErrorAPI(403, "LLAVE_SIN_PERMISO", f"La llave no tiene el permiso {permiso}")
    fila.ultimo_uso_at = datetime.now(UTC)
    fila.usos = (fila.usos or 0) + 1
    return fila


# ------------------------------------------------------------------ lote (importación y API del cliente)

async def registrar_lote(db: AsyncSession, actor: Actor | None, tenant_id: UUID, lecturas: list[dict[str, Any]], *,
                         metodo: MetodoActualizacionMedidor = MetodoActualizacionMedidor.importacion,
                         llave_api_id: UUID | None = None, request: Request | None = None) -> dict[str, Any]:
    """Lecturas en lote por código de equipo y nombre del tipo de medidor. Cada fila se resuelve en su savepoint:
    una mala no tira el lote (es lo que necesita un SCADA que manda cientos por hora)."""
    resultados: list[dict[str, Any]] = []
    aplicadas = duplicadas = en_revision = rechazadas = 0
    equipos = {e.codigo.lower(): e for e in (await db.execute(select(Equipo).where(Equipo.tenant_id == tenant_id))).scalars()}
    for i, fila in enumerate(lecturas):
        codigo = str(fila.get("equipo_codigo") or "").strip().lower()
        equipo = equipos.get(codigo)
        if equipo is None:
            resultados.append({"indice": i, "estado": "rechazada", "motivo": f"No existe el equipo {codigo}"})
            rechazadas += 1
            continue
        nombre_tipo = str(fila.get("tipo_medidor") or "").strip().lower()
        medidores = await medidores_de(db, equipo.id)
        destino = None
        for m in medidores:
            t = await db.get(TipoMedidor, m.tipo_medidor_id)
            if t is not None and t.nombre.lower() == nombre_tipo:
                destino = m
                break
        if destino is None:
            resultados.append({"indice": i, "estado": "rechazada", "motivo": f"El equipo {equipo.codigo} no tiene un medidor de «{fila.get('tipo_medidor')}»"})
            rechazadas += 1
            continue
        try:
            punto = await db.begin_nested()
            r = await registrar_lectura(db, actor, destino, valor=Decimal(str(fila["valor"])), metodo=metodo,
                                        timestamp_dispositivo=fila.get("timestamp"), llave_api_id=llave_api_id,
                                        registrado_por=actor.id if actor is not None else None, request=request)
            await punto.commit()
            if r["duplicada"]:
                estado = "duplicada"
                duplicadas += 1
            elif r["anomalia"]:
                estado = "en_revision"
                en_revision += 1
            else:
                estado = "aplicada"
                aplicadas += 1
            resultados.append({"indice": i, "estado": estado, "lectura_id": r["lectura"].id,
                               "motivo": r["anomalia"], "folios_generados": len(r["generados"])})
        except ErrorAPI as e:
            await punto.rollback()
            resultados.append({"indice": i, "estado": "rechazada", "motivo": e.mensaje})
            rechazadas += 1
    await db.flush()
    return {"total": len(lecturas), "aplicadas": aplicadas, "duplicadas": duplicadas, "en_revision": en_revision,
            "rechazadas": rechazadas, "resultados": resultados}


# ------------------------------------------------------------------ lectura desde el formulario (§6.9.2 técnico)

async def desde_respuesta(db: AsyncSession, actor: Actor, r, esquema) -> list[MedidorLectura]:
    """Campos con la bandera `lectura_medidor` del formulario de atención o del preventivo: al enviarse el
    formulario, cada uno registra su lectura con el folio. La foto del marcador va como evidencia del campo."""
    from models.formularios import FormularioEvidencia

    registradas: list[MedidorLectura] = []
    equipo_id = r.equipo_id or (r.contexto_json or {}).get("equipo_id")
    if equipo_id is None:
        return registradas
    equipo = await db.get(Equipo, equipo_id if isinstance(equipo_id, uuid.UUID) else UUID(str(equipo_id)))
    if equipo is None:
        return registradas
    evidencias = {e.campo_clave: e for e in (await db.execute(
        select(FormularioEvidencia).where(FormularioEvidencia.respuesta_id == r.id))).scalars()}
    for campo in esquema.campos:
        mapeo = getattr(campo, "lectura_medidor", None)
        if mapeo is None or campo.clave not in (r.respuestas_json or {}):
            continue
        crudo = (r.respuestas_json or {}).get(campo.clave)
        if crudo is None or str(crudo).strip() == "":
            continue
        try:
            valor = Decimal(str(crudo))
        except Exception:  # noqa: BLE001 — un campo de texto puede traer basura; la validación del tipo ya avisó
            continue
        medidor = (await db.execute(select(EquipoMedidor).where(
            EquipoMedidor.equipo_id == equipo.id, EquipoMedidor.tipo_medidor_id == mapeo.tipo_medidor_id,
            EquipoMedidor.activo.is_(True)))).scalar_one_or_none()
        if medidor is None:
            continue   # el formulario pide una lectura de un medidor que ese equipo no tiene: se ignora
        evidencia = evidencias.get(mapeo.campo_foto or "")
        resultado = await registrar_lectura(
            db, actor, medidor, valor=valor, metodo=MetodoActualizacionMedidor(mapeo.metodo or "tecnico"),
            momento=r.enviado_at, folio_id=r.referencia_id, respuesta_id=r.id,
            evidencia_id=evidencia.id if evidencia is not None else None)
        registradas.append(resultado["lectura"])
    return registradas


async def equipos_para_operador(db: AsyncSession, actor: Actor, un_id: UUID | None = None) -> list[dict[str, Any]]:
    """Pantalla «Registrar lectura» del operador: equipos de su unidad con medidor de método `operador`."""
    _exigir(actor, REGISTRAN_LECTURA, "registra lecturas de medidor")
    from services.preventivos_service import _unidades_visibles

    consulta = (select(EquipoMedidor, TipoMedidor, Equipo, UnidadNegocio)
                .join(TipoMedidor, TipoMedidor.id == EquipoMedidor.tipo_medidor_id)
                .join(Equipo, Equipo.id == EquipoMedidor.equipo_id)
                .join(UnidadNegocio, UnidadNegocio.id == Equipo.un_id)
                .where(EquipoMedidor.activo.is_(True), EquipoMedidor.metodo_actualizacion == MetodoActualizacionMedidor.operador)
                .order_by(Equipo.codigo))
    if un_id is not None:
        consulta = consulta.where(Equipo.un_id == un_id)
    if not actor.es_superadmin:
        if actor.dominio == Dominio.tenant:
            consulta = consulta.where(Equipo.tenant_id == actor.tenant_id)
            unidades = await _unidades_visibles(db, actor)
            if unidades is not None:
                consulta = consulta.where(Equipo.un_id.in_(unidades))
        else:
            from models.organizaciones import TenantPrestador

            tenants = list((await db.execute(select(TenantPrestador.tenant_id).where(
                TenantPrestador.prestador_id == actor.prestador_id))).scalars())
            consulta = consulta.where(Equipo.tenant_id.in_(tenants))
    salida = []
    for m, tipo, equipo, un in (await db.execute(consulta)).all():
        salida.append({"equipo_medidor_id": m.id, "equipo_id": equipo.id, "equipo": equipo.nombre,
                       "equipo_codigo": equipo.codigo, "un_id": un.id, "un_codigo": un.codigo,
                       "medidor": tipo.nombre, "unidad": tipo.unidad, "decimales": tipo.decimales,
                       "requiere_foto": tipo.requiere_foto, "valor_actual": m.valor_actual,
                       "valor_maximo": m.valor_maximo, "fecha_ultima_lectura": m.fecha_ultima_lectura})
    return salida


async def medidor_del_plan(db: AsyncSession, plan_id: UUID, equipo_id: UUID) -> EquipoMedidor | None:
    """El medidor que disparó el plan: lo que el formulario del preventivo pide leer (§6.9.1)."""
    from models.preventivos import PlanTrigger, TipoTrigger

    triggers = (await db.execute(select(PlanTrigger).where(PlanTrigger.plan_id == plan_id))).scalars().all()
    for t in triggers:
        if t.tipo_trigger in (TipoTrigger.medidor_umbral, TipoTrigger.medidor_intervalo):
            tipo_id = (t.parametros_json or {}).get("tipo_medidor_id")
            if not tipo_id:
                continue
            m = (await db.execute(select(EquipoMedidor).where(
                EquipoMedidor.equipo_id == equipo_id, EquipoMedidor.tipo_medidor_id == UUID(str(tipo_id)),
                EquipoMedidor.activo.is_(True)))).scalar_one_or_none()
            if m is not None:
                return m
    return None


async def resumen_de_equipo(db: AsyncSession, db_actor: Actor, equipo: Equipo) -> list[dict[str, Any]]:
    """Pestaña «Medidores» de la ficha del equipo: valor actual, próximo mantenimiento por uso y fecha estimada."""
    from services import triggers_service

    salida = []
    for m in await medidores_de(db, equipo.id, incluir_inactivos=True):
        tipo = await db.get(TipoMedidor, m.tipo_medidor_id)
        est = await estimacion_de(db, m.id)
        incremento, origen = await incremento_diario(db, m)
        salida.append({
            "id": m.id, "tipo_medidor_id": m.tipo_medidor_id, "tipo": tipo.nombre if tipo else "",
            "unidad": tipo.unidad if tipo else "", "categoria": tipo.categoria if tipo else None,
            "decimales": tipo.decimales if tipo else 0, "requiere_foto": tipo.requiere_foto if tipo else False,
            "valor_actual": m.valor_actual, "valor_acumulado": m.valor_acumulado, "valor_ultimo_pm": m.valor_ultimo_pm,
            "fecha_ultima_lectura": m.fecha_ultima_lectura, "metodo_actualizacion": m.metodo_actualizacion,
            "valor_maximo": m.valor_maximo, "numero_serie_medidor": m.numero_serie_medidor,
            "instalado_en": m.instalado_en, "activo": m.activo,
            "incremento_por_dia": incremento, "origen_incremento": origen,
            "estimacion": None if est is None else {
                "incremento_por_dia": est.incremento_por_dia, "incremento_real_promedio": est.incremento_real_promedio,
                "horario_operacion_json": est.horario_operacion_json, "activa": est.activa, "desde": est.desde,
                "ultima_estimacion_at": est.ultima_estimacion_at},
            "proximos_mantenimientos": await triggers_service.proximos_de_medidor(db, m),
        })
    return salida
