import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


# Dominios de email desechables conocidos. Lista corta de los más usados
# para spam/throwaway; no pretende ser exhaustiva, solo subir la fricción.
# Si crece, mover a un set externo (txt/JSON) cargado al startup.
_DISPOSABLE_DOMAINS = frozenset({
    "mailinator.com", "guerrillamail.com", "guerrillamail.net", "10minutemail.com",
    "10minutemail.net", "tempmail.com", "temp-mail.org", "throwawaymail.com",
    "yopmail.com", "trashmail.com", "sharklasers.com", "getnada.com", "nada.email",
    "fakeinbox.com", "fake-mail.net", "maildrop.cc", "dispostable.com",
    "mintemail.com", "mt2015.com", "tempinbox.com", "emailondeck.com",
    "spamgourmet.com", "mohmal.com", "tempemail.net", "burnermail.io",
    "33mail.com", "anonbox.net", "mailcatch.com", "spambox.us",
    "spam4.me", "0wnd.net", "tmpmail.org", "trbvm.com", "mvrht.com",
})

_RUT_CLEANUP = re.compile(r"[.\s]")

# Moliendas disponibles. Slug interno → label visible (frontend lo replica).
GRIND_VALUES = (
    "grano-entero",
    "molido",
    "espresso",
    "v60",
    "aeropress",
    "prensa-francesa",
    "moka",
)
_GRIND_SET = set(GRIND_VALUES)

# Teléfono chileno: acepta variaciones comunes que tipea un usuario real:
#   +56 9 1234 5678 / +56912345678 / 56912345678 / 9 1234 5678 / 91234567
#   Normaliza a '+56 9 XXXX XXXX'. Rechaza fijos (Blue Express necesita móvil).
_PHONE_DIGITS = re.compile(r"\D+")


def _validate_chilean_phone(value: str) -> str:
    digits = _PHONE_DIGITS.sub("", value or "")
    # Quitar prefijo país si vino
    if digits.startswith("56"):
        digits = digits[2:]
    if digits.startswith("0"):
        digits = digits[1:]
    # Móvil chileno: 9 + 8 dígitos = 9 dígitos total
    if len(digits) != 9 or not digits.startswith("9"):
        raise ValueError(
            "Teléfono inválido. Usá formato móvil chileno: +56 9 XXXX XXXX"
        )
    return f"+56 9 {digits[1:5]} {digits[5:]}"


def _validate_chilean_rut(value: str) -> str:
    """Valida y normaliza un RUT chileno. Acepta '12.345.678-K', '12345678-k',
    '12345678K'; devuelve '12345678-K' (uppercase, sin puntos, con guion).
    Rechaza con ValueError si el dígito verificador no coincide."""
    clean = _RUT_CLEANUP.sub("", value).upper()
    if "-" in clean:
        body, dv = clean.split("-", 1)
    else:
        body, dv = clean[:-1], clean[-1]
    if not body.isdigit() or len(body) < 7 or len(body) > 9 or len(dv) != 1:
        raise ValueError("Formato de RUT inválido")
    # Módulo 11
    total, mult = 0, 2
    for ch in reversed(body):
        total += int(ch) * mult
        mult = 2 if mult == 7 else mult + 1
    rem = 11 - (total % 11)
    expected = "0" if rem == 11 else "K" if rem == 10 else str(rem)
    if dv != expected:
        raise ValueError("Dígito verificador del RUT no coincide")
    return f"{body}-{dv}"


class VariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    size_g: int
    price_clp: int
    # Stock expuesto SOLO cuando es bajo (configurable en site_settings.low_stock_threshold).
    # Si stock es alto, devolvemos None — evita que competidores scrapen niveles.
    # Si es 0, devolvemos 0 explícito (out of stock).
    stock_low: int | None = None
    # Precio "antes" para mostrar tachado en oferta. None = sin oferta.
    compare_at_price_clp: int | None = None


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
    grind_options: list[str] = Field(default_factory=lambda: ["grano-entero", "molido"])


# --- Orders ---


class OrderItemIn(BaseModel):
    product_slug: str
    size_g: int = Field(gt=0)
    quantity: int = Field(gt=0, le=99)
    grind: str = Field(default="grano-entero", max_length=40)

    @field_validator("grind")
    @classmethod
    def _grind_valid(cls, v: str) -> str:
        if v not in _GRIND_SET:
            raise ValueError(f"Molienda inválida: {v}")
        return v


class OrderIn(BaseModel):
    customer_email: EmailStr
    customer_name: str = Field(min_length=2, max_length=200)
    customer_phone: str = Field(min_length=6, max_length=40)
    customer_rut: str = Field(min_length=8, max_length=20)
    shipping_method: Literal["rm", "regiones", "pickup"]
    # 'domicilio' o 'punto' Blue Express. Solo cuando shipping_method != 'pickup'.
    shipping_mode: Literal["domicilio", "punto"] | None = None
    shipping_address: str | None = Field(default=None, max_length=300)
    shipping_comuna: str | None = Field(default=None, max_length=120)
    shipping_region: str | None = Field(default=None, max_length=120)
    shipping_notes: str | None = Field(default=None, max_length=500)
    # Honeypot: campo invisible en el form (display:none). Humanos lo dejan
    # vacío; bots que llenan todos los inputs lo completan y se autobannean.
    # Nombre genérico tipo "website" para que el bot no lo detecte.
    website: str | None = Field(default=None, max_length=200, exclude=True)

    @field_validator("customer_rut")
    @classmethod
    def _rut_valid(cls, v: str) -> str:
        return _validate_chilean_rut(v)

    @field_validator("customer_email")
    @classmethod
    def _email_no_disposable(cls, v: str) -> str:
        domain = v.split("@", 1)[1].lower() if "@" in v else ""
        if domain in _DISPOSABLE_DOMAINS:
            raise ValueError("No aceptamos emails desechables. Usá tu correo real.")
        return v

    @field_validator("website")
    @classmethod
    def _website_must_be_empty(cls, v: str | None) -> str | None:
        # Si llegó algo en este campo, es un bot.
        if v:
            raise ValueError("Solicitud rechazada.")
        return v

    @field_validator("customer_phone")
    @classmethod
    def _phone_valid(cls, v: str) -> str:
        return _validate_chilean_phone(v)
    # 'bank_transfer' = BanchilePagos manual (queda pending hasta confirmación).
    # 'webpay'/'khipu' se setea desde /api/checkout/*/init.
    payment_method: Literal["bank_transfer", "webpay", "khipu", "mercadopago"] | None = None
    items: list[OrderItemIn] = Field(min_length=1, max_length=20)
    coupon_code: str | None = Field(default=None, max_length=40)


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_slug: str
    product_name: str
    size_g: int
    unit_price_clp: int
    quantity: int
    subtotal_clp: int
    grind: str = "grano-entero"


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
    coupon_code: str | None = None
    discount_clp: int = 0


class OrderCreatedOut(OrderOut):
    """Variante de OrderOut que incluye el access_token. Se devuelve al
    crear una orden (POST /api/orders) y al listar las del cliente logueado
    (/api/auth/me/orders). Nullable porque hay órdenes legacy creadas antes
    de que la columna existiera — el frontend muestra esas como no-linkables."""
    access_token: str | None = None


# --- Checkout ---


class CheckoutInitIn(BaseModel):
    order_id: int


class CouponValidateItemIn(BaseModel):
    product_slug: str
    category: str | None = None
    subtotal_clp: int = Field(ge=0)


class CouponValidateIn(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    subtotal_clp: int = Field(ge=0)
    items: list[CouponValidateItemIn] = Field(default_factory=list, max_length=20)


class CouponValidateOut(BaseModel):
    valid: bool
    code: str
    discount_clp: int = 0
    kind: str | None = None  # 'percent' | 'fixed'
    value: int | None = None
    message: str | None = None  # explicación cuando valid=False
    description: str | None = None  # cuando valid=True, mensaje "público" del cupón


# --- Suscripciones ---


class SubscriptionIn(BaseModel):
    customer_email: EmailStr
    customer_name: str = Field(min_length=2, max_length=200)
    customer_phone: str = Field(min_length=6, max_length=40)
    customer_rut: str = Field(min_length=8, max_length=20)
    shipping_method: Literal["rm", "regiones", "pickup"]
    shipping_address: str | None = Field(default=None, max_length=300)
    shipping_comuna: str | None = Field(default=None, max_length=120)
    shipping_region: str | None = Field(default=None, max_length=120)
    shipping_notes: str | None = Field(default=None, max_length=500)
    # 45 = "cada 6 semanas" (opción real del frontend).
    frequency_days: Literal[30, 45, 60, 90]
    product_slug: str | None = None  # None si is_surprise=True
    size_g: int = Field(gt=0)
    is_surprise: bool = False

    @field_validator("customer_rut")
    @classmethod
    def _rut_valid(cls, v: str) -> str:
        return _validate_chilean_rut(v)

    @field_validator("customer_phone")
    @classmethod
    def _phone_valid(cls, v: str) -> str:
        return _validate_chilean_phone(v)


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
    admin_notes: str | None = None
    cancel_reason: str | None = None
    canceled_at: datetime | None = None
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
    price_clp: int = Field(gt=0)  # no aceptamos café gratis
    stock_qty: int = Field(ge=0, default=50)
    compare_at_price_clp: int | None = Field(default=None, gt=0)


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
    grind_options: list[str] = Field(
        default_factory=lambda: ["grano-entero", "molido"]
    )

    @field_validator("grind_options")
    @classmethod
    def _grind_options_valid(cls, v: list[str]) -> list[str]:
        if not v:
            return ["grano-entero", "molido"]
        bad = [g for g in v if g not in _GRIND_SET]
        if bad:
            raise ValueError(f"Moliendas inválidas: {bad}")
        return v


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
    grind_options: list[str] | None = None

    @field_validator("grind_options")
    @classmethod
    def _patch_grind_options(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        if not v:
            return ["grano-entero", "molido"]
        bad = [g for g in v if g not in _GRIND_SET]
        if bad:
            raise ValueError(f"Moliendas inválidas: {bad}")
        return v


# --- Hero carousel (home) ---


class HeroSlideOut(BaseModel):
    """Forma pública: solo lo que el carrusel necesita renderizar."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    image: str
    eyebrow: str
    title: str
    subtitle: str
    cta_label: str
    cta_url: str
    image_has_text: bool = False


class HeroSlideAdminOut(HeroSlideOut):
    sort_order: int
    is_active: bool
    starts_at: datetime | None
    ends_at: datetime | None
    created_at: datetime
    updated_at: datetime


class HeroSlideIn(BaseModel):
    image: str = Field(min_length=1, max_length=300)
    eyebrow: str = Field(default="", max_length=80)
    title: str = Field(default="", max_length=160)
    subtitle: str = Field(default="", max_length=400)
    cta_label: str = Field(default="", max_length=60)
    cta_url: str = Field(default="", max_length=300)
    image_has_text: bool = False
    sort_order: int = Field(default=100, ge=0, le=10000)
    is_active: bool = True
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class HeroSlidePatch(BaseModel):
    image: str | None = Field(default=None, min_length=1, max_length=300)
    eyebrow: str | None = Field(default=None, max_length=80)
    title: str | None = Field(default=None, max_length=160)
    subtitle: str | None = Field(default=None, max_length=400)
    cta_label: str | None = Field(default=None, max_length=60)
    cta_url: str | None = Field(default=None, max_length=300)
    image_has_text: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10000)
    is_active: bool | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None


# --- Kardex / inventario (admin) ---


class StockMovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    variant_id: int | None
    product_slug: str
    size_g: int
    delta: int
    reason: str
    balance_after: int
    order_id: int | None
    note: str | None
    created_by: str
    created_at: datetime


class RestockIn(BaseModel):
    """Ingreso manual de inventario (+qty)."""
    qty: int = Field(gt=0, le=1_000_000)
    note: str | None = Field(default=None, max_length=300)


class StockAdjustIn(BaseModel):
    """Ajuste del stock a un valor absoluto (merma, corrección de conteo)."""
    stock_qty: int = Field(ge=0, le=1_000_000)
    note: str | None = Field(default=None, max_length=300)


# --- Customer / Auth (público) ---


class AuthRequestLinkIn(BaseModel):
    email: EmailStr


class AuthGoogleIn(BaseModel):
    id_token: str = Field(min_length=10)


class AuthVerifyOut(BaseModel):
    jwt: str
    email: str


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str | None
    phone: str | None
    rut: str | None
    shipping_address: str | None
    shipping_comuna: str | None
    shipping_region: str | None
    shipping_notes: str | None
    coffee_prefs: dict | None
    created_at: datetime


class CustomerPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    rut: str | None = Field(default=None, max_length=20)
    shipping_address: str | None = Field(default=None, max_length=300)
    shipping_comuna: str | None = Field(default=None, max_length=120)
    shipping_region: str | None = Field(default=None, max_length=120)
    shipping_notes: str | None = Field(default=None, max_length=500)
    coffee_prefs: dict | None = None


# --- Site settings + shipping (admin-config) ---


class SiteSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    free_shipping_threshold_clp: int
    roast_day: str
    ship_days: str
    subscription_discount_pct: int
    subscription_enabled: bool = True
    customer_accounts_enabled: bool = False
    wholesale_min_kg: int
    wholesale_lead_msg: str
    low_stock_threshold: int = 10
    # Announcement bar superior
    announcement_enabled: bool = False
    announcement_text: str = ""
    announcement_link_url: str | None = None
    announcement_link_label: str | None = None
    announcement_bg_color: str = "#E63946"
    announcement_text_color: str = "#F5F1EA"
    announcement_expires_at: str | None = None
    # Promo popup
    promo_enabled: bool = False
    promo_trigger: str = "exit"
    promo_delay_seconds: int = 10
    promo_show_countdown: bool = False
    promo_badge: str = "OFERTA DEL MES"
    promo_title: str = ""
    promo_subtitle: str = ""
    promo_body: str = ""
    promo_cta_label: str = "Ver oferta"
    promo_cta_url: str = "/tienda"
    promo_image: str | None = None
    promo_expires_at: str | None = None
    promo_dismiss_days: int = 7


class SiteSettingsPatch(BaseModel):
    free_shipping_threshold_clp: int | None = Field(default=None, ge=0)
    roast_day: str | None = Field(default=None, max_length=40)
    ship_days: str | None = Field(default=None, max_length=80)
    subscription_discount_pct: int | None = Field(default=None, ge=0, le=100)
    subscription_enabled: bool | None = None
    customer_accounts_enabled: bool | None = None
    wholesale_min_kg: int | None = Field(default=None, ge=1)
    wholesale_lead_msg: str | None = Field(default=None, max_length=500)
    low_stock_threshold: int | None = Field(default=None, ge=0, le=10000)
    announcement_enabled: bool | None = None
    announcement_text: str | None = Field(default=None, max_length=200)
    announcement_link_url: str | None = Field(default=None, max_length=300)
    announcement_link_label: str | None = Field(default=None, max_length=60)
    announcement_bg_color: str | None = Field(default=None, max_length=20)
    announcement_text_color: str | None = Field(default=None, max_length=20)
    announcement_expires_at: str | None = Field(default=None, max_length=20)
    promo_enabled: bool | None = None
    promo_trigger: Literal["exit", "delay", "scroll", "immediate"] | None = None
    promo_delay_seconds: int | None = Field(default=None, ge=0, le=600)
    promo_show_countdown: bool | None = None
    promo_badge: str | None = Field(default=None, max_length=40)
    promo_title: str | None = Field(default=None, max_length=120)
    promo_subtitle: str | None = Field(default=None, max_length=200)
    promo_body: str | None = Field(default=None, max_length=600)
    promo_cta_label: str | None = Field(default=None, max_length=60)
    promo_cta_url: str | None = Field(default=None, max_length=300)
    promo_image: str | None = Field(default=None, max_length=300)
    promo_expires_at: str | None = Field(default=None, max_length=20)
    promo_dismiss_days: int | None = Field(default=None, ge=0, le=365)


class ShippingRateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    size_band: str
    zone: str
    mode: str
    weight_min_g: int
    weight_max_g: int
    price_clp: int


class ShippingRatePatch(BaseModel):
    price_clp: int = Field(ge=0)


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    slug: str
    title: str
    excerpt: str
    meta_description: str
    cover: str
    published_at: str
    reading_minutes: int
    author: str
    tags: list[str]
    body: str
    is_published: bool


class PostIn(BaseModel):
    slug: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9-]+$")
    title: str = Field(min_length=2, max_length=200)
    excerpt: str = Field(min_length=10, max_length=500)
    meta_description: str = Field(default="", max_length=200)
    cover: str = Field(default="", max_length=300)
    published_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    reading_minutes: int = Field(gt=0, le=120, default=5)
    author: str = Field(default="Equipo Tengu", max_length=100)
    tags: list[str] = Field(default_factory=list)
    body: str = Field(min_length=10, max_length=50000)
    is_published: bool = True


class PostPatch(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    excerpt: str | None = Field(default=None, min_length=10, max_length=500)
    meta_description: str | None = Field(default=None, max_length=200)
    cover: str | None = Field(default=None, max_length=300)
    published_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    reading_minutes: int | None = Field(default=None, gt=0, le=120)
    author: str | None = Field(default=None, max_length=100)
    tags: list[str] | None = None
    body: str | None = Field(default=None, min_length=10, max_length=50000)
    is_published: bool | None = None


class ShippingQuoteIn(BaseModel):
    region: str = Field(min_length=1, max_length=120)
    comuna: str | None = Field(default=None, max_length=120)
    weight_g: int = Field(gt=0, le=200_000)  # tope sanidad: 200 kg
    mode: Literal["domicilio", "punto"] = "domicilio"
    subtotal_clp: int = Field(ge=0)


class ShippingQuoteOut(BaseModel):
    cost_clp: int
    zone: str
    size_band: str
    is_free: bool
    reason: str  # explain: por qué este precio (free / banda / zona)


class ComunaZoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    region: str
    comuna: str | None
    zone: str


class RegionOut(BaseModel):
    """Una región con la lista de sus comunas (relación padre-hijo)."""
    name: str
    comunas: list[str]


class ComunaZoneIn(BaseModel):
    region: str = Field(min_length=2, max_length=120)
    comuna: str | None = Field(default=None, max_length=120)
    zone: Literal["ohiggins", "centro_otros", "extremo"]


class WebpayInitOut(BaseModel):
    token: str
    url: str


class KhipuInitOut(BaseModel):
    payment_id: str
    payment_url: str
    simplified_transfer_url: str | None = None


class MercadoPagoInitOut(BaseModel):
    preference_id: str
    init_point: str  # URL para redirigir al cliente
