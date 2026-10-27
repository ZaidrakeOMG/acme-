"""Celery: Redis como broker y backend. En Windows ejecutar el worker con --pool=solo.

  celery -A workers.celery_app worker --pool=solo -l info
  celery -A workers.celery_app beat -l info
"""
from celery import Celery

from core.config import config

celery_app = Celery("acma", broker=config.celery_broker_url, backend=config.celery_result_backend, include=["workers.tareas"])
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
    },
)

app = celery_app
