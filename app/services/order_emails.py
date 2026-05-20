"""Emails transaccionales asociados al ciclo de vida de Order.

Tres touchpoints:
- Cliente cuando se crea la orden: "Recibimos tu pedido"
- Cliente cuando pasa a paid: "Pago confirmado"
- Admin cuando pasa a paid: "Nuevo pedido pagado"

Cada función es idempotente vía flag en Order (notification_created_sent_at /
notification_paid_sent_at) — no envía dos veces aunque el webhook reintente.

Si SMTP_HOST=__console__ los mails se imprimen al log (modo dev/pre-prod).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..config import settings
from ..models import Order
from .email import send_email

logger = logging.getLogger(__name__)


def _money(clp: int) -> str:
    return f"${clp:,.0f}".replace(",", ".") + " CLP"


def _items_html(order: Order) -> str:
    rows = []
    for it in order.items:
        rows.append(
            f"<tr>"
            f"<td style='padding:6px 8px'>{it.product_name} {it.size_g}g × {it.quantity}</td>"
            f"<td style='padding:6px 8px;text-align:right'>{_money(it.subtotal_clp)}</td>"
            f"</tr>"
        )
    rows.append(
        f"<tr><td style='padding:6px 8px;color:#555'>Envío</td>"
        f"<td style='padding:6px 8px;text-align:right;color:#555'>{_money(order.shipping_cost_clp)}</td></tr>"
    )
    rows.append(
        f"<tr><td style='padding:8px;font-weight:700;border-top:1px solid #ddd'>Total</td>"
        f"<td style='padding:8px;text-align:right;font-weight:700;border-top:1px solid #ddd'>{_money(order.total_clp)}</td></tr>"
    )
    return (
        "<table style='border-collapse:collapse;width:100%;max-width:520px;font-family:Inter,Arial,sans-serif;font-size:14px'>"
        + "".join(rows)
        + "</table>"
    )


def _shipping_summary(order: Order) -> str:
    if order.shipping_method == "pickup":
        return "Retiro en tienda (te avisamos cuándo está listo)."
    parts = [order.shipping_address or "", order.shipping_comuna or "", order.shipping_region or ""]
    return ", ".join(p for p in parts if p)


def send_order_created_email(order: Order) -> bool:
    """Mail al cliente confirmando recepción del pedido. Idempotente."""
    if order.notification_created_sent_at is not None:
        return False
    try:
        subject = f"Recibimos tu pedido #{order.id} — Tengu Roastery"
        html = f"""\
<div style="font-family:Inter,Arial,sans-serif;color:#0F0F0F;max-width:560px;margin:0 auto">
  <h2 style="font-family:Bungee,Arial,sans-serif;color:#1F4E9C;margin:0 0 8px">¡Gracias por tu pedido, {order.customer_name.split(' ')[0]}!</h2>
  <p>Recibimos tu pedido <strong>#{order.id}</strong>. Te avisaremos en cuanto se confirme el pago.</p>
  <h3 style="margin-top:24px">Resumen</h3>
  {_items_html(order)}
  <p style="margin-top:24px"><strong>Despacho:</strong> {_shipping_summary(order)}</p>
  <p style="color:#555;font-size:13px;margin-top:24px">Si tenés alguna duda, respondé este mail o escribinos por Instagram <a href="https://instagram.com/tenguroastery">@tenguroastery</a>.</p>
  <p style="color:#888;font-size:12px;margin-top:16px">— Tengu Roastery · Café de especialidad</p>
</div>
"""
        send_email(order.customer_email, subject, html)
        order.notification_created_sent_at = datetime.now(timezone.utc)
        return True
    except Exception as e:
        logger.warning("send_order_created_email order=%d failed: %s", order.id, e)
        return False


def send_order_paid_emails(order: Order) -> bool:
    """Mail al cliente + al admin cuando la orden pasa a paid. Idempotente."""
    if order.notification_paid_sent_at is not None:
        return False
    try:
        # Cliente
        subject_c = f"¡Pago confirmado! Pedido #{order.id} — Tengu Roastery"
        html_c = f"""\
<div style="font-family:Inter,Arial,sans-serif;color:#0F0F0F;max-width:560px;margin:0 auto">
  <h2 style="font-family:Bungee,Arial,sans-serif;color:#1F4E9C;margin:0 0 8px">Pago confirmado ✅</h2>
  <p>Hola {order.customer_name.split(' ')[0]}, confirmamos el pago de tu pedido <strong>#{order.id}</strong>.</p>
  <p>Tostamos los viernes y despachamos los martes y viernes; te avisaremos con el código de seguimiento apenas salga.</p>
  <h3 style="margin-top:24px">Tu pedido</h3>
  {_items_html(order)}
  <p style="margin-top:24px"><strong>Despacho:</strong> {_shipping_summary(order)}</p>
  <p style="color:#888;font-size:12px;margin-top:24px">— Tengu Roastery · Tostado en Chile, sin endulzantes artificiales</p>
</div>
"""
        send_email(order.customer_email, subject_c, html_c)

        # Admin(s)
        admin_emails = [e.strip() for e in settings.admin_emails.split(",") if e.strip()]
        if admin_emails:
            subject_a = f"💰 Nueva venta #{order.id} — {_money(order.total_clp)}"
            html_a = f"""\
<div style="font-family:Inter,Arial,sans-serif;color:#0F0F0F;max-width:600px">
  <h2 style="margin:0 0 8px">Nuevo pedido pagado #{order.id}</h2>
  <p><strong>{_money(order.total_clp)}</strong> · {order.payment_method or 'pago confirmado'}</p>
  <p><strong>Cliente:</strong> {order.customer_name} &lt;{order.customer_email}&gt; · {order.customer_phone} · RUT {order.customer_rut}</p>
  <p><strong>Despacho:</strong> {_shipping_summary(order)}</p>
  {_items_html(order)}
  <p style="margin-top:16px"><a href="{settings.frontend_url}/admin/orders">→ Ver en admin</a></p>
</div>
"""
            for admin_email in admin_emails:
                send_email(admin_email, subject_a, html_a)

        order.notification_paid_sent_at = datetime.now(timezone.utc)
        return True
    except Exception as e:
        logger.warning("send_order_paid_emails order=%d failed: %s", order.id, e)
        return False
