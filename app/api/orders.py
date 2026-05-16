from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Customer, Order, OrderItem, Product, ShippingMethod, Variant
from ..schemas import OrderIn, OrderOut

router = APIRouter(prefix="/api/orders", tags=["orders"])


def _upsert_customer(db: Session, payload: OrderIn) -> Customer:
    """Crea o actualiza el Customer asociado al email del payload.
    Llena los campos vacíos del Customer existente con los datos de la orden
    (no pisa los que el cliente ya configuró manualmente)."""
    email = payload.customer_email.lower().strip()
    customer = db.query(Customer).filter(Customer.email == email).first()
    if not customer:
        customer = Customer(email=email)
        db.add(customer)

    # Solo llenamos lo que esté vacío en el Customer — preserva preferencias
    # manuales que el cliente haya seteado desde /cuenta.
    if not customer.name:
        customer.name = payload.customer_name.strip()
    if not customer.phone:
        customer.phone = payload.customer_phone.strip()
    if not customer.rut:
        customer.rut = payload.customer_rut.strip()
    if not customer.shipping_address and payload.shipping_address:
        customer.shipping_address = payload.shipping_address
    if not customer.shipping_comuna and payload.shipping_comuna:
        customer.shipping_comuna = payload.shipping_comuna
    if not customer.shipping_region and payload.shipping_region:
        customer.shipping_region = payload.shipping_region

    db.flush()
    return customer


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

    customer = _upsert_customer(db, payload)

    order = Order(
        customer_id=customer.id,
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
        payment_method=payload.payment_method,
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
