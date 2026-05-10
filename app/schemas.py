from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class VariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    size_g: int
    price_clp: int


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    origin: str
    region: str | None
    variety: str | None
    process: str | None
    altitude_masl: str | None
    harvest: str | None
    roast_profile: str
    producer: str | None
    body: str | None
    acidity: str | None
    tasting_notes: list[str]
    image: str | None
    category: str
    featured: bool
    is_published: bool
    description: str | None = None
    variants: list[VariantOut]


# --- Orders ---


class OrderItemIn(BaseModel):
    product_slug: str
    size_g: int = Field(gt=0)
    quantity: int = Field(gt=0, le=99)


class OrderIn(BaseModel):
    customer_email: EmailStr
    customer_name: str = Field(min_length=2, max_length=200)
    customer_phone: str = Field(min_length=6, max_length=40)
    customer_rut: str = Field(min_length=8, max_length=20)
    shipping_method: Literal["rm", "regiones", "pickup"]
    shipping_address: str | None = None
    shipping_comuna: str | None = None
    shipping_region: str | None = None
    shipping_notes: str | None = None
    items: list[OrderItemIn] = Field(min_length=1)


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_slug: str
    product_name: str
    size_g: int
    unit_price_clp: int
    quantity: int
    subtotal_clp: int


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    customer_email: str
    customer_name: str
    customer_phone: str
    customer_rut: str
    shipping_method: str
    shipping_address: str | None
    shipping_comuna: str | None
    shipping_region: str | None
    shipping_notes: str | None
    shipping_cost_clp: int
    subtotal_clp: int
    total_clp: int
    payment_method: str | None
    webpay_authorization_code: str | None
    admin_notes: str | None
    tracking_code: str | None
    created_at: datetime
    paid_at: datetime | None
    shipped_at: datetime | None
    items: list[OrderItemOut]


# --- Checkout ---


class CheckoutInitIn(BaseModel):
    order_id: int


# --- Suscripciones ---


class SubscriptionIn(BaseModel):
    customer_email: EmailStr
    customer_name: str = Field(min_length=2, max_length=200)
    customer_phone: str = Field(min_length=6, max_length=40)
    customer_rut: str = Field(min_length=8, max_length=20)
    shipping_method: Literal["rm", "regiones", "pickup"]
    shipping_address: str | None = None
    shipping_comuna: str | None = None
    shipping_region: str | None = None
    shipping_notes: str | None = None
    frequency_days: Literal[30, 60, 90]
    product_slug: str | None = None  # None si is_surprise=True
    size_g: int = Field(gt=0)
    is_surprise: bool = False


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    customer_email: str
    customer_name: str
    frequency_days: int
    product_slug: str | None
    size_g: int
    is_surprise: bool
    discount_pct: int
    is_active: bool
    next_charge_at: datetime | None
    last_charge_at: datetime | None
    orders_count: int
    first_order_id: int | None
    created_at: datetime


class SubscriptionCreateOut(BaseModel):
    subscription: SubscriptionOut
    order: OrderOut


# --- Reseñas ---


class ReviewIn(BaseModel):
    product_slug: str
    customer_name: str = Field(min_length=2, max_length=120)
    customer_email: EmailStr
    rating: int = Field(ge=1, le=5)
    title: str | None = Field(default=None, max_length=200)
    body: str = Field(min_length=10, max_length=2000)


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_slug: str
    customer_name: str
    rating: int
    title: str | None
    body: str
    created_at: datetime


class ReviewAdminOut(ReviewOut):
    customer_email: str
    status: str
    admin_notes: str | None
    approved_at: datetime | None


class ReviewSummary(BaseModel):
    count: int
    average: float


# --- Categorías ---


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str | None
    is_visible: bool
    sort_order: int


class CategoryWithCount(CategoryOut):
    product_count: int = 0


class CategoryIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    is_visible: bool = True
    sort_order: int = 100


class CategoryPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    description: str | None = None
    is_visible: bool | None = None
    sort_order: int | None = None


# --- Admin: CRUD productos ---


class VariantIn(BaseModel):
    size_g: int = Field(gt=0)
    price_clp: int = Field(ge=0)
    stock_qty: int = Field(ge=0, default=50)


class ProductIn(BaseModel):
    slug: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=2, max_length=200)
    # Para no-café (mug, equipo) puede ser una marca o país. Required para evitar ambigüedad.
    origin: str = Field(min_length=2, max_length=60)
    region: str | None = Field(default=None, max_length=200)
    variety: str | None = Field(default=None, max_length=120)
    process: str | None = Field(default=None, max_length=80)
    altitude_masl: str | None = Field(default=None, max_length=40)
    harvest: str | None = Field(default=None, max_length=60)
    # Para café: 'Filtrado' o 'Espresso'. Para no-café: vacío o 'N/A'.
    roast_profile: str = Field(default="", max_length=40)
    producer: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, max_length=120)
    acidity: str | None = Field(default=None, max_length=120)
    tasting_notes: list[str] = Field(default_factory=list)
    category: str = Field(min_length=2, max_length=40)
    featured: bool = False
    is_published: bool = True
    description: str | None = Field(default=None, max_length=2000)
    variants: list[VariantIn] = Field(min_length=1)


class ProductPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    origin: str | None = Field(default=None, min_length=2, max_length=60)
    region: str | None = None
    variety: str | None = None
    process: str | None = None
    altitude_masl: str | None = None
    harvest: str | None = None
    roast_profile: str | None = None
    producer: str | None = None
    body: str | None = None
    acidity: str | None = None
    tasting_notes: list[str] | None = None
    category: str | None = None
    featured: bool | None = None
    is_published: bool | None = None
    description: str | None = None


class WebpayInitOut(BaseModel):
    token: str
    url: str


class KhipuInitOut(BaseModel):
    payment_id: str
    payment_url: str
    simplified_transfer_url: str | None = None
