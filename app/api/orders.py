from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Order, OrderItem, Product, ShippingMethod, Variant
from ..schemas import OrderIn, OrderOut

router = APIRouter(prefix="/api/orders", tags=["orders"])


def _shipping_cost(method: str) -> int:
    return {
        ShippingMethod.rm.value: settings.shipping_rm_clp,
        ShippingMethod.regiones.value: settings.shipping_regiones_clp,
        ShippingMethod.pickup.value: settings.shipping_pickup_clp,
    }[method]


@router.post("", response_model=OrderOut, status_code=201)
def create_order(payload: OrderIn, db: Session = Depends(get_db)) -> Order:
    if payload.shipping_method != ShippingMethod.pickup.value:
        if not payload.shipping_address or not payload.shipping_comuna:
            raise HTTPException(status_code=422, detail="Falta dirección o comuna para el despacho.")

    items: list[OrderItem] = []
    subtotal = 0
    for line in payload.items:
        product = db.query(Product).filter(Product.slug == line.product_slug).first()
        if not product:
            raise HTTPException(status_code=422, detail=f"Producto desconocido: {line.product_slug}")
        variant = next((v for v in product.variants if v.size_g == line.size_g), None)
        if not variant:
            raise HTTPException(
                status_code=422,
                detail=f"Formato {line.size_g}g no disponible para {product.name}",
            )
        line_subtotal = variant.price_clp * line.quantity
        subtotal += line_subtotal
        items.append(
            OrderItem(
                product_slug=product.slug,
                product_name=product.name,
                size_g=variant.size_g,
                unit_price_clp=variant.price_clp,
                quantity=line.quantity,
                subtotal_clp=line_subtotal,
            )
        )

    shipping_cost = _shipping_cost(payload.shipping_method)
    total = subtotal + shipping_cost

    order = Order(
        customer_email=payload.customer_email.lower(),
        customer_name=payload.customer_name.strip(),
        customer_phone=payload.customer_phone.strip(),
        customer_rut=payload.customer_rut.strip(),
        shipping_method=payload.shipping_method,
        shipping_address=payload.shipping_address,
        shipping_comuna=payload.shipping_comuna,
        shipping_region=payload.shipping_region,
        shipping_notes=payload.shipping_notes,
        shipping_cost_clp=shipping_cost,
        subtotal_clp=subtotal,
        total_clp=total,
        items=items,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: int, db: Session = Depends(get_db)) -> Order:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    return order
