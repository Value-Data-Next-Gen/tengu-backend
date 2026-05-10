from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import checkout as checkout_api
from .api import newsletter as newsletter_api
from .api import orders as orders_api
from .api import products as products_api
from .config import settings
from .db import Base, SessionLocal, engine
from .seed import seed_products


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    if settings.seed_on_startup:
        with SessionLocal() as db:
            seed_products(db)
    yield


app = FastAPI(title="Tengu Roastery API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"name": "Tengu Roastery API", "version": "0.1.0", "docs": "/docs"}


app.include_router(products_api.router)
app.include_router(newsletter_api.router)
app.include_router(orders_api.router)
app.include_router(checkout_api.router)
