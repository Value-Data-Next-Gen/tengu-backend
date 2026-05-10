from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Order, OrderStatus
from ..schemas import WebpayInitIn, WebpayInitOut
from ..services import webpay

router = APIRouter(prefix="/api/checkout", tags=["checkout"])


@router.post("/webpay/init", response_model=WebpayInitOut)
def webpay_init(payload: WebpayInitIn, db: Session = Depends(get_db)) -> WebpayInitOut:
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
    """Endpoint donde Transbank hace POST tras la pasarela.

    - `token_ws` presente → usuario completó (autorizado o rechazado)
    - `TBK_TOKEN` presente → usuario abortó (botón anular en Webpay)
    - Ambos vacíos → timeout en formulario
    """

    if TBK_TOKEN or TBK_ORDEN_COMPRA:
        # Usuario abortó. Buscar orden y marcarla canceled.
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

    # Commit con Transbank
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


def _redirect_to_thanks(order_id: int | None, status: str) -> RedirectResponse:
    if order_id:
        url = f"{settings.frontend_url}/thanks/{order_id}?status={status}"
    else:
        url = f"{settings.frontend_url}/checkout/error?status={status}"
    return RedirectResponse(url=url, status_code=303)
