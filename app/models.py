from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    origin: Mapped[str] = mapped_column(String(60))
    region: Mapped[str | None] = mapped_column(String(200), nullable=True)
    variety: Mapped[str | None] = mapped_column(String(120), nullable=True)
    process: Mapped[str | None] = mapped_column(String(80), nullable=True)
    altitude_masl: Mapped[str | None] = mapped_column(String(40), nullable=True)
    harvest: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # Para no-café (mug, equipo), puede ser vacío o "N/A". Para café usar Filtrado / Espresso.
    roast_profile: Mapped[str] = mapped_column(String(40), default="")
    producer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    body: Mapped[str | None] = mapped_column(String(120), nullable=True)
    acidity: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tasting_notes: Mapped[list[str]] = mapped_column(JSON, default=list)
    image: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category: Mapped[str] = mapped_column(String(40), index=True)
    featured: Mapped[bool] = mapped_column(Boolean, default=False)
    # Si is_published=False, no aparece en /api/products (público) pero sí en /api/admin/products
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    # Descripción opcional para productos no-café (mugs, equipo, etc.)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    variants: Mapped[list["Variant"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="Variant.size_g",
    )


class Category(Base):
    """Categoría de producto. Si is_visible=False, todos los productos
    de esa categoría se ocultan de la tienda pública sin tener que
    despublicarlos uno por uno."""
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class Variant(Base):
    __tablename__ = "variants"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    size_g: Mapped[int] = mapped_column(Integer)
    price_clp: Mapped[int] = mapped_column(Integer)
    stock_qty: Mapped[int] = mapped_column(Integer, default=50)

    product: Mapped[Product] = relationship(back_populates="variants")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class OrderStatus(str, Enum):
    pending = "pending"
    paid = "paid"
    shipped = "shipped"
    delivered = "delivered"
    failed = "failed"
    canceled = "canceled"


class ShippingMethod(str, Enum):
    rm = "rm"
    regiones = "regiones"
    pickup = "pickup"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default=OrderStatus.pending.value, index=True)

    customer_email: Mapped[str] = mapped_column(String(200), index=True)
    customer_name: Mapped[str] = mapped_column(String(200))
    customer_phone: Mapped[str] = mapped_column(String(40))
    customer_rut: Mapped[str] = mapped_column(String(20))

    shipping_method: Mapped[str] = mapped_column(String(20))
    shipping_address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    shipping_comuna: Mapped[str | None] = mapped_column(String(120), nullable=True)
    shipping_region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    shipping_notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    shipping_cost_clp: Mapped[int] = mapped_column(Integer, default=0)

    subtotal_clp: Mapped[int] = mapped_column(Integer)
    total_clp: Mapped[int] = mapped_column(Integer)

    payment_method: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)

    webpay_buy_order: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    webpay_token: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    webpay_authorization_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    webpay_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    khipu_payment_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    khipu_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    admin_notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    tracking_code: Mapped[str | None] = mapped_column(String(120), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    product_slug: Mapped[str] = mapped_column(String(120))
    product_name: Mapped[str] = mapped_column(String(200))
    size_g: Mapped[int] = mapped_column(Integer)
    unit_price_clp: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    subtotal_clp: Mapped[int] = mapped_column(Integer)

    order: Mapped[Order] = relationship(back_populates="items")


class AdminLoginToken(Base):
    __tablename__ = "admin_login_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), index=True)
    token: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class CoffeeSubscription(Base):
    """Suscripción recurrente de café.

    'Light': el primer pago va por Webpay/Khipu igual que un pedido normal.
    Las reposiciones futuras las gatilla un admin desde /admin (o un cron
    futuro) y crean una nueva Order linkeada.
    """
    __tablename__ = "coffee_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Customer
    customer_email: Mapped[str] = mapped_column(String(200), index=True)
    customer_name: Mapped[str] = mapped_column(String(200))
    customer_phone: Mapped[str] = mapped_column(String(40))
    customer_rut: Mapped[str] = mapped_column(String(20))

    # Shipping
    shipping_method: Mapped[str] = mapped_column(String(20))
    shipping_address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    shipping_comuna: Mapped[str | None] = mapped_column(String(120), nullable=True)
    shipping_region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    shipping_notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Plan
    frequency_days: Mapped[int] = mapped_column(Integer)  # 30, 60, 90
    product_slug: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size_g: Mapped[int] = mapped_column(Integer)
    is_surprise: Mapped[bool] = mapped_column(Boolean, default=False)
    discount_pct: Mapped[int] = mapped_column(Integer, default=10)

    # State
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_charge_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_charge_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # Stats
    orders_count: Mapped[int] = mapped_column(Integer, default=0)
    first_order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)

    admin_notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_slug: Mapped[str] = mapped_column(String(120), index=True)
    customer_name: Mapped[str] = mapped_column(String(120))
    customer_email: Mapped[str] = mapped_column(String(200), index=True)
    rating: Mapped[int] = mapped_column(Integer)  # 1-5
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    body: Mapped[str] = mapped_column(String(2000))
    # Moderación: pending hasta que admin lo apruebe.
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # 'pending' | 'approved' | 'rejected'
    admin_notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Link opcional a una orden real (si el reviewer compró)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class HorecaLead(Base):
    __tablename__ = "horeca_leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    company: Mapped[str] = mapped_column(String(200))
    contact_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(200), index=True)
    phone: Mapped[str] = mapped_column(String(40))
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    business_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    kg_per_month: Mapped[str | None] = mapped_column(String(40), nullable=True)
    machine_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    contacted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
