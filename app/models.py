import secrets
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _gen_access_token() -> str:
    """Token URL-safe para autorizar lecturas de Order desde /thanks sin login."""
    return secrets.token_urlsafe(24)


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
    # Moliendas que el cliente puede pedir para este producto. Default 2:
    # grano-entero + molido (medio). Admin puede activar específicas:
    # espresso, v60, aeropress, prensa-francesa, moka.
    grind_options: Mapped[list[str]] = mapped_column(
        JSON, default=lambda: ["grano-entero", "molido"]
    )
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

    # Token (URL-safe) que autoriza lectura del detalle desde /thanks sin login.
    # Se entrega solo al cliente que creó la orden; corta enumeración por order_id.
    # Nullable porque las órdenes legacy creadas antes de esta migración no lo tienen.
    access_token: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True, default=_gen_access_token
    )

    # Asociación opcional con cuenta de cliente. Se hace upsert al crear la orden.
    # Nullable porque hay órdenes legacy sin Customer.
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True, index=True)

    customer_email: Mapped[str] = mapped_column(String(200), index=True)
    customer_name: Mapped[str] = mapped_column(String(200))
    customer_phone: Mapped[str] = mapped_column(String(40))
    customer_rut: Mapped[str] = mapped_column(String(20))

    shipping_method: Mapped[str] = mapped_column(String(20))
    # Modalidad Blue Express cuando shipping_method != 'pickup'. 'domicilio' o 'punto'.
    shipping_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
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

    mp_preference_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    mp_payment_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    mp_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    admin_notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    tracking_code: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Evidencia anti-chargeback: capturados al crear la orden. Útil para
    # disputas con MP/Banco ("este pedido llegó desde IP X con UA Y").
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Idempotencia: timestamps de side-effects que sólo deben ocurrir UNA vez
    # por orden, aunque el webhook MP/Khipu reintente. Si no es None, el
    # efecto ya se aplicó y no se repite.
    stock_decremented_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notification_created_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notification_paid_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

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
    # Molienda elegida por el cliente. Slug del set fijo definido en
    # schemas._GRIND_VALUES. Default 'grano-entero' para líneas legacy.
    grind: Mapped[str] = mapped_column(String(40), default="grano-entero")

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


class Customer(Base):
    """Cuenta de cliente (público). Se crea con upsert al confirmar una orden,
    o explícitamente desde /api/auth/request-link. Login = magic link al email.
    Todos los campos excepto email son opcionales (los completa el cliente)."""
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    rut: Mapped[str | None] = mapped_column(String(20), nullable=True)
    shipping_address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    shipping_comuna: Mapped[str | None] = mapped_column(String(120), nullable=True)
    shipping_region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    shipping_notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Preferencias de café: {"grind": "grano|molido", "roast": "filtrado|espresso",
    # "frequency_days": 30|60|90} — schema libre, el frontend lo valida.
    coffee_prefs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class CustomerLoginToken(Base):
    """Magic link de un solo uso para login de Customer. Mismo patrón que AdminLoginToken."""
    __tablename__ = "customer_login_tokens"

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


class SiteSettings(Base):
    """Configuración site-wide editable desde /admin. Tabla singleton: siempre
    una sola fila con id=1. Si no existe se crea con defaults al primer acceso."""
    __tablename__ = "site_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Envíos
    free_shipping_threshold_clp: Mapped[int] = mapped_column(Integer, default=50000)
    # Operativa / copy
    roast_day: Mapped[str] = mapped_column(String(40), default="viernes")
    ship_days: Mapped[str] = mapped_column(String(80), default="martes y viernes")
    # Suscripción
    subscription_discount_pct: Mapped[int] = mapped_column(Integer, default=10)
    # Si false, /suscripcion muestra "próximamente" + WhatsApp en vez del form,
    # y se oculta del header/footer. Útil mientras Webpay/Khipu no estén activos
    # para los cobros recurrentes.
    subscription_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Si false, /cuenta y /cuenta/login muestran "próximamente" y los JWT
    # viejos persistidos en localStorage no acceden al dashboard.
    customer_accounts_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Wholesale / HORECA
    wholesale_min_kg: Mapped[int] = mapped_column(Integer, default=5)
    wholesale_lead_msg: Mapped[str] = mapped_column(
        String(500),
        default="Cotización mayorista personalizada desde 5 kg. Filtrado o espresso a tu medida.",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ShippingRate(Base):
    """Tarifa Blue Express por talla + zona + modalidad. Editable desde /admin.
    Origen fijo: Rancagua. Talla derivada del peso total del pedido."""
    __tablename__ = "shipping_rates"

    id: Mapped[int] = mapped_column(primary_key=True)
    size_band: Mapped[str] = mapped_column(String(4), index=True)  # XS, S, M, L
    zone: Mapped[str] = mapped_column(String(20), index=True)  # ohiggins, centro_otros, extremo
    mode: Mapped[str] = mapped_column(String(20), index=True)  # domicilio, punto
    weight_min_g: Mapped[int] = mapped_column(Integer)  # inclusive
    weight_max_g: Mapped[int] = mapped_column(Integer)  # inclusive
    price_clp: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ComunaZone(Base):
    """Mapeo región / comuna → zona Blue Express desde Rancagua.
    Si una comuna no está, cae al match por región. Si tampoco, usa 'extremo'."""
    __tablename__ = "comuna_zones"

    id: Mapped[int] = mapped_column(primary_key=True)
    region: Mapped[str] = mapped_column(String(120), index=True)
    comuna: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    zone: Mapped[str] = mapped_column(String(20))  # ohiggins, centro_otros, extremo


class Comuna(Base):
    """Catálogo plano de comunas de Chile (relación padre-hijo: cada comuna pertenece
    a una región). Se siembra al startup desde seed/comunas-chile.json. Read-only
    desde el API público; el frontend la consume para selects anidados en el
    checkout. Las reglas de envío viven en [[ComunaZone]] aparte."""
    __tablename__ = "comunas"

    id: Mapped[int] = mapped_column(primary_key=True)
    region: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)


class Post(Base):
    """Post del blog. Migrado desde frontend/src/data/blog.ts a tabla
    persistente para edición desde /admin. La columna `cover` guarda la
    URL/path relativo a la imagen (ej. '/uploads/rwanda-natural.jpg').
    `body` es markdown."""
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    excerpt: Mapped[str] = mapped_column(String(500))
    meta_description: Mapped[str] = mapped_column(String(200), default="")
    cover: Mapped[str] = mapped_column(String(300), default="")
    published_at: Mapped[str] = mapped_column(String(20))  # YYYY-MM-DD
    reading_minutes: Mapped[int] = mapped_column(Integer, default=5)
    author: Mapped[str] = mapped_column(String(100), default="Equipo Tengu")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    body: Mapped[str] = mapped_column(String(50000))  # markdown
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class AbandonedCart(Base):
    """Carrito abandonado: snapshot de items + datos del cliente capturados
    cuando el usuario empieza a llenar el checkout pero no completa la orden.

    Disparado desde POST /api/cart-events cuando el frontend detecta email
    válido + items. Upsert por email (un solo carrito activo por cliente).

    Status:
    - open: carrito vivo, esperando recuperación
    - recovered: se concretó orden con ese email (set automático)
    - dismissed: admin lo marca como "no contactar" (cliente pidió no spam)
    """
    __tablename__ = "abandoned_carts"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    customer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    customer_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    items: Mapped[list[dict]] = mapped_column(JSON, default=list)
    subtotal_clp: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    recovered_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id"), nullable=True
    )
    admin_notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_reminder_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


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
