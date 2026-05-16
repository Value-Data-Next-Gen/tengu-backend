"""API pública de suscripciones de café."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import CoffeeSubscription, Order, OrderItem, Product, ShippingMethod
from ..schemas import SubscriptionCreateOut, SubscriptionIn, SubscriptionOut
from ..services.shipping import get_settings, quote_shipping

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])


def _shipping_cost_for_sub(db: Session, sub: CoffeeSubscription, subtotal_clp: int) -> int:
    if sub.shipping_method == ShippingMethod.pickup.value:
        return 0
    q = quote_shipping(
        db,
        region=sub.shipping_region or "",
        comuna=sub.shipping_comuna,
        weight_g=sub.size_g,
        mode="domicilio",  # suscripciones por ahora siempre a domicilio
        subtotal_clp=subtotal_clp,
    )
    return q["cost_clp"]


def _pick_surprise_product(db: Session) -> Product:
    """Para la opción 'sorpresa del barista', devuelve el café featured actual.
    En el futuro: rotar entre featured + recientes, o tener una pool curada."""
    product = (
        db.query(Product)
        .filter(Product.featured == True)  # noqa: E712
        .order_by(Product.id)
        .first()
    )
    if not product:
        raise HTTPException(status_code=500, detail="No hay café featured para suscripción sorpresa")
    return product


def _build_order_from_sub(
    db: Session, sub: CoffeeSubscription, surprise_product_slug: str | None = None
) -> Order:
    """Crea una Order pending para una suscripción aplicando descuento."""
    product_slug = sub.product_slug or surprise_product_slug
    product = db.query(Product).filter(Product.slug == product_slug).first()
    if not product:
        raise HTTPException(status_code=422, detail=f"Producto {product_slug} no existe")
    variant = next((v for v in product.variants if v.size_g == sub.size_g), None)
    if not variant:
        raise HTTPException(status_code=422, detail=f"Formato {sub.size_g}g no disponible para {product.name}")

    unit_price_with_discount = round(variant.price_clp * (100 - sub.discount_pct) / 100)
    subtotal = unit_price_with_discount
    shipping_cost = _shipping_cost_for_sub(db, sub, subtotal)
    total = subtotal + shipping_cost

    order = Order(
        customer_email=sub.customer_email,
        customer_name=sub.customer_name,
        customer_phone=sub.customer_phone,
        customer_rut=sub.customer_rut,
        shipping_method=sub.shipping_method,
        shipping_address=sub.shipping_address,
        shipping_comuna=sub.shipping_comuna,
        shipping_region=sub.shipping_region,
        shipping_notes=sub.shipping_notes,
        shipping_cost_clp=shipping_cost,
        subtotal_clp=subtotal,
        total_clp=total,
        items=[
            OrderItem(
                product_slug=product.slug,
                product_name=product.name,
                size_g=variant.size_g,
                unit_price_clp=unit_price_with_discount,
                quantity=1,
                subtotal_clp=subtotal,
            )
        ],
        admin_notes=f"Suscripción #{sub.id} · Cargo {sub.orders_count + 1} · -{sub.discount_pct}%",
    )
    db.add(order)
    db.flush()
    return order


@router.post("", response_model=SubscriptionCreateOut, status_code=201)
def create_subscription(payload: SubscriptionIn, db: Session = Depends(get_db)) -> SubscriptionCreateOut:
    if not payload.is_surprise and not payload.product_slug:
        raise HTTPException(status_code=422, detail="Indica product_slug o marca is_surprise=true")
    if payload.shipping_method != ShippingMethod.pickup.value:
        if not payload.shipping_address or not payload.shipping_comuna:
            raise HTTPException(status_code=422, detail="Falta dirección o comuna para el despacho.")

    surprise_slug: str | None = None
    if payload.is_surprise:
        surprise_slug = _pick_surprise_product(db).slug

    sub = CoffeeSubscription(
        customer_email=payload.customer_email.lower(),
        customer_name=payload.customer_name.strip(),
        customer_phone=payload.customer_phone.strip(),
        customer_rut=payload.customer_rut.strip(),
        shipping_method=payload.shipping_method,
        shipping_address=payload.shipping_address,
        shipping_comuna=payload.shipping_comuna,
        shipping_region=payload.shipping_region,
        shipping_notes=payload.shipping_notes,
        frequency_days=payload.frequency_days,
        product_slug=payload.product_slug,
        size_g=payload.size_g,
        is_surprise=payload.is_surprise,
        discount_pct=get_settings(db).subscription_discount_pct,
        is_active=True,
    )
    db.add(sub)
    db.flush()

    order = _build_order_from_sub(db, sub, surprise_product_slug=surprise_slug)
    sub.first_order_id = order.id
    sub.next_charge_at = datetime.now(timezone.utc) + timedelta(days=sub.frequency_days)

    db.commit()
    db.refresh(sub)
    db.refresh(order)
    return SubscriptionCreateOut(subscription=SubscriptionOut.model_validate(sub), order=order)


@router.get("/{sub_id}", response_model=SubscriptionOut)
def get_subscription(sub_id: int, db: Session = Depends(get_db)) -> SubscriptionOut:
    sub = db.get(CoffeeSubscription, sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Suscripción no encontrada")
    return SubscriptionOut.model_validate(sub)
