import hmac

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Customer, Order, OrderItem, Product, ShippingMethod
from ..schemas import OrderCreatedOut, OrderIn, OrderOut
from ..services.customer_auth import optional_customer
from ..services.order_emails import send_order_created_email
from ..services.rate_limit import client_ip, orders_create_limiter
from ..services.shipping import quote_shipping

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


@router.post("", response_model=OrderCreatedOut, status_code=201)
def create_order(payload: OrderIn, request: Request, db: Session = Depends(get_db)) -> Order:
    # Anti-DoS: 10 órdenes/min por IP. Suficiente para flujos legítimos
    # (un cliente raramente crea 2 órdenes en 60s) y bloquea scripts.
    orders_create_limiter.check(client_ip(request))
    if payload.shipping_method != ShippingMethod.pickup.value:
        if not payload.shipping_address or not payload.shipping_comuna:
            raise HTTPException(status_code=422, detail="Falta dirección o comuna para el despacho.")

    items: list[OrderItem] = []
    subtotal = 0
    for line in payload.items:
        product = db.query(Product).filter(
            Product.slug == line.product_slug,
            Product.is_published == True,  # noqa: E712
        ).first()
        if not product:
            raise HTTPException(status_code=422, detail=f"Producto desconocido: {line.product_slug}")
        variant = next((v for v in product.variants if v.size_g == line.size_g), None)
        if not variant:
            raise HTTPException(
                status_code=422,
                detail=f"Formato {line.size_g}g no disponible para {product.name}",
            )
        if variant.stock_qty < line.quantity:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Stock insuficiente para {product.name} {variant.size_g}g — "
                    f"quedan {variant.stock_qty} disponibles."
                ),
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

    # Cálculo de envío: pickup gratis; resto vía quote dinámico (Blue Express).
    # El frontend ya cotizó y mostró el total; recomputamos server-side para
    # que el cliente no pueda manipular el precio manualmente.
    if payload.shipping_method == ShippingMethod.pickup.value:
        shipping_cost = 0
    else:
        weight_g = sum(line.size_g * line.quantity for line in payload.items)
        quote = quote_shipping(
            db,
            region=payload.shipping_region or "",
            comuna=payload.shipping_comuna,
            weight_g=weight_g,
            mode=payload.shipping_mode or "domicilio",
            subtotal_clp=subtotal,
        )
        shipping_cost = quote["cost_clp"]
    total = subtotal + shipping_cost

    customer = _upsert_customer(db, payload)

    is_pickup = payload.shipping_method == ShippingMethod.pickup.value
    order = Order(
        customer_id=customer.id,
        customer_email=payload.customer_email.lower().strip(),
        customer_name=payload.customer_name.strip(),
        customer_phone=payload.customer_phone.strip(),
        customer_rut=payload.customer_rut.strip(),
        shipping_method=payload.shipping_method,
        shipping_mode=None if is_pickup else payload.shipping_mode,
        shipping_address=None if is_pickup else payload.shipping_address,
        shipping_comuna=None if is_pickup else payload.shipping_comuna,
        shipping_region=None if is_pickup else payload.shipping_region,
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
    # Mail de confirmación al cliente (idempotente). En modo __console__ sólo logea.
    send_order_created_email(order)
    db.commit()
    return order


@router.get("/{order_id}", response_model=OrderOut)
def get_order(
    order_id: int,
    token: str | None = Query(None, min_length=8, max_length=64),
    db: Session = Depends(get_db),
    customer: Customer | None = Depends(optional_customer),
) -> Order:
    """Lectura de una orden. Dos modos de auth aceptados:

    - JWT customer (Authorization: Bearer ...) → orden debe pertenecer a ese
      customer_email. Es el camino seguro para /cuenta/orders.
    - access_token en query (legacy) → secret-link entregado en /thanks. Sirve
      para el flujo guest sin login.
    """
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Orden no encontrada")

    if customer and order.customer_email.lower() == customer.email.lower():
        return order

    if token and order.access_token and hmac.compare_digest(order.access_token, token):
        return order

    raise HTTPException(status_code=404, detail="Orden no encontrada")
