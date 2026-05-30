"""Transiciones de estado de Order con side-effects idempotentes.

Toda transición pending→paid pasa por mark_order_paid() y toda transición a
failed/canceled por mark_order_unpaid(), para que stock (kardex) + emails +
conteo de cupón se ejecuten exactamente una vez aunque el webhook del proveedor
reintente N veces.

El stock se maneja con el kardex (services/stock.py): la orden reserva su stock
al CREARSE (no acá). mark_order_paid solo confirma la reserva (idempotente);
mark_order_unpaid la libera. Para órdenes legacy creadas antes del kardex,
mark_order_paid reserva en el momento del pago (strict=False) para no vender de
más.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import Order, OrderStatus
from . import stock

logger = logging.getLogger(__name__)


def mark_order_paid(
    order: Order,
    db: Session,
    *,
    allow_from_failed: bool = False,
    allow_from_any: bool = False,
) -> bool:
    """Marca orden como paid y dispara side-effects una sola vez.

    Returns True si esta llamada transicionó la orden a paid; False si ya estaba
    paid o el estado de origen no es transicionable.

    Por defecto sólo transiciona desde pending. allow_from_failed=True permite
    recuperar órdenes mal-marcadas failed (ej. verify de MP cuando confirma
    approved tardío). allow_from_any=True (uso admin) permite forzar paid desde
    cualquier estado.

    Side-effects idempotentes:
    - status=paid + paid_at
    - confirma la reserva de stock en el kardex (re-reserva si fue liberada en
      una recuperación failed→paid; reserva legacy si la orden nunca reservó)
    - incrementa DiscountCode.used_count (vía coupon_counted_at)
    - email transaccional (vía notification_paid_sent_at)

    No hace db.commit() — el caller commitea en su contexto.
    """
    if order.status == OrderStatus.paid.value:
        # Ya estaba paid: aseguramos que el stock esté tomado (órdenes legacy
        # sin reserva). Idempotente: no re-reserva si ya está tomado.
        stock.reserve_for_order(db, order, strict=False)
        return False

    allowed = {OrderStatus.pending.value}
    if allow_from_failed:
        allowed.add(OrderStatus.failed.value)
    if not allow_from_any and order.status not in allowed:
        # No transicionamos desde shipped/delivered/canceled salvo allow_from_any.
        return False

    order.status = OrderStatus.paid.value
    if order.paid_at is None:
        order.paid_at = datetime.now(timezone.utc)
    # Confirma/toma la reserva (idempotente). En una recuperación desde failed
    # —que liberó el stock— net_reserved volvió a 0, así que vuelve a reservar.
    stock.reserve_for_order(db, order, strict=False)
    _increment_coupon_used_count(order, db)
    # Emails (cliente + admin). Idempotente vía notification_paid_sent_at.
    # Import diferido para evitar ciclo con services/order_emails.
    from .order_emails import send_order_paid_emails
    send_order_paid_emails(order)
    return True


def mark_order_unpaid(
    order: Order,
    db: Session,
    *,
    new_status: str,
    note: str | None = None,
) -> None:
    """Transición a failed/canceled liberando la reserva de stock (idempotente).
    Úsalo en todos los caminos pending→failed/canceled (callbacks de pago,
    expiración, cancelación admin)."""
    if new_status not in (OrderStatus.failed.value, OrderStatus.canceled.value):
        raise ValueError(f"mark_order_unpaid solo a failed/canceled, no {new_status}")
    order.status = new_status
    if note:
        _append_admin_note(order, note)
    stock.release_for_order(db, order, note=note)


def _increment_coupon_used_count(order: Order, db: Session) -> None:
    """Suma 1 a DiscountCode.used_count una sola vez por orden. Idempotente vía
    order.coupon_counted_at (su propio flag, independiente del stock)."""
    if not order.coupon_code or order.coupon_counted_at is not None:
        return
    # Import local para evitar import circular
    from ..models import DiscountCode

    coupon = db.query(DiscountCode).filter(DiscountCode.code == order.coupon_code).first()
    if coupon:
        coupon.used_count = (coupon.used_count or 0) + 1
    order.coupon_counted_at = datetime.now(timezone.utc)


def _append_admin_note(order: Order, note: str) -> None:
    existing = order.admin_notes or ""
    if note not in existing:
        order.admin_notes = (existing + "\n" + note).strip()[:1000]
