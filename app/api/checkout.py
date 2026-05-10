from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Order, OrderStatus
from ..schemas import CheckoutInitIn, KhipuInitOut, WebpayInitOut
from ..services import khipu, webpay

router = APIRouter(prefix="/api/checkout", tags=["checkout"])


# --- Webpay ---


@router.post("/webpay/init", response_model=WebpayInitOut)
def webpay_init(payload: CheckoutInitIn, db: Session = Depends(get_db)) -> WebpayInitOut:
    order = db.get(Order, payload.order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    if order.status != OrderStatus.pending.value:
        raise HTTPException(status_code=409, detail="La orden ya fue procesada")

    buy_order = f"tengu-{order.id}"[:26]
    session_id = f"sess-{order.id}-{int(datetime.now().timestamp())}"[:61]

    response = webpay.create_transaction(
        buy_order=buy_order,
        session_id=session_id,
        amount=order.total_clp,
        return_url=settings.webpay_return_url,
    )

    order.payment_method = "webpay"
    order.webpay_buy_order = buy_order
    order.webpay_token = response["token"]
    db.commit()

    return WebpayInitOut(token=response["token"], url=response["url"])


@router.post("/webpay/return", include_in_schema=False)
def webpay_return(
    db: Session = Depends(get_db),
    token_ws: str | None = Form(default=None),
    TBK_TOKEN: str | None = Form(default=None),
    TBK_ORDEN_COMPRA: str | None = Form(default=None),
) -> RedirectResponse:
    if TBK_TOKEN or TBK_ORDEN_COMPRA:
        order = (
            db.query(Order).filter(Order.webpay_buy_order == TBK_ORDEN_COMPRA).first()
            if TBK_ORDEN_COMPRA
            else None
        )
        if order and order.status == OrderStatus.pending.value:
            order.status = OrderStatus.canceled.value
            db.commit()
        return _redirect_to_thanks(order_id=order.id if order else None, status="canceled")

    if not token_ws:
        return _redirect_to_thanks(order_id=None, status="timeout")

    response = webpay.commit_transaction(token_ws)

    order = db.query(Order).filter(Order.webpay_token == token_ws).first()
    if not order:
        return _redirect_to_thanks(order_id=None, status="not_found")

    order.webpay_response = response
    order.webpay_authorization_code = response.get("authorization_code") if isinstance(response, dict) else None

    response_code = response.get("response_code") if isinstance(response, dict) else None
    status_str = response.get("status") if isinstance(response, dict) else None

    if response_code == 0 and status_str == "AUTHORIZED":
        order.status = OrderStatus.paid.value
        order.paid_at = datetime.now(timezone.utc)
        result = "paid"
    else:
        order.status = OrderStatus.failed.value
        result = "failed"

    db.commit()
    return _redirect_to_thanks(order_id=order.id, status=result)


# --- Khipu ---


@router.post("/khipu/init", response_model=KhipuInitOut)
def khipu_init(payload: CheckoutInitIn, db: Session = Depends(get_db)) -> KhipuInitOut:
    if not khipu.is_configured():
        raise HTTPException(status_code=503, detail="Khipu no está configurado")

    order = db.get(Order, payload.order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    if order.status != OrderStatus.pending.value:
        raise HTTPException(status_code=409, detail="La orden ya fue procesada")

    backend_base = settings.webpay_return_url.rsplit("/api/", 1)[0]  # http://host[:port]
    return_url = f"{settings.frontend_url}/checkout/khipu/return?order_id={order.id}"
    cancel_url = f"{settings.frontend_url}/checkout/error?status=canceled&order_id={order.id}"
    notify_url = f"{backend_base}/api/checkout/khipu/notify"

    try:
        response = khipu.create_payment(
            amount=order.total_clp,
            subject=f"Tengu Roastery — Pedido #{order.id}",
            transaction_id=f"tengu-{order.id}",
            return_url=return_url,
            cancel_url=cancel_url,
            notify_url=notify_url,
            payer_name=order.customer_name,
            payer_email=order.customer_email,
        )
    except khipu.KhipuError as e:
        raise HTTPException(status_code=502, detail=f"Khipu: {e}") from e

    order.payment_method = "khipu"
    order.khipu_payment_id = response.get("payment_id")
    order.khipu_response = response
    db.commit()

    return KhipuInitOut(
        payment_id=response.get("payment_id", ""),
        payment_url=response.get("payment_url", ""),
        simplified_transfer_url=response.get("simplified_transfer_url"),
    )


@router.post("/khipu/notify", include_in_schema=False)
async def khipu_notify(request: Request, db: Session = Depends(get_db)) -> dict:
    """Webhook desde Khipu cuando el cobro cambia de estado.

    Khipu envía un POST x-www-form-urlencoded con `notification_token` (v3).
    Verificamos el estado consultando la API con ese token (nunca confiar en
    el body del webhook por sí solo)."""
    form = await request.form()
    notification_token = form.get("notification_token") or (await _maybe_json(request)).get(
        "notification_token"
    )
    if not notification_token:
        raise HTTPException(status_code=400, detail="Falta notification_token")

    try:
        payment = khipu.get_payment_by_notification_token(str(notification_token))
    except khipu.KhipuError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    payment_id = payment.get("payment_id")
    if not payment_id:
        raise HTTPException(status_code=400, detail="Khipu no devolvió payment_id")

    order = db.query(Order).filter(Order.khipu_payment_id == payment_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Orden no encontrada para ese pago")

    order.khipu_response = payment
    if payment.get("status") == "done":
        if order.status == OrderStatus.pending.value:
            order.status = OrderStatus.paid.value
            order.paid_at = datetime.now(timezone.utc)
    elif payment.get("status") in {"expired", "rejected"}:
        order.status = OrderStatus.failed.value

    db.commit()
    return {"ok": True, "status": payment.get("status")}


async def _maybe_json(request: Request) -> dict:
    try:
        return await request.json()
    except Exception:
        return {}


@router.post("/khipu/verify/{order_id}")
def khipu_verify(order_id: int, db: Session = Depends(get_db)) -> dict:
    """Re-verifica con Khipu el estado del pago de la orden y actualiza la BD.

    Útil cuando el usuario vuelve de Khipu antes de que llegue el webhook
    (típico en dev local donde el webhook no puede llegar a localhost) o
    cuando el webhook se perdió.
    """
    order = db.get(Order, order_id)
    if not order or not order.khipu_payment_id:
        raise HTTPException(status_code=404, detail="Orden o pago no encontrado")

    if not khipu.is_configured():
        raise HTTPException(status_code=503, detail="Khipu no está configurado")

    try:
        payment = khipu.get_payment(order.khipu_payment_id)
    except khipu.KhipuError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    order.khipu_response = payment
    if payment.get("status") == "done" and order.status == OrderStatus.pending.value:
        order.status = OrderStatus.paid.value
        order.paid_at = datetime.now(timezone.utc)
    elif payment.get("status") in {"expired", "rejected"} and order.status == OrderStatus.pending.value:
        order.status = OrderStatus.failed.value

    db.commit()
    return {"order_status": order.status, "khipu_status": payment.get("status")}


# --- Helpers ---


def _redirect_to_thanks(order_id: int | None, status: str) -> RedirectResponse:
    if order_id:
        url = f"{settings.frontend_url}/thanks/{order_id}?status={status}"
    else:
        url = f"{settings.frontend_url}/checkout/error?status={status}"
    return RedirectResponse(url=url, status_code=303)
