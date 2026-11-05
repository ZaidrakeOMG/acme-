"""Configuración central leída de variables de entorno (.env en la raíz del repo)."""
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ_REPO = Path(__file__).resolve().parents[2]

# Campos que llevan secretos: en produccion ninguno puede quedarse con el valor de ejemplo del .env. P11a.
SECRETOS = ("jwt_secreto", "clave_cifrado", "minio_root_password", "smtp_password", "vapid_clave_privada",
            "database_url", "database_migrations_url", "redis_url", "celery_broker_url", "celery_result_backend")
MARCAS_DE_EJEMPLO = ("cambiar", "ejemplo", "changeme", "password", "secreto_dev", "acma_dev")
# La CLAVE_CIFRADO del .env.example es base64 valido, asi que no la delata ninguna marca de texto.
CLAVE_CIFRADO_EJEMPLO = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


class Configuracion(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(RAIZ_REPO / ".env", RAIZ_REPO / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    acma_entorno: str = "desarrollo"

    database_url: str
    database_read_url: str = ""
    database_migrations_url: str = ""
    test_database_url: str = ""
    test_database_migrations_url: str = ""

    redis_url: str = "redis://localhost:6389/0"
    celery_broker_url: str = "redis://localhost:6389/1"
    celery_result_backend: str = "redis://localhost:6389/2"

    almacenamiento_modo: str = "minio"
    minio_endpoint: str = "localhost:9010"
    minio_root_user: str = ""
    minio_root_password: str = ""
    minio_bucket: str = "acma"
    minio_seguro: bool = False

    jwt_secreto: str = Field(min_length=32)
    jwt_algoritmo: str = "HS256"
    jwt_acceso_minutos: int = 15
    jwt_mfa_minutos: int = 5
    # §6.9.5: la sesión vive 8 h (2 h para roles administrativos) y se cierra por inactividad; el token de acceso
    # sigue siendo corto y se renueva con el refresh rotativo mientras la sesión esté viva.
    # P11a cierra así la decisión pendiente n.º 1 (P01 pedía 15 min + 7 días; §6.9.5 pide 8 h / 2 h).
    sesion_horas: int = 8
    sesion_horas_admin: int = 2
    sesion_inactividad_minutos: int = 30
    # §6.9.5: vencimiento de la contraseña de los roles administrativos (0 = sin vencimiento).
    contrasena_dias_admin: int = 90
    # §6.9.5: retención de la bitácora de API (90 días normales, 1 año los errores 4xx/5xx).
    retencion_accesos_dias: int = 90
    retencion_accesos_errores_dias: int = 365
    # §6.9.5: geolocalización aproximada del login. Vacío = sin base (la auditoría anota geo: null). P11a.
    geoip_base: str = ""
    clave_cifrado: str
    mfa_obligatorio: bool = True
    cors_origenes: str = ""

    # Login: bloqueo por usuario y límite por IP (§6.9.5: 5 intentos en 10 min).
    login_max_intentos: int = 5
    login_ventana_minutos: int = 10
    login_bloqueo_minutos: int = 15

    # Pool de conexiones. NullPool en pruebas para no atar conexiones a un event loop.
    db_pool_nulo: bool = False

    # P05: tiempo real del chat ("redis" = pub/sub entre procesos; "local" = solo este proceso, pruebas).
    tiempo_real_modo: str = "redis"
    # P05: push PWA con web-push (VAPID). Sin claves, el envío solo se registra en el log.
    vapid_clave_publica: str = ""
    vapid_clave_privada: str = ""
    vapid_contacto: str = "mailto:soporte@acma.dev"

    # P07: correo por SMTP genérico (corporativo o SendGrid por SMTP). Sin SMTP_HOST → modo stub (.eml en el almacenamiento).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "ACMA <no-responder@acma.dev>"
    smtp_tls: str = "starttls"  # starttls | ssl | none
    # P07: URL pública de la app para los enlaces de correo y push.
    app_url_publica: str = "http://localhost:5173"
    # P07: enviar las notificaciones en la misma petición (pruebas / sin Celery) en lugar de encolarlas.
    notificaciones_envio_inline: bool = False

    @field_validator("acma_entorno")
    @classmethod
    def _entorno_valido(cls, v: str) -> str:
        if v not in {"desarrollo", "pruebas", "produccion"}:
            raise ValueError("ACMA_ENTORNO debe ser desarrollo, pruebas o produccion")
        return v

    @model_validator(mode="after")
    def _guardia_produccion(self) -> "Configuracion":
        if self.acma_entorno == "produccion":
            if not self.mfa_obligatorio:
                raise ValueError("En produccion MFA_OBLIGATORIO debe ser true")
            if "*" in self.cors_origenes:
                raise ValueError("CORS comodín no permitido en produccion")
            if not self.lista_cors:
                raise ValueError("CORS_ORIGENES debe listar el dominio del frontend en produccion")
            # §6.9.5: arrancar con un secreto de ejemplo equivale a no tener secreto. P11a.
            for campo in SECRETOS:
                valor = (getattr(self, campo) or "").lower()
                if valor and any(marca in valor for marca in MARCAS_DE_EJEMPLO):
                    raise ValueError(f"{campo.upper()} tiene un valor de ejemplo; genera uno real "
                                     f"(scripts/generar_secretos.py) antes de arrancar en produccion")
            if len(self.clave_cifrado) < 32 or self.clave_cifrado == CLAVE_CIFRADO_EJEMPLO:
                raise ValueError("CLAVE_CIFRADO debe ser una clave nueva de 32 bytes "
                                 "(scripts/generar_secretos.py), no la del .env.example")
            if self.almacenamiento_modo == "minio" and not (self.minio_root_user and self.minio_root_password):
                raise ValueError("MinIO en produccion exige MINIO_ROOT_USER y MINIO_ROOT_PASSWORD")
            if not self.app_url_publica.startswith("https://"):
                raise ValueError("APP_URL_PUBLICA debe ser https en produccion (las cookies de sesion son Secure)")
        return self

    @property
    def url_lectura(self) -> str:
        return self.database_read_url or self.database_url

    @property
    def lista_cors(self) -> list[str]:
        return [o.strip() for o in self.cors_origenes.split(",") if o.strip()]

    @property
    def es_produccion(self) -> bool:
        return self.acma_entorno == "produccion"


@lru_cache
def obtener_configuracion() -> Configuracion:
    return Configuracion()  # type: ignore[call-arg]


config = obtener_configuracion()
