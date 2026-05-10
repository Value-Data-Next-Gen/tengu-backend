from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import checkout as checkout_api
from .api import horeca as horeca_api
from .api import newsletter as newsletter_api
from .api import orders as orders_api
from .api import products as products_api
from .api.admin import router as admin_router
from .config import settings
from .db import Base, SessionLocal, engine
from .seed import UPLOADS_DIR, ensure_uploads_seeded, seed_products


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_uploads_seeded()
    if settings.seed_on_startup:
        with SessionLocal() as db:
            seed_products(db)
    yield


app = FastAPI(title="Tengu Roastery API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"name": "Tengu Roastery API", "version": "0.2.0", "docs": "/docs"}


app.include_router(products_api.router)
app.include_router(newsletter_api.router)
app.include_router(orders_api.router)
app.include_router(checkout_api.router)
app.include_router(horeca_api.router)
app.include_router(admin_router)

# Serve uploaded product images at /uploads/<filename>
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
