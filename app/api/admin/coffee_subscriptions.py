"""Admin: gestión de suscripciones de café."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import CoffeeSubscription, Order
from ...schemas import OrderOut, SubscriptionOut
from ...services.auth import require_admin
from ..subscriptions import _build_order_from_sub, _pick_surprise_product

router = APIRouter(prefix="/coffee-subscriptions", dependencies=[Depends(require_admin)])


class SubUpdate(BaseModel):
    is_active: bool | None = None
    cancel_reason: str | None = None
    admin_notes: str | None = None
    next_charge_at: datetime | None = None


class ProcessOut(BaseModel):
    subscription: SubscriptionOut
    order: OrderOut


@router.get("", response_model=list[SubscriptionOut])
def list_subs(db: Session = Depends(get_db)) -> list[SubscriptionOut]:
    rows = db.query(CoffeeSubscription).order_by(CoffeeSubscription.created_at.desc()).all()
    return [SubscriptionOut.model_validate(s) for s in rows]


@router.patch("/{sub_id}", response_model=SubscriptionOut)
def update_sub(sub_id: int, payload: SubUpdate, db: Session = Depends(get_db)) -> SubscriptionOut:
    sub = db.get(CoffeeSubscription, sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Suscripción no encontrada")
    if payload.is_active is not None:
        sub.is_active = payload.is_active
        if not payload.is_active and not sub.canceled_at:
            sub.canceled_at = datetime.now(timezone.utc)
    if payload.cancel_reason is not None:
        sub.cancel_reason = payload.cancel_reason or None
    if payload.admin_notes is not None:
        sub.admin_notes = payload.admin_notes or None
    if payload.next_charge_at is not None:
        sub.next_charge_at = payload.next_charge_at
    db.commit()
    db.refresh(sub)
    return SubscriptionOut.model_validate(sub)


@router.post("/{sub_id}/process", response_model=ProcessOut)
def process_next(sub_id: int, db: Session = Depends(get_db)) -> ProcessOut:
    """Crea una nueva Order pending para la suscripción y agenda el próximo cargo.
    El admin después de esto debe gestionar el cobro (mandar link de pago, marcar pagado, etc.)."""
    sub = db.get(CoffeeSubscription, sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Suscripción no encontrada")
    if not sub.is_active:
        raise HTTPException(status_code=409, detail="Suscripción inactiva")

    surprise_slug = _pick_surprise_product(db).slug if sub.is_surprise else None
    order = _build_order_from_sub(db, sub, surprise_product_slug=surprise_slug)

    sub.orders_count += 1
    sub.last_charge_at = datetime.now(timezone.utc)
    sub.next_charge_at = sub.last_charge_at + timedelta(days=sub.frequency_days)
    db.commit()
    db.refresh(sub)
    db.refresh(order)
    return ProcessOut(subscription=SubscriptionOut.model_validate(sub), order=order)
