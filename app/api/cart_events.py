"""Endpoint público para registrar carritos en progreso (anti-abandono).

Disparado desde el frontend cuando el usuario llena email + tiene items en
el carrito. Hace upsert por email: un solo AbandonedCart "open" por cliente.

Cuando el cliente completa POST /api/orders con el mismo email, la orden
crea/actualiza el cart a status=recovered (ver orders.py).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AbandonedCart
from ..services.rate_limit import client_ip, RateLimiter

router = APIRouter(prefix="/api/cart-events", tags=["cart-events"])

# Más permisivo que orders (un cliente puede actualizar su cart varias veces
# al cambiar cantidades). 30/min por IP, 60/h por email.
_cart_event_ip_limiter = RateLimiter(max_calls=30, window_seconds=60)
_cart_event_email_limiter = RateLimiter(max_calls=60, window_seconds=3600)


class CartItemIn(BaseModel):
    product_slug: str = Field(max_length=120)
    product_name: str = Field(max_length=200)
    size_g: int = Field(gt=0)
    unit_price_clp: int = Field(ge=0)
    quantity: int = Field(gt=0, le=99)


class CartEventIn(BaseModel):
    customer_email: EmailStr
    customer_name: str | None = Field(default=None, max_length=200)
    customer_phone: str | None = Field(default=None, max_length=40)
    items: list[CartItemIn] = Field(min_length=1, max_length=20)
    subtotal_clp: int = Field(ge=0)


@router.post("", status_code=204)
def register_cart_event(
    payload: CartEventIn, request: Request, db: Session = Depends(get_db)
) -> None:
    _cart_event_ip_limiter.check(client_ip(request))
    email = payload.customer_email.lower().strip()
    _cart_event_email_limiter.check(email)

    cart = db.query(AbandonedCart).filter(AbandonedCart.customer_email == email).first()
    items_data = [it.model_dump() for it in payload.items]

    if cart:
        # Si el carrito ya fue marcado dismissed por admin, no resucitarlo.
        # Recovered sí se actualiza (cliente armó carrito nuevo post-compra).
        if cart.status == "dismissed":
            return
        cart.customer_name = payload.customer_name or cart.customer_name
        cart.customer_phone = payload.customer_phone or cart.customer_phone
        cart.items = items_data
        cart.subtotal_clp = payload.subtotal_clp
        if cart.status == "recovered":
            cart.status = "open"
            cart.recovered_order_id = None
        cart.updated_at = datetime.now(timezone.utc)
    else:
        cart = AbandonedCart(
            customer_email=email,
            customer_name=payload.customer_name,
            customer_phone=payload.customer_phone,
            items=items_data,
            subtotal_clp=payload.subtotal_clp,
            status="open",
        )
        db.add(cart)
    db.commit()
