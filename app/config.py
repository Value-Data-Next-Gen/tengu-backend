from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./data/tengu.db"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    seed_on_startup: bool = True

    # Frontend URL — backend redirects here after Webpay return.
    frontend_url: str = "http://localhost:5173"

    # Webpay Plus return URL — Transbank POSTs here after payment.
    webpay_return_url: str = "http://localhost:8000/api/checkout/webpay/return"

    # Shipping costs (CLP).
    shipping_rm_clp: int = 3500
    shipping_regiones_clp: int = 5500
    shipping_pickup_clp: int = 0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
