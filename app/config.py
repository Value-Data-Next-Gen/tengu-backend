import logging
import os
import secrets

from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_ADMIN_PASSWORD = "tengu123"  # solo válido en localhost dev


class Settings(BaseSettings):
    database_url: str = "sqlite:///./data/tengu.db"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    seed_on_startup: bool = True
    # En Azure App Service apuntar a /home/uploads para que persista entre deploys
    # (en dev queda relativo a backend/, gitignored).
    uploads_dir: str = ""

    # Google OAuth — Client ID (web app) usado para verificar ID tokens en /api/auth/google.
    # Vacío = endpoint devuelve 503.
    google_client_id: str = ""

    # Frontend URL — backend redirects here after Webpay return + magic link.
    frontend_url: str = "http://localhost:5173"

    # Webpay Plus return URL — Transbank POSTs here after payment.
    webpay_return_url: str = "http://localhost:8000/api/checkout/webpay/return"

    # --- Webpay credentials ---
    webpay_environment: str = "test"
    webpay_commerce_code: str = ""
    webpay_api_key: str = ""

    # --- Khipu credentials ---
    # Configurar tras crear cuenta en https://khipu.com (registro gratuito).
    # En el panel "Cobrar > Tu información" obtienes receiver_id + secret/api key.
    khipu_receiver_id: str = ""
    khipu_api_key: str = ""
    khipu_api_base: str = "https://payment-api.khipu.com/v3"

    # --- Mercado Pago credentials (Checkout Pro) ---
    # Sacar en https://www.mercadopago.cl/developers/panel/app → Credenciales.
    # 4 valores: Access Token + Public Key, en sandbox y producción.
    # En sandbox los tokens empiezan con TEST-..., en prod con APP_USR-...
    # mp_environment="test" → usa mp_tk_test (y devuelve sandbox_init_point).
    # mp_environment="live" → usa mp_tk_prod (y devuelve init_point).
    mp_tk_test: str = ""
    mp_pk_test: str = ""
    mp_tk_prod: str = ""
    mp_pk_prod: str = ""
    mp_environment: str = "test"
    # "Clave secreta" del webhook (panel MP → Webhooks → Configurar firma).
    # Se usa para validar el header x-signature en /mercadopago/notify.
    # Si queda vacía, se acepta cualquier request (modo dev/pre-config).
    mp_cs_wbhk: str = ""

    # Shipping costs (CLP).
    shipping_rm_clp: int = 3500
    shipping_regiones_clp: int = 5500
    shipping_pickup_clp: int = 0

    # --- Admin & auth ---
    admin_emails: str = "g.rojaschacon@gmail.com"
    # Password compartido para los admins listados en admin_emails.
    # IMPORTANTE: cambiar en producción vía env var ADMIN_PASSWORD.
    admin_password: str = DEFAULT_ADMIN_PASSWORD
    jwt_secret: str = secrets.token_urlsafe(32)  # override in .env for stable sessions
    jwt_algorithm: str = "HS256"
    magic_link_ttl_minutes: int = 15  # legacy, no usado en password auth
    session_ttl_hours: int = 72

    # --- Email (SMTP) ---
    # Pon SMTP_HOST=__console__ en dev: imprime el magic link en la consola
    # en lugar de enviar por SMTP. En prod usa Brevo, Resend o tu SMTP real.
    smtp_host: str = "__console__"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "Tengu Roastery <hola@tenguroastery.cl>"
    smtp_use_tls: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def admin_emails_list(self) -> list[str]:
        return [e.strip().lower() for e in self.admin_emails.split(",") if e.strip()]

    @property
    def mp_access_token(self) -> str:
        return self.mp_tk_prod if self.mp_environment.lower() == "live" else self.mp_tk_test

    @property
    def mp_public_key(self) -> str:
        return self.mp_pk_prod if self.mp_environment.lower() == "live" else self.mp_pk_test


settings = Settings()


def _is_production() -> bool:
    """Detecta Azure App Service (que setea WEBSITE_SITE_NAME automáticamente)
    o ENVIRONMENT=production explícito. Tunnel/cloudflare locales no cuentan."""
    if os.environ.get("ENVIRONMENT", "").lower() == "production":
        return True
    if os.environ.get("WEBSITE_SITE_NAME"):  # Azure App Service
        return True
    return False


def assert_production_secrets() -> None:
    """Llamada al startup. En producción (Azure App Service o ENVIRONMENT=production)
    abortamos si los secretos siguen en sus defaults. En dev se permite seguir
    con tengu123 + jwt_secret aleatorio.

    Escape hatch para casos raros: TENGU_ALLOW_DEFAULT_SECRETS=1.
    """
    if os.environ.get("TENGU_ALLOW_DEFAULT_SECRETS") == "1":
        return
    if not _is_production():
        return
    if settings.admin_password == DEFAULT_ADMIN_PASSWORD:
        raise RuntimeError(
            "ADMIN_PASSWORD no configurado en producción — "
            "setea la env var ADMIN_PASSWORD antes de iniciar el backend."
        )
    if not os.environ.get("JWT_SECRET"):
        # jwt_secret tiene default random por proceso; si no está en env,
        # cada restart invalida todas las sesiones admin.
        raise RuntimeError(
            "JWT_SECRET no configurado en producción — "
            "setea la env var JWT_SECRET (string aleatorio largo) para que las sesiones persistan."
        )
    if not settings.frontend_url.startswith("https://"):
        # En prod los magic links + redirects de pago necesitan dominio HTTPS real.
        raise RuntimeError(
            f"FRONTEND_URL debe ser un URL https:// en producción. Valor actual: {settings.frontend_url!r}"
        )
    # Los siguientes dos NO abortan el arranque (no queremos tumbar prod si aún
    # falta configurarlos), pero quedan como WARNING ruidoso en logs hasta que
    # se resuelvan. Son deuda de seguridad/operación conocida.
    if settings.mp_environment.lower() == "live" and not settings.mp_cs_wbhk:
        # Sin la clave secreta del webhook, /mercadopago/notify acepta cualquier
        # POST (modo permisivo). Con MP en vivo eso es falsificable: alguien con
        # un payment_id aprobado real podría degradar/forzar órdenes.
        logging.getLogger(__name__).warning(
            "SEGURIDAD: MP_CS_WBHK vacío con MP_ENVIRONMENT=live — el webhook de "
            "Mercado Pago acepta cualquier POST (falsificable). Configura la clave "
            "secreta del webhook (panel MP → Webhooks → Configurar firma)."
        )
    if settings.smtp_host in ("", "__console__"):
        # En prod sin SMTP real los emails de orden creada / pago confirmado /
        # aviso al admin se imprimen en consola pero nunca se envían.
        logging.getLogger(__name__).warning(
            "OPERACIÓN: SMTP_HOST sigue en %r en producción — los emails "
            "transaccionales NO se envían. Configura un SMTP real (Resend, Brevo, "
            "etc.) vía las env vars SMTP_*.",
            settings.smtp_host,
        )
    if not settings.uploads_dir.startswith("/home/"):
        # En Azure App Service /home es la única zona persistente. Sin esto,
        # las imágenes subidas desde /admin se pierden en cada redeploy.
        # Caso típico: Git Bash en Windows convierte "/home/uploads" a
        # "C:/Program Files/Git/home/uploads" al ejecutar `az ... --settings`.
        # Si pasa, usa `MSYS_NO_PATHCONV=1 az ...` o setealo desde el Portal.
        raise RuntimeError(
            "UPLOADS_DIR debe ser un path absoluto bajo /home/ para sobrevivir "
            "los redeploys de Azure App Service. "
            f"Valor actual: {settings.uploads_dir!r}. "
            "Setea UPLOADS_DIR=/home/uploads desde Azure Portal "
            "(Configuration → Application settings)."
        )
