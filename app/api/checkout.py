import hashlib
import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Order, OrderStatus
from ..schemas import CheckoutInitIn, KhipuInitOut, MercadoPagoInitOut, WebpayInitOut
from ..services import khipu, mercadopago, webpay
from ..services.order_lifecycle import mark_order_paid

router = APIRouter(prefix="/api/checkout", tags=["checkout"])


def _verify_mp_signature(
    *, x_signature: str | None, x_request_id: str | None, data_id: str | None
) -> bool:
    """Valida HMAC-SHA256 del header x-signature contra MP_CS_WBHK.
    Si el secret no está configurado, devuelve True (modo permisivo dev).
    Docs: https://www.mercadopago.cl/developers/es/docs/your-integrations/notifications/webhooks#editor_5
    """
    if not settings.mp_cs_wbhk:
        return True  # secret no configurado: aceptar (dev/pre-config)
    if not x_signature or not data_id:
        return False
    # x-signature formato: "ts=1704908010,v1=abc123def456..."
    parts = dict(p.split("=", 1) for p in x_signature.split(",") if "=" in p)
    ts = parts.get("ts")
    v1 = parts.get("v1")
    if not ts or not v1:
        return False
    # Manifest: id:{data_id};request-id:{x_request_id};ts:{ts};
    manifest = f"id:{data_id};request-id:{x_request_id or ''};ts:{ts};"
    expected = hmac.new(
        settings.mp_cs_wbhk.encode(), manifest.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, v1)


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
        return _redirect_to_thanks(
            order_id=order.id if order else None,
            status="canceled",
            token=order.access_token if order else None,
        )

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
        mark_order_paid(order, db)
        result = "paid"
    else:
        order.status = OrderStatus.failed.value
        result = "failed"

    db.commit()
    return _redirect_to_thanks(order_id=order.id, status=result, token=order.access_token)


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
        mark_order_paid(order, db)
    elif payment.get("status") in {"expired", "rejected"}:
        if order.status == OrderStatus.pending.value:
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
    if payment.get("status") == "done":
        mark_order_paid(order, db)
    elif payment.get("status") in {"expired", "rejected"} and order.status == OrderStatus.pending.value:
        order.status = OrderStatus.failed.value

    db.commit()
    return {"order_status": order.status, "khipu_status": payment.get("status")}


# --- Mercado Pago Checkout Pro ---


@router.post("/mercadopago/init", response_model=MercadoPagoInitOut)
def mercadopago_init(payload: CheckoutInitIn, db: Session = Depends(get_db)) -> MercadoPagoInitOut:
    if not mercadopago.is_configured():
        raise HTTPException(status_code=503, detail="Mercado Pago no está configurado")

    order = db.get(Order, payload.order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    if order.status != OrderStatus.pending.value:
        raise HTTPException(status_code=409, detail="La orden ya fue procesada")

    items = [
        {
            "title": f"{it.product_name} {it.size_g}g",
            "quantity": it.quantity,
            "unit_price": it.unit_price_clp,
            "currency_id": "CLP",
        }
        for it in order.items  # type: ignore[attr-defined]
    ]
    # Envío como item separado para que el monto total cuadre con order.total_clp
    if order.shipping_cost_clp > 0:
        items.append({
            "title": "Envío",
            "quantity": 1,
            "unit_price": order.shipping_cost_clp,
            "currency_id": "CLP",
        })

    backend_base = settings.webpay_return_url.rsplit("/api/", 1)[0]
    success_url = f"{settings.frontend_url}/thanks/{order.id}?status=paid&token={order.access_token}"
    failure_url = f"{settings.frontend_url}/thanks/{order.id}?status=failed&token={order.access_token}"
    pending_url = f"{settings.frontend_url}/thanks/{order.id}?status=pending&token={order.access_token}"
    notify_url = f"{backend_base}/api/checkout/mercadopago/notify"

    try:
        preference = mercadopago.create_preference(
            order_id=order.id,
            items=items,
            payer_email=order.customer_email,
            payer_name=order.customer_name,
            success_url=success_url,
            failure_url=failure_url,
            pending_url=pending_url,
            notification_url=notify_url,
        )
    except mercadopago.MercadoPagoError as e:
        raise HTTPException(status_code=502, detail=f"Mercado Pago: {e}") from e

    order.payment_method = "mercadopago"
    order.mp_preference_id = preference.get("id")
    order.mp_response = preference
    db.commit()

    return MercadoPagoInitOut(
        preference_id=preference.get("id", ""),
        init_point=mercadopago.init_point_for_environment(preference),
    )


@router.post("/mercadopago/notify", include_in_schema=False)
async def mercadopago_notify(request: Request, db: Session = Depends(get_db)) -> dict:
    """Webhook de Mercado Pago. MP manda topic=payment con data.id; consultamos
    GET /v1/payments/{id} para confirmar el estado real (nunca confiar en el
    body del webhook por sí solo)."""
    # MP manda los datos vía query params (topic, id) o como JSON body según versión.
    qp = dict(request.query_params)
    body = await _maybe_json(request)
    topic = qp.get("topic") or qp.get("type") or body.get("type") or ""
    payment_id = (
        qp.get("data.id")
        or (body.get("data", {}) or {}).get("id")
        or qp.get("id")
    )

    # Topic estricto: MP usa "payment" o "topic_payment_wh". Evitamos matchear
    # "merchant_order_payment" u otros eventos no-payment por substring.
    if topic.lower() not in {"payment", "topic_payment_wh"} or not payment_id:
        return {"ok": True, "ignored": True, "topic": topic}

    # Verificación HMAC del header x-signature. Solo aplica si MP_CS_WBHK está
    # configurado. Esto bloquea webhooks falsificados que conozcan order_id.
    valid = _verify_mp_signature(
        x_signature=request.headers.get("x-signature"),
        x_request_id=request.headers.get("x-request-id"),
        data_id=str(payment_id),
    )
    if not valid:
        raise HTTPException(status_code=401, detail="Firma del webhook inválida")

    try:
        payment = mercadopago.get_payment(str(payment_id))
    except mercadopago.MercadoPagoError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    # Vincular el payment con la order vía external_reference = "tengu-{id}".
    external_ref = payment.get("external_reference", "")
    if not external_ref.startswith("tengu-"):
        return {"ok": True, "ignored": True, "reason": "external_reference no es de Tengu"}
    try:
        order_id = int(external_ref.removeprefix("tengu-"))
    except ValueError:
        return {"ok": True, "ignored": True, "reason": "external_reference inválido"}

    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Orden no encontrada para ese pago")

    # Validar monto: MP devuelve transaction_amount como float ("15000.0").
    # CLP no tiene decimales pero por redondeo o descuento puede llegar "14999.99".
    # Aceptamos tolerancia ±2 CLP para evitar amount_mismatch por float-rounding.
    paid_amount = round(float(payment.get("transaction_amount") or 0))
    amount_ok = abs(paid_amount - order.total_clp) <= 2
    if not amount_ok:
        # Mismatch fuera de tolerancia: NO marcar paid. Bloquear despacho
        # marcando failed + nota para admin. Si era un approved real con monto
        # raro (descuento aplicado por MP), admin puede revisar y forzar paid.
        order.mp_response = payment
        existing = order.admin_notes or ""
        tag = f"[MP] amount_mismatch: recibido {paid_amount} ≠ esperado {order.total_clp}"
        if "[MP] amount_mismatch" not in existing:
            order.admin_notes = (existing + "\n" + tag).strip()[:1000]
        if order.status == OrderStatus.pending.value:
            order.status = OrderStatus.failed.value
        db.commit()
        return {"ok": True, "warning": "amount_mismatch", "blocked": True}

    order.mp_payment_id = str(payment.get("id", ""))
    order.mp_response = payment
    status_mp = payment.get("status", "")

    # Idempotencia: si la orden ya está paid o canceled/failed por un webhook
    # previo, NO sobrescribimos. Refund/charged_back posteriores no degradan
    # el estado paid (requieren tratamiento manual + emisión de devolución).
    if status_mp == "approved":
        mark_order_paid(order, db)
    elif order.status == OrderStatus.pending.value and status_mp in {"rejected", "cancelled"}:
        order.status = OrderStatus.failed.value
    elif order.status == OrderStatus.paid.value and status_mp in {"refunded", "charged_back"}:
        # Pago revertido post-aprobación: dejamos nota para revisión admin pero
        # no automatizamos el cambio de estado (necesita refund flow + stock).
        existing = order.admin_notes or ""
        if "[MP] refund detectado" not in existing:
            order.admin_notes = (existing + f"\n[MP] refund detectado ({status_mp}). Revisar stock y devolución.").strip()[:1000]

    db.commit()
    return {"ok": True, "status": status_mp}


@router.post("/mercadopago/verify/{order_id}")
def mercadopago_verify(order_id: int, db: Session = Depends(get_db)) -> dict:
    """Re-verifica con MP el estado del pago de la orden y actualiza la DB.
    Útil cuando el webhook se perdió (cold start Azure) o el usuario vuelve a
    /thanks antes que MP llame al notify. Misma lógica que mercadopago_notify
    pero buscando el payment por external_reference."""
    if not mercadopago.is_configured():
        raise HTTPException(status_code=503, detail="Mercado Pago no está configurado")

    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    if not order.mp_preference_id:
        raise HTTPException(status_code=404, detail="Orden no tiene pago MP iniciado")

    try:
        payments = mercadopago.search_payments_by_external_reference(f"tengu-{order.id}")
    except mercadopago.MercadoPagoError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    if not payments:
        return {"order_status": order.status, "mp_status": None}

    # Si hubo varios intentos (tarjeta rechazada → reintento aprobado), MP los
    # devuelve cronológicamente y NO siempre DESC. Priorizamos cualquier
    # "approved", si no, el más reciente por date_created. Tomar payments[0] a
    # ciegas marcaba órdenes pagadas como failed cuando el primer intento había
    # sido rejected.
    approved = [p for p in payments if p.get("status") == "approved"]
    if approved:
        payment = max(approved, key=lambda p: p.get("date_created") or "")
    else:
        payment = max(payments, key=lambda p: p.get("date_created") or "")
    order.mp_payment_id = str(payment.get("id", ""))
    order.mp_response = payment
    status_mp = payment.get("status", "")
    paid_amount = round(float(payment.get("transaction_amount") or 0))
    amount_ok = abs(paid_amount - order.total_clp) <= 2

    # Si MP confirma un pago aprobado con monto correcto, marcamos paid
    # aunque la orden esté en "failed" — un verify anterior buggeado pudo
    # haberla degradado tomando un intento rechazado. paid manda sobre failed.
    if status_mp == "approved" and amount_ok:
        mark_order_paid(order, db, allow_from_failed=True)
    elif order.status == OrderStatus.pending.value and status_mp in {"rejected", "cancelled"}:
        order.status = OrderStatus.failed.value
    db.commit()
    return {"order_status": order.status, "mp_status": status_mp}


# --- Helpers ---


def _redirect_to_thanks(
    order_id: int | None, status: str, token: str | None = None
) -> RedirectResponse:
    if order_id:
        suffix = f"&token={token}" if token else ""
        url = f"{settings.frontend_url}/thanks/{order_id}?status={status}{suffix}"
    else:
        url = f"{settings.frontend_url}/checkout/error?status={status}"
    return RedirectResponse(url=url, status_code=303)
