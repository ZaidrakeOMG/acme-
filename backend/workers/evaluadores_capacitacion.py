"""Evaluador de la alerta CERTIFICACION_VENCIDA (§6.9.6, §6.10.3). F2-01.

La alerta avisa **antes** de que la certificación venza: el umbral del catálogo son los días de anticipación
(default 30, rango 1–180) y cada prestador puede ajustarlo en `capacitacion_alertas_config`, que es lo que §6.10.3
pone en sus manos. Entre los dos gana el más corto de la configuración del prestador, porque es la que el Admin
prestador ve y edita en su pantalla.

`CERTIFICACION_VENCIDA_HABILIDAD_RETIRADA` no se evalúa aquí: la dispara el servicio el día en que efectivamente
retira la habilidad (`capacitacion_service._retirar_habilidad`), que es el hecho que importa.
"""
from datetime import date, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.alertas import AlertaCatalogo
from models.capacitacion import CapacitacionAlertasConfig, CursoCatalogo, TecnicoCurso
from models.catalogos import Tecnico
from models.usuarios import Usuario
from services import capacitacion_service
from workers.evaluadores import _umbral_p06 as _umbral, _ya_disparada
from workers.evaluadores_seguimiento import _disparar_una_vez
from workers.tareas import registrar_evaluador


@registrar_evaluador("CERTIFICACION_VENCIDA")
async def certificacion_vencida(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """Certificaciones que vencen dentro de la ventana, una sola vez por curso del técnico."""
    hoy = date.today()
    configs = {c.prestador_id: c for c in (await db.execute(select(CapacitacionAlertasConfig))).scalars()}
    # Solo cursos aprobados, con vigencia y que caducan: lo que no vence nunca no dispara nada.
    filas = (await db.execute(
        select(TecnicoCurso, CursoCatalogo, Usuario)
        .join(CursoCatalogo, CursoCatalogo.id == TecnicoCurso.curso_id)
        .join(Tecnico, Tecnico.id == TecnicoCurso.tecnico_id)
        .join(Usuario, Usuario.id == Tecnico.usuario_id)
        .where(TecnicoCurso.aprobado.is_(True), TecnicoCurso.vigente_hasta.is_not(None)))).all()
    disparadas = 0
    for tc, curso, usuario in filas:
        cfg = configs.get(tc.prestador_id)
        if cfg is not None and not cfg.activa:
            continue
        del_catalogo = int(await _umbral(db, alerta, None))
        dias_aviso = min(cfg.dias_anticipacion, del_catalogo) if cfg is not None else del_catalogo
        faltan = (tc.vigente_hasta - hoy).days
        if faltan > dias_aviso:
            continue
        nuevas = await _disparar_una_vez(
            db, alerta, tenant_id=None, prestador_id=tc.prestador_id, entidad_tipo="tecnico_curso",
            entidad_id=tc.id, datos={"tecnico_id": str(tc.tecnico_id), "tecnico": usuario.nombre,
                                     "curso": curso.nombre, "norma": curso.norma_referencia,
                                     "vigente_hasta": str(tc.vigente_hasta), "dias": faltan,
                                     "vencida": faltan < 0})
        if nuevas:
            # §6.10.3: aviso al Admin prestador, y al cliente solo si él lo configuró.
            await capacitacion_service._avisar(db, tc, retirada=False)
        disparadas += nuevas
    return disparadas
