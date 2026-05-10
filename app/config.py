import secrets

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./data/tengu.db"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    seed_on_startup: bool = True

    # Frontend URL — backend redirects here after Webpay return + magic link.
    frontend_url: str = "http://localhost:5173"

    # Webpay Plus return URL — Transbank POSTs here after payment.
    webpay_return_url: str = "http://localhost:8000/api/checkout/webpay/return"

    # Shipping costs (CLP).
    shipping_rm_clp: int = 3500
    shipping_regiones_clp: int = 5500
    shipping_pickup_clp: int = 0

    # --- Admin & auth ---
    admin_emails: str = "g.rojaschacon@gmail.com"
    jwt_secret: str = secrets.token_urlsafe(32)  # override in .env for stable sessions
    jwt_algorithm: str = "HS256"
    magic_link_ttl_minutes: int = 15
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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def admin_emails_list(self) -> list[str]:
        return [e.strip().lower() for e in self.admin_emails.split(",") if e.strip()]


settings = Settings()
