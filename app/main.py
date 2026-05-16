import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from .api import auth as auth_api
from .api import categories as categories_api
from .api import checkout as checkout_api
from .api import horeca as horeca_api
from .api import newsletter as newsletter_api
from .api import orders as orders_api
from .api import products as products_api
from .api import reviews as reviews_api
from .api import subscriptions as subscriptions_api
from .api.admin import router as admin_router
from .config import settings
from .db import Base, SessionLocal, engine
from .seed import UPLOADS_DIR, ensure_uploads_seeded, seed_products
from .services.subscriptions_cron import subscription_cron_loop


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_uploads_seeded()
    if settings.seed_on_startup:
        with SessionLocal() as db:
            seed_products(db)
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
app.include_router(admin_router)

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", CachedStaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
