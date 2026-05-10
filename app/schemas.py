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


class WebpayInitOut(BaseModel):
    token: str
    url: str


class KhipuInitOut(BaseModel):
    payment_id: str
    payment_url: str
    simplified_transfer_url: str | None = None
