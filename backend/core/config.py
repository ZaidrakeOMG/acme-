"""Configuración central leída de variables de entorno (.env en la raíz del repo)."""
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ_REPO = Path(__file__).resolve().parents[2]

# Campos que llevan secretos: en produccion ninguno puede quedarse con el valor de ejemplo del .env. P11a.
SECRETOS = ("jwt_secreto", "clave_cifrado", "minio_root_password", "smtp_password", "vapid_clave_privada",
            "database_url", "database_migrations_url", "redis_url", "celery_broker_url", "celery_result_backend",
            "whatsapp_token", "whatsapp_app_secret", "whatsapp_verify_token", "twilio_auth_token", "resend_api_key",
            "mailjet_api_key", "mailjet_secret_key")
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
    # La instalación Supabase usa el esquema privado acma; Docker original usa public.
    db_schema: str = "public"
    database_read_url: str = ""
    database_migrations_url: str = ""
    test_database_url: str = ""
    test_database_migrations_url: str = ""

    redis_url: str = "redis://localhost:6389/0"
    celery_broker_url: str = "redis://localhost:6389/1"
    celery_result_backend: str = "redis://localhost:6389/2"

    almacenamiento_modo: str = "minio"  # minio | memoria | supabase
    minio_endpoint: str = "localhost:9010"
    minio_root_user: str = ""
    minio_root_password: str = ""
    minio_bucket: str = "acma"
    minio_seguro: bool = False
    # Solo el backend usa la clave secreta: jamás se incluye en React/Flutter.
    supabase_url: str = ""
    supabase_secret_key: str = ""
    supabase_bucket: str = "acma"

    jwt_secreto: str = Field(min_length=32)
    jwt_algoritmo: str = "HS256"
    jwt_acceso_minutos: int = 15
    jwt_mfa_minutos: int = 5
    # Sesión persistente para web/PWA y WebView Flutter (iPhone/Android): el access JWT
    # dura 15 minutos; el refresh rotativo en cookie httpOnly conserva la sesión.
    # Vida absoluta máxima por dispositivo: 30 días (general) y 7 días (administradores).
    # No se permite que la rotación extienda estos topes; el cierre de sesión o revocación son inmediatos.
    sesion_dias: int = Field(default=30, ge=1, le=90)
    sesion_dias_admin: int = Field(default=7, ge=1, le=30)
    sesion_inactividad_dias: int = Field(default=30, ge=1, le=90)
    sesion_inactividad_dias_admin: int = Field(default=7, ge=1, le=30)
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
    # P11a: medido con 50 tecnicos + 20 de oficina. Por proceso: pool_size + overflow conexiones como maximo, asi que
    # workers x (db_pool_size + db_pool_overflow) debe caber en el max_connections de PostgreSQL.
    db_pool_size: int = 15
    db_pool_overflow: int = 10
    db_pool_timeout: int = 10
    # argon2 cuesta ~110 ms de CPU con 4 hilos cada vez. Sin tope, una tanda de inicios de sesion ocupa todos los
    # nucleos y deja sin aire al resto de la API; con tope, los logins se forman y lo demas sigue respondiendo. P11a.
    hash_concurrencia: int = 2
    # P11a: logs de una linea en JSON para produccion (la rotacion la hace Docker, no la aplicacion).
    log_json: bool = False

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
    # Resend por HTTPS: compatible con Railway Free/Trial/Hobby, donde SMTP está bloqueado.
    resend_api_key: str = ""
    resend_from: str = ""  # Remitente del dominio verificado (e.g. ACMA <no-reply@correo.ejemplo.com>)
    # "auto" conserva la prioridad original Resend > SMTP > stub.
    # "mailjet" se activa SOLO cuando el administrador lo selecciona en Railway.
    correo_proveedor: str = "auto"  # auto | resend | mailjet | smtp | stub
    mailjet_api_key: str = ""
    mailjet_secret_key: str = ""
    mailjet_from: str = ""  # Remitente individual validado: ACMA <usuario@proveedor.com>
    # P07: URL pública de la app para los enlaces de correo y push.
    app_url_publica: str = "http://localhost:5173"
    # P07: enviar las notificaciones en la misma petición (pruebas / sin Celery) en lugar de encolarlas.
    notificaciones_envio_inline: bool = False

    # F2-02: WhatsApp y SMS. Modo igual que SMTP: `stub` (nada sale de la máquina y el mensaje se guarda como
    # vista previa), `prueba` (cuentas gratuitas de Meta y Twilio, solo a números verificados en su panel) y
    # `real` (cuenta de pago). Las credenciales las carga la usuaria en `.env`; ver docs/operacion/mensajeria.md.
    whatsapp_modo: str = "stub"  # stub | prueba | real
    whatsapp_proveedor: str = "meta_cloud"  # meta_cloud | twilio (en modo prueba/real)
    whatsapp_token: str = ""
    whatsapp_numero_id: str = ""  # «Phone number ID» del panel de Meta
    whatsapp_verify_token: str = ""  # el que se escribe en el webhook de Meta
    whatsapp_app_secret: str = ""  # para validar la firma X-Hub-Signature-256
    whatsapp_api_url: str = "https://graph.facebook.com/v21.0"
    sms_modo: str = "stub"  # stub | prueba | real
    sms_proveedor: str = "twilio"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_remitente_sms: str = ""  # número o Messaging Service SID
    twilio_remitente_whatsapp: str = ""  # «whatsapp:+14155238886» en la cuenta de prueba
    twilio_api_url: str = "https://api.twilio.com/2010-04-01"
    # Ventana de 24 h de WhatsApp para mensajes de texto libre tras un mensaje del usuario (§6.1).
    mensajeria_ventana_libre_horas: int = 24
    mensajeria_max_por_minuto: int = 60  # límite de tasa por proveedor y por tenant

    @field_validator("correo_proveedor")
    @classmethod
    def _proveedor_correo_valido(cls, valor: str) -> str:
        valor = valor.strip().lower()
        if valor not in {"auto", "resend", "mailjet", "smtp", "stub"}:
            raise ValueError("CORREO_PROVEEDOR debe ser auto, resend, mailjet, smtp o stub")
        return valor

    @field_validator("db_schema")
    @classmethod
    def _esquema_valido(cls, valor: str) -> str:
        if valor not in {"public", "acma"}:
            raise ValueError("DB_SCHEMA debe ser public o acma")
        return valor

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
            if self.almacenamiento_modo == "supabase" and (not self.supabase_url.startswith("https://") or not self.supabase_secret_key or not self.supabase_bucket):
                raise ValueError("Storage Supabase requiere URL HTTPS, secret key y bucket privado")
            if not self.app_url_publica.startswith("https://"):
                raise ValueError("APP_URL_PUBLICA debe ser https en produccion (las cookies de sesion son Secure)")
        return self

    # F2-06: optimizacion de rutas. El solver corre en proceso donde OR-Tools carga (Linux, produccion) y, donde
    # no carga, en el contenedor `solver` (en Windows el Control de aplicaciones inteligente bloquea su binario).
    # "auto" prueba en proceso y cae al contenedor; "en_proceso" y "sidecar" lo fuerzan.
    rutas_motor_transporte: str = "auto"
    rutas_solver_url: str = "http://localhost:8099"
    # Sin llave, el proveedor `google_routes` devuelve el estimado y lo declara: nunca inventa un tiempo con trafico.
    google_routes_api_key: str = ""

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
