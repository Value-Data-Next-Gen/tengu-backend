"""Cron asyncio que procesa suscripciones con next_charge_at vencido.

Crea órdenes pending automáticamente y avisa al admin por email.
El cobro real (Webpay / Khipu) sigue siendo manual o se gestiona aparte —
este cron solo prepara la orden y deja la suscripción agendada al siguiente
ciclo.

Se arranca desde el lifespan de FastAPI."""
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal
from ..models import CoffeeSubscription, Order, OrderStatus
from .email import send_email

POLL_INTERVAL_SECONDS = 3600  # 1 hora
STALE_ORDER_HOURS = 24  # pending sin payment → canceled


def _run_due_subscriptions(db: Session) -> int:
    from ..api.subscriptions import _build_order_from_sub, _pick_surprise_product

    now = datetime.now(timezone.utc)
    due = (
        db.query(CoffeeSubscription)
        .filter(
            CoffeeSubscription.is_active == True,  # noqa: E712
            CoffeeSubscription.next_charge_at != None,  # noqa: E711
            CoffeeSubscription.next_charge_at <= now,
        )
        .all()
    )
    if not due:
        return 0

    processed = []
    for sub in due:
        surprise_slug = _pick_surprise_product(db).slug if sub.is_surprise else None
        order = _build_order_from_sub(db, sub, surprise_product_slug=surprise_slug)
        sub.orders_count += 1
        sub.last_charge_at = now
        sub.next_charge_at = now + timedelta(days=sub.frequency_days)
        processed.append((sub, order))

    db.commit()

    # Notificar admin con la lista de órdenes a cobrar
    admin_to = settings.admin_emails_list[0] if settings.admin_emails_list else None
    if admin_to and processed:
        html = "<p><strong>Suscripciones procesadas automáticamente:</strong></p><ul>"
        for sub, order in processed:
            html += (
                f"<li>Sub #{sub.id} ({sub.customer_email}) → Order #{order.id} "
                f"${order.total_clp:,} CLP · gestionar cobro</li>"
            )
        html += "</ul><p>Entrar al admin: " + settings.frontend_url + "/admin/orders</p>"
        send_email(admin_to, f"Tengu · {len(processed)} suscripción(es) lista(s) para cobrar", html)

    return len(processed)


def _cancel_stale_pending_orders(db: Session) -> int:
    """Cancela órdenes pending con >24h sin payment iniciado.

    "Sin payment iniciado" = NO tiene mp_payment_id ni khipu_payment_id ni
    webpay_token. Esas órdenes son típicamente spam o usuarios que llenaron
    el form y se fueron. Las dejamos como 'canceled' (no se borran para no
    perder evidencia anti-chargeback ni huella de spam).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=STALE_ORDER_HOURS)
    stale = (
        db.query(Order)
        .filter(
            Order.status == OrderStatus.pending.value,
            Order.created_at < cutoff,
            Order.mp_payment_id.is_(None),
            Order.khipu_payment_id.is_(None),
            Order.webpay_token.is_(None),
        )
        .all()
    )
    from .order_lifecycle import mark_order_unpaid

    for o in stale:
        # Cancela + libera la reserva de stock en el kardex (idempotente).
        mark_order_unpaid(
            o, db,
            new_status=OrderStatus.canceled.value,
            note="[auto] cancelada por >24h sin pago iniciado",
        )
    if stale:
        db.commit()
    return len(stale)


async def subscription_cron_loop():
    """Loop asyncio que corre indefinidamente procesando suscripciones
    y limpiando órdenes pending muertas."""
    while True:
        try:
            with SessionLocal() as db:
                count = _run_due_subscriptions(db)
                if count > 0:
                    print(f"[subs-cron] procesadas {count} suscripción(es)")
                cancelled = _cancel_stale_pending_orders(db)
                if cancelled > 0:
                    print(f"[orders-cleanup] canceladas {cancelled} orden(es) pending stale")
        except Exception as e:
            print(f"[subs-cron] error: {e}")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
