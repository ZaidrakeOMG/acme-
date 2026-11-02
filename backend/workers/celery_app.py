"""Celery: Redis como broker y backend. En Windows ejecutar el worker con --pool=solo.

  celery -A workers.celery_app worker --pool=solo -l info
  celery -A workers.celery_app beat -l info
"""
from celery import Celery
from celery.schedules import crontab

from core.config import config

celery_app = Celery("acma", broker=config.celery_broker_url, backend=config.celery_result_backend, include=["workers.tareas", "workers.tareas.preventivos", "workers.tareas.notificaciones", "workers.tareas.minuta"])
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
    },
)

app = celery_app
