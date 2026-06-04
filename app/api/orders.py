import hmac

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AbandonedCart, Customer, Order, OrderItem, Product, ShippingMethod
from ..schemas import OrderCreatedOut, OrderIn, OrderOut
from ..services.coupons import evaluate_coupon
from ..services.customer_auth import optional_customer
from ..services.order_emails import send_order_created_email
from ..services.order_lifecycle import mark_order_paid
from ..services.rate_limit import client_ip, orders_create_limiter, orders_per_email_limiter
from ..services.shipping import quote_shipping
from ..services.stock import StockError, reserve_for_order

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
    # Anti-DoS por IP: 10 órdenes/min.
    orders_create_limiter.check(client_ip(request))
    # Anti-spam por email: 3 órdenes/hora. Bots y formularios de prueba
    # repiten email; corta antes de inflar la DB con basura.
    orders_per_email_limiter.check(payload.customer_email.lower().strip())
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
        # Validar que la molienda esté entre las habilitadas para este producto
        allowed = product.grind_options or ["grano-entero", "molido"]
        if line.grind not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"Molienda '{line.grind}' no disponible para {product.name}",
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
                grind=line.grind,
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

    # Cupón (opcional). Server-side: re-evalúa contra la DB para que el
    # cliente no pueda enviar un descuento manipulado.
    discount_clp = 0
    coupon_code_norm: str | None = None
    coupon_obj = None
    if payload.coupon_code:
        items_for_coupon = [
            {
                "product_slug": it.product_slug,
                "category": next(
                    (p.category for p in [
                        db.query(Product).filter(Product.slug == it.product_slug).first()
                    ] if p), None,
                ),
                "subtotal_clp": it.subtotal_clp,
            }
            for it in items
        ]
        discount_clp, err, coupon_obj = evaluate_coupon(
            db, payload.coupon_code, subtotal_clp=subtotal, items=items_for_coupon
        )
        if err:
            raise HTTPException(status_code=422, detail=err)
        coupon_code_norm = coupon_obj.code if coupon_obj else None

    total = max(0, subtotal - discount_clp) + shipping_cost

    customer = _upsert_customer(db, payload)

    is_pickup = payload.shipping_method == ShippingMethod.pickup.value
    order = Order(
        customer_id=customer.id,
        client_ip=client_ip(request)[:64],
        user_agent=(request.headers.get("user-agent") or "")[:300],
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
        coupon_code=coupon_code_norm,
        discount_clp=discount_clp,
        total_clp=total,
        payment_method=payload.payment_method,
        items=items,
    )
    db.add(order)
    db.flush()  # asigna order.id sin cerrar la transacción
    # Reserva el stock atómicamente. Re-lee stock_qty (que ya refleja reservas
    # de otras órdenes pending), así que cierra el overselling: si entre la
    # validación de arriba y este punto otra orden tomó las últimas unidades,
    # acá falla y se revierte todo.
    try:
        reserve_for_order(db, order, strict=True)
    except StockError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from e
    db.commit()
    db.refresh(order)
    if order.total_clp == 0:
        # Cupón 100% + retiro: no hay nada que cobrar. Las pasarelas rechazan
        # montos 0 (MP: "unit_price must be greater than 0"), así que se
        # confirma de inmediato sin pasar por checkout de pago.
        mark_order_paid(order, db)
        db.commit()
        db.refresh(order)
    # Marcar el abandoned cart (si había) como recovered. Idempotente.
    cart = (
        db.query(AbandonedCart)
        .filter(AbandonedCart.customer_email == order.customer_email.lower())
        .first()
    )
    if cart and cart.status == "open":
        cart.status = "recovered"
        cart.recovered_order_id = order.id
        db.commit()
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
