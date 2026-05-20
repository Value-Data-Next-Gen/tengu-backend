"""Admin: ver y gestionar carritos abandonados."""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import AbandonedCart
from ...services.auth import require_admin

router = APIRouter(prefix="/abandoned-carts", dependencies=[Depends(require_admin)])


class AbandonedCartOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    customer_email: str
    customer_name: str | None
    customer_phone: str | None
    items: list[dict]
    subtotal_clp: int
    status: str
    recovered_order_id: int | None
    admin_notes: str | None
    last_reminder_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AbandonedCartPatch(BaseModel):
    status: Literal["open", "dismissed"] | None = None
    admin_notes: str | None = None
    # Si admin marca que ya envió un recordatorio manual (WhatsApp/email).
    mark_reminded: bool = False


@router.get("", response_model=list[AbandonedCartOut])
def list_carts(status: str | None = None, db: Session = Depends(get_db)) -> list[AbandonedCart]:
    q = db.query(AbandonedCart)
    if status:
        q = q.filter(AbandonedCart.status == status)
    return q.order_by(AbandonedCart.updated_at.desc()).all()


@router.patch("/{cart_id}", response_model=AbandonedCartOut)
def update_cart(cart_id: int, payload: AbandonedCartPatch, db: Session = Depends(get_db)) -> AbandonedCart:
    cart = db.get(AbandonedCart, cart_id)
    if not cart:
        raise HTTPException(status_code=404, detail="Carrito no encontrado")
    if payload.status is not None:
        cart.status = payload.status
    if payload.admin_notes is not None:
        cart.admin_notes = payload.admin_notes or None
    if payload.mark_reminded:
        from datetime import timezone
        cart.last_reminder_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(cart)
    return cart


@router.delete("/{cart_id}", status_code=204)
def delete_cart(cart_id: int, db: Session = Depends(get_db)) -> None:
    cart = db.get(AbandonedCart, cart_id)
    if not cart:
        raise HTTPException(status_code=404, detail="Carrito no encontrado")
    db.delete(cart)
    db.commit()
