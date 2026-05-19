import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from sqlalchemy import inspect, text

from .api import auth as auth_api
from .api import categories as categories_api
from .api import checkout as checkout_api
from .api import horeca as horeca_api
from .api import newsletter as newsletter_api
from .api import orders as orders_api
from .api import products as products_api
from .api import reviews as reviews_api
from .api import site as site_api
from .api import subscriptions as subscriptions_api
from .api.admin import router as admin_router
from .config import assert_production_secrets, settings
from .db import Base, SessionLocal, engine
from .seed import UPLOADS_DIR, ensure_uploads_seeded, seed_products
from .services.shipping import ensure_seeded as ensure_shipping_seeded
from .services.subscriptions_cron import subscription_cron_loop


def _migrate_add_missing_columns() -> None:
    """Migraciones idempotentes para columnas agregadas a tablas existentes.
    Base.metadata.create_all() no hace ALTER, así que cada cambio aditivo va acá.
    """
    inspector = inspect(engine)
    if not inspector.has_table("orders"):
        return  # primera arrancada limpia: create_all() ya hizo todo
    existing = {c["name"] for c in inspector.get_columns("orders")}
    statements = []
    if "customer_id" not in existing:
        statements.append("ALTER TABLE orders ADD COLUMN customer_id INTEGER")
        statements.append(
            "CREATE INDEX IF NOT EXISTS ix_orders_customer_id ON orders(customer_id)"
        )
    if "shipping_mode" not in existing:
        statements.append("ALTER TABLE orders ADD COLUMN shipping_mode VARCHAR(20)")
    backfill_access_tokens = False
    if "access_token" not in existing:
        statements.append("ALTER TABLE orders ADD COLUMN access_token VARCHAR(64)")
        statements.append(
            "CREATE INDEX IF NOT EXISTS ix_orders_access_token ON orders(access_token)"
        )
        backfill_access_tokens = True
    if not statements:
        return
    with engine.begin() as conn:
        for sql in statements:
            conn.execute(text(sql))
    # Backfill: las órdenes legacy quedan con access_token=NULL al ALTER.
    # Las rellenamos para que /cuenta y /thanks funcionen consistente. El token
    # es un secreto razonable (el dueño es el único con el link).
    if backfill_access_tokens:
        from .models import Order, _gen_access_token
        with engine.begin() as conn:
            from sqlalchemy.orm import Session
            with Session(bind=conn) as db:
                legacy = db.query(Order).filter(Order.access_token.is_(None)).all()
                for o in legacy:
                    o.access_token = _gen_access_token()
                db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    assert_production_secrets()
    Base.metadata.create_all(bind=engine)
    _migrate_add_missing_columns()
    ensure_uploads_seeded()
    if settings.seed_on_startup:
        with SessionLocal() as db:
            seed_products(db)
            ensure_shipping_seeded(db)
    # Arranca el cron de suscripciones (no bloquea el startup)
    cron_task = asyncio.create_task(subscription_cron_loop())
    try:
        yield
    finally:
        cron_task.cancel()


app = FastAPI(title="Tengu Roastery API", version="0.3.0", lifespan=lifespan)

app.add_middleware(GZipMiddleware, minimum_size=512)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Cache agresivo en /uploads para que Netlify cachee al edge. El admin UI ya
# agrega ?v=timestamp al re-subir, así que el cliente forzar refresh cuando
# importa; el público lo ve estable durante 1 día.
class CachedStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=86400"
        return response


@app.get("/")
def root():
    return {"name": "Tengu Roastery API", "version": "0.3.0", "docs": "/docs"}


app.include_router(products_api.router)
app.include_router(categories_api.router)
app.include_router(newsletter_api.router)
app.include_router(orders_api.router)
app.include_router(checkout_api.router)
app.include_router(horeca_api.router)
app.include_router(subscriptions_api.router)
app.include_router(reviews_api.router)
app.include_router(auth_api.router)
app.include_router(site_api.router)
app.include_router(site_api.shipping_router)
app.include_router(admin_router)

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", CachedStaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
