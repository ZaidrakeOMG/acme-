"""Celery: Redis como broker y backend. En Windows ejecutar el worker con --pool=solo.

  celery -A workers.celery_app worker --pool=solo -l info
  celery -A workers.celery_app beat -l info
"""
from celery import Celery
from celery.schedules import crontab
from celery.signals import celeryd_init

from core.config import config

celery_app = Celery("acma", broker=config.celery_broker_url, backend=config.celery_result_backend, include=["workers.tareas", "workers.tareas.preventivos", "workers.tareas.notificaciones", "workers.tareas.minuta",
                            "workers.tareas.costos", "workers.tareas.sla"])
celery_app.conf.update(
    timezone="America/Mexico_City",
    enable_utc=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=3600,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "evaluar-alertas": {"task": "acma.evaluar_alertas", "schedule": 60.0},
        "timeouts-aprobacion": {"task": "acma.evaluar_timeouts_aprobacion", "schedule": 60.0},
        "particiones-auditoria": {"task": "acma.crear_particiones_auditoria", "schedule": 24 * 3600.0},
        "purgar-sesiones": {"task": "acma.purgar_sesiones_expiradas", "schedule": 6 * 3600.0},
        # P06: generación nocturna de folios preventivos (planes con trigger y calendario manual).
        "generar-preventivos": {"task": "acma.generar_preventivos_programados", "schedule": crontab(hour=2, minute=0)},
        # P07: minuta a la hora configurada por tenant (se revisa cada 10 min), notificaciones pendientes y calificación diaria.
        "generar-minutas": {"task": "acma.generar_minutas", "schedule": 600.0},
        "enviar-notificaciones-pendientes": {"task": "acma.enviar_notificaciones_pendientes", "schedule": 120.0},
        "calificar-admin-un": {"task": "acma.calificar_admin_un", "schedule": crontab(hour=6, minute=30)},
        # P09: reposición de caja chica al cierre de jornada, depreciación y TCO mensuales, exportación opcional al ERP.
        "polizas-caja-chica": {"task": "acma.generar_polizas_caja_chica", "schedule": crontab(hour=23, minute=0)},
        "depreciacion-tco": {"task": "acma.calcular_depreciacion_tco", "schedule": crontab(hour=3, minute=30, day_of_month=1)},
        "exportar-erp-periodo": {"task": "acma.exportar_erp_periodo", "schedule": crontab(hour=4, minute=0, day_of_month=1)},
        # P10: penalizaciones e iguala del mes cerrado, reportes programados y cierre de jornada (§6.10.1, ACT-8.4).
        "consolidar-penalizaciones": {"task": "acma.consolidar_penalizaciones", "schedule": crontab(hour=5, minute=0, day_of_month=1)},
        "reportes-programados": {"task": "acma.enviar_reportes_programados", "schedule": crontab(hour=8, minute=0)},
        "cierre-jornada": {"task": "acma.reporte_cierre_jornada", "schedule": crontab(hour=22, minute=30)},
        # P11a: retención de la bitácora de accesos a la API (§6.9.5).
        "purgar-accesos-api": {"task": "acma.purgar_accesos_api", "schedule": crontab(hour=3, minute=50)},
        # F2-01: antes de que empiece la jornada, para que el despachador ya vea retiradas las habilidades vencidas.
        "recalcular-capacitacion": {"task": "acma.recalcular_capacitacion", "schedule": crontab(hour=5, minute=10)},
        # F2-02: reintentos de WhatsApp y SMS que fallaron por algo temporal (espera exponencial en el servicio).
        "reintentar-mensajeria": {"task": "acma.reintentar_mensajeria", "schedule": 300.0},
        # F2-03: escalacion del tiempo muerto y refresco del estatus de los tecnicos (el mapa no debe mentir),
        # cierre de jornadas olvidadas y particiones diarias de posiciones con su retencion de 90 dias.
        "seguimiento-operacion": {"task": "acma.seguimiento_operacion", "schedule": 60.0},
        "cerrar-jornadas-inactivas": {"task": "acma.cerrar_jornadas_inactivas", "schedule": 900.0},
        "particiones-posiciones": {"task": "acma.crear_particiones_posiciones", "schedule": crontab(hour=3, minute=5)},
        "purgar-posiciones": {"task": "acma.purgar_posiciones", "schedule": crontab(hour=3, minute=40)},
    },
)

app = celery_app


@celeryd_init.connect
def _sesiones_sin_pool(**_: object) -> None:
    """El worker corre cada tarea en su propio event loop (`asyncio.run`), asi que un pool compartido guardaria
    conexiones de loops ya cerrados: el segundo envio de push de la corrida fallaba con "Event loop is closed".
    La senal solo se dispara al arrancar el worker; la API conserva su pool afinado en P11a."""
    from core.db import reconstruir_sin_pool

    reconstruir_sin_pool()
