"""Khipu Payments v3 — wrapper minimalista.

API ref: https://docs.khipu.com/api/v3

Auth: header `x-api-key: <api_key>`
Endpoint base: https://payment-api.khipu.com/v3

Flujo:
1. POST /payments con {amount, currency=CLP, subject, transaction_id, return_url, cancel_url, notify_url}
   → response: {payment_id, payment_url, simplified_transfer_url, ...}
2. Usuario navega a payment_url o simplified_transfer_url, paga via banco
3. Khipu manda webhook POST a notify_url con {api_version, notification_token}
4. Backend hace GET /payments/<id> con header x-api-key para verificar que esté pagada
5. Si status='done' → marcar orden como paid

NOTA: Khipu (a diferencia de Transbank) tiene cadena TLS válida estándar,
no requiere bypass.
"""
import requests

from ..config import settings


class KhipuError(Exception):
    """Cuando Khipu responde error o credenciales faltan."""


def _headers() -> dict:
    if not settings.khipu_api_key:
        raise KhipuError("KHIPU_API_KEY no configurada")
    return {
        "x-api-key": settings.khipu_api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def is_configured() -> bool:
    return bool(settings.khipu_api_key and settings.khipu_receiver_id)


def create_payment(
    *,
    amount: int,
    subject: str,
    transaction_id: str,
    return_url: str,
    cancel_url: str,
    notify_url: str,
    payer_name: str | None = None,
    payer_email: str | None = None,
) -> dict:
    """Crea un cobro en Khipu y devuelve la URL a la que debe ir el cliente."""
    payload = {
        "amount": amount,
        "currency": "CLP",
        "subject": subject[:255],
        "transaction_id": transaction_id[:60],
        "return_url": return_url,
        "cancel_url": cancel_url,
        "notify_url": notify_url,
        "notify_api_version": "3.0",
    }
    if payer_name:
        payload["payer_name"] = payer_name[:80]
    if payer_email:
        payload["payer_email"] = payer_email

    res = requests.post(
        f"{settings.khipu_api_base}/payments",
        headers=_headers(),
        json=payload,
        timeout=15,
    )
    if not res.ok:
        raise KhipuError(f"Khipu create payment {res.status_code}: {res.text[:300]}")
    return res.json()


def get_payment(payment_id: str) -> dict:
    """Lee el estado actual de un pago. Use este endpoint para verificar
    webhooks (no confiar en el body del webhook)."""
    res = requests.get(
        f"{settings.khipu_api_base}/payments/{payment_id}",
        headers=_headers(),
        timeout=15,
    )
    if not res.ok:
        raise KhipuError(f"Khipu get payment {res.status_code}: {res.text[:300]}")
    return res.json()


def get_payment_by_notification_token(notification_token: str) -> dict:
    """Endpoint v3 alternativo para verificar webhook usando el notification_token."""
    res = requests.post(
        f"{settings.khipu_api_base}/payments/notify",
        headers=_headers(),
        json={"notification_token": notification_token},
        timeout=15,
    )
    if not res.ok:
        raise KhipuError(f"Khipu notify verify {res.status_code}: {res.text[:300]}")
    return res.json()
