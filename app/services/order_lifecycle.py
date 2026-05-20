"""Transiciones de estado de Order con side-effects idempotentes.

Toda transición pending→paid debería pasar por mark_order_paid() para que
stock + emails (cuando estén wireados) se ejecuten exactamente una vez
aunque el webhook del proveedor reintente N veces.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import Order, OrderStatus, Product, Variant

logger = logging.getLogger(__name__)


def mark_order_paid(order: Order, db: Session, *, allow_from_failed: bool = False) -> bool:
    """Marca orden como paid y dispara side-effects una sola vez.

    Returns True si esta llamada fue la que transicionó la orden a paid;
    False si ya estaba paid (caller no necesita commit adicional por estado).

    Por defecto sólo transiciona desde pending. allow_from_failed=True permite
    recuperar órdenes mal-marcadas failed (ej. verify endpoint cuando MP
    confirma approved tardío).

    Side-effects idempotentes (cada uno tiene su propio timestamp):
    - status=paid + paid_at
    - decremento de stock_qty en cada variant del pedido
    - email transaccional (TODO: wireado en mark_paid_send_notifications)

    No hace db.commit() — el caller debe commitearlo en su contexto.
    """
    if order.status == OrderStatus.paid.value:
        # Ya estaba paid: pasamos por _decrement_stock por si el flag de
        # idempotencia falta (orden marcada paid antes de esta migración).
        _decrement_stock_if_needed(order, db)
        return False

    allowed = {OrderStatus.pending.value}
    if allow_from_failed:
        allowed.add(OrderStatus.failed.value)
    if order.status not in allowed:
        # No transicionamos desde shipped/delivered/canceled. Caller decide.
        return False

    order.status = OrderStatus.paid.value
    order.paid_at = datetime.now(timezone.utc)
    _decrement_stock_if_needed(order, db)
    # Emails (cliente + admin). Idempotente vía notification_paid_sent_at.
    # Import diferido para evitar ciclo con services/order_emails.
    from .order_emails import send_order_paid_emails
    send_order_paid_emails(order)
    return True


def _decrement_stock_if_needed(order: Order, db: Session) -> None:
    """Resta stock_qty por cada item del pedido. Idempotente vía
    order.stock_decremented_at. Stock no baja de 0."""
    if order.stock_decremented_at is not None:
        return

    for item in order.items:
        variant = (
            db.query(Variant)
            .join(Product, Variant.product_id == Product.id)
            .filter(Product.slug == item.product_slug, Variant.size_g == item.size_g)
            .first()
        )
        if variant is None:
            # Producto/variante eliminado después de la compra: no podemos
            # restar. Lo dejamos como nota para el admin.
            logger.warning(
                "stock_decrement: variant no encontrada slug=%s size=%dg order=%d",
                item.product_slug, item.size_g, order.id,
            )
            existing = order.admin_notes or ""
            tag = f"[stock] variant {item.product_slug}-{item.size_g}g no existe"
            if tag not in existing:
                order.admin_notes = (existing + "\n" + tag).strip()[:1000]
            continue
        variant.stock_qty = max(0, variant.stock_qty - item.quantity)

    order.stock_decremented_at = datetime.now(timezone.utc)
