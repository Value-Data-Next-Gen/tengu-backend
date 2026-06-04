"""Fixtures de integración: app FastAPI completa con SQLite in-memory.

Mercado Pago se mockea por test (monkeypatch sobre app.services.mercadopago);
el resto del stack (kardex, cupones, lifecycle, emails en modo consola) corre
real.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import DiscountCode, Product, Variant
from app.services import rate_limit
from app.services.auth import require_admin


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # una sola conexión compartida: los overrides ven los mismos datos
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSession()

    def override_get_db():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: "test@admin"
    rate_limit.orders_create_limiter._calls.clear()
    rate_limit.orders_per_email_limiter._calls.clear()
    yield session
    session.close()
    app.dependency_overrides.clear()


@pytest.fixture()
def client(db):
    # Sin context manager: no corre el lifespan (seed + cron) a propósito.
    return TestClient(app)


@pytest.fixture()
def seed(db):
    """Producto café con 2 variantes + cupones de prueba."""
    p = Product(slug="test-blend", name="Test Blend", origin="Colombia", category="cafe")
    p.variants = [
        Variant(size_g=250, price_clp=10000, stock_qty=10),
        Variant(size_g=1000, price_clp=30000, stock_qty=3),
    ]
    mug = Product(slug="test-mug", name="Test Mug", origin="Chile", category="accesorios")
    mug.variants = [Variant(size_g=300, price_clp=8000, stock_qty=5)]
    coupons = [
        DiscountCode(code="DIEZ", kind="percent", value=10),
        DiscountCode(code="TODO", kind="percent", value=100),
        DiscountCode(code="SOLOCAFE", kind="percent", value=20, applies_to="category", applies_value="cafe"),
        DiscountCode(code="UNICO", kind="fixed", value=2000, max_uses=1),
    ]
    db.add_all([p, mug, *coupons])
    db.commit()
    return {"product": p, "mug": mug}


ORDER_PAYLOAD = {
    "customer_email": "cliente@test.cl",
    "customer_name": "Cliente Test",
    "customer_phone": "+56950013366",
    "customer_rut": "11111111-1",
    "shipping_method": "pickup",
    "payment_method": "mercadopago",
    "items": [{"product_slug": "test-blend", "size_g": 250, "quantity": 2, "grind": "grano-entero"}],
}


@pytest.fixture()
def order_payload():
    return {**ORDER_PAYLOAD, "items": [dict(i) for i in ORDER_PAYLOAD["items"]]}
