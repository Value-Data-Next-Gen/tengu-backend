"""Integración Checkout Pro de Mercado Pago Chile.

Patrón similar a Khipu/Webpay: el backend crea una preference, devuelve la
init_point al frontend, el cliente se redirige a MP, paga, MP redirige al
return URL y separadamente manda webhook al notification_url.

Docs: https://www.mercadopago.cl/developers/es/docs/checkout-pro
"""
import mercadopago

from ..config import settings


class MercadoPagoError(Exception):
    pass


def is_configured() -> bool:
    return bool(settings.mp_access_token)


def _sdk() -> mercadopago.SDK:
    if not is_configured():
        raise MercadoPagoError("MP_ACCESS_TOKEN no configurado")
    return mercadopago.SDK(settings.mp_access_token)


def create_preference(
    *,
    order_id: int,
    items: list[dict],
    payer_email: str,
    payer_name: str,
    success_url: str,
    failure_url: str,
    pending_url: str,
    notification_url: str,
) -> dict:
    """Crea una preference en MP y devuelve {id, init_point, sandbox_init_point}.

    `items` es lista de dicts {title, quantity, unit_price, currency_id="CLP"}.
    `external_reference` lleva el order_id (el webhook lo necesita para encontrar
    la Order local). MP no garantiza orden de webhook vs return, ambos deben
    ser idempotentes.
    """
    sdk = _sdk()
    payload = {
        "items": items,
        "payer": {
            "name": payer_name,
            "email": payer_email,
        },
        "back_urls": {
            "success": success_url,
            "failure": failure_url,
            "pending": pending_url,
        },
        "auto_return": "approved",  # redirect automático tras pago aprobado
        "notification_url": notification_url,
        "external_reference": f"tengu-{order_id}",
        "statement_descriptor": "TENGU ROASTERY",
        "binary_mode": True,  # aprobado o rechazado, sin estado "pending"
    }
    response = sdk.preference().create(payload)
    if response.get("status", 0) >= 400:
        raise MercadoPagoError(f"MP rechazó la preference: {response.get('response', response)}")
    return response["response"]


def get_payment(payment_id: str) -> dict:
    """Consulta el detalle de un payment por id. Usado desde el webhook para
    confirmar el estado real (nunca confiar en el body del webhook por sí solo)."""
    sdk = _sdk()
    response = sdk.payment().get(payment_id)
    if response.get("status", 0) >= 400:
        raise MercadoPagoError(f"MP get_payment falló: {response.get('response', response)}")
    return response["response"]


def search_payments_by_external_reference(external_reference: str) -> list[dict]:
    """Devuelve los payments asociados a un external_reference, ordenados por
    date_created DESC (más reciente primero). Usado para verify manual cuando
    el webhook se perdió."""
    sdk = _sdk()
    response = sdk.payment().search(filters={"external_reference": external_reference})
    if response.get("status", 0) >= 400:
        raise MercadoPagoError(f"MP search falló: {response.get('response', response)}")
    return (response.get("response", {}) or {}).get("results", [])


def init_point_for_environment(preference: dict) -> str:
    """Devuelve sandbox_init_point en test, init_point en live. Si el
    environment es 'test' pero la cuenta no es sandbox, igual cae al init_point."""
    if settings.mp_environment.lower() == "test":
        return preference.get("sandbox_init_point") or preference.get("init_point", "")
    return preference.get("init_point", "")
