from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import Order, OrderStatus
from ...schemas import OrderOut
from ...services.auth import require_admin
from ...services.order_lifecycle import mark_order_paid, mark_order_unpaid

router = APIRouter(prefix="/orders", dependencies=[Depends(require_admin)])


class OrderUpdate(BaseModel):
    status: Literal["pending", "paid", "shipped", "delivered", "failed", "canceled"] | None = None
    tracking_code: str | None = None
    admin_notes: str | None = None


@router.get("", response_model=list[OrderOut])
def list_orders(
    status: str | None = None,
    db: Session = Depends(get_db),
) -> list[Order]:
    q = db.query(Order)
    if status:
        q = q.filter(Order.status == status)
    return q.order_by(Order.created_at.desc()).all()


@router.patch("/{order_id}", response_model=OrderOut)
def update_order(order_id: int, payload: OrderUpdate, db: Session = Depends(get_db)) -> Order:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    if payload.status is not None and payload.status != order.status:
        new_status = payload.status
        if new_status == OrderStatus.paid.value:
            # Ruta correcta para marcar paid a mano (ej. transferencia bancaria
            # confirmada): descuenta stock vía kardex, cuenta el cupón y manda
            # emails — todo idempotente. allow_from_any: el admin puede forzar.
            mark_order_paid(order, db, allow_from_any=True)
        elif new_status in (OrderStatus.failed.value, OrderStatus.canceled.value):
            # Libera la reserva de stock al cancelar/fallar (idempotente).
            mark_order_unpaid(
                order, db, new_status=new_status,
                note=f"[admin] estado → {new_status}",
            )
        else:
            order.status = new_status
            if new_status == OrderStatus.shipped.value and not order.shipped_at:
                order.shipped_at = datetime.now(timezone.utc)
    if payload.tracking_code is not None:
        order.tracking_code = payload.tracking_code or None
    if payload.admin_notes is not None:
        order.admin_notes = payload.admin_notes or None
    db.commit()
    db.refresh(order)
    return order
