import csv
import io
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import Order, OrderStatus
from ...schemas import OrderOut
from ...services.auth import require_admin
from ...services.order_lifecycle import mark_order_paid, mark_order_unpaid

router = APIRouter(prefix="/orders", dependencies=[Depends(require_admin)])


class OrderUpdate(BaseModel):
    status: Literal["pending", "paid", "shipped", "delivered", "failed", "canceled"] | None = None
    tracking_code: str | None = None
    admin_notes: str | None = None


@router.get("", response_model=list[OrderOut])
def list_orders(
    status: str | None = None,
    db: Session = Depends(get_db),
) -> list[Order]:
    q = db.query(Order)
    if status:
        q = q.filter(Order.status == status)
    return q.order_by(Order.created_at.desc()).all()


@router.get("/export.csv")
def export_orders_csv(
    status: str | None = None, db: Session = Depends(get_db)
) -> StreamingResponse:
    """Exporta los pedidos a CSV (una fila por pedido, items resumidos).
    Acepta el mismo filtro de status que el listado."""
    q = db.query(Order)
    if status:
        q = q.filter(Order.status == status)
    orders = q.order_by(Order.created_at.asc()).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "id", "fecha", "estado", "cliente", "email", "telefono", "rut",
        "envio", "comuna", "region", "subtotal_clp", "envio_clp",
        "descuento_clp", "total_clp", "cupon", "metodo_pago", "tracking", "items",
    ])
    for o in orders:
        items = " | ".join(
            f"{it.product_name} {it.size_g}g x{it.quantity} ({it.grind})" for it in o.items
        )
        writer.writerow([
            o.id,
            o.created_at.isoformat() if o.created_at else "",
            o.status,
            o.customer_name,
            o.customer_email,
            o.customer_phone,
            o.customer_rut,
            o.shipping_method,
            o.shipping_comuna or "",
            o.shipping_region or "",
            o.subtotal_clp,
            o.shipping_cost_clp,
            o.discount_clp,
            o.total_clp,
            o.coupon_code or "",
            o.payment_method or "",
            o.tracking_code or "",
            items,
        ])
    buf.seek(0)
    # BOM para que Excel (es-CL) abra los acentos y el CSV bien.
    return StreamingResponse(
        iter(["﻿" + buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="pedidos-tengu.csv"'},
    )


@router.patch("/{order_id}", response_model=OrderOut)
def update_order(order_id: int, payload: OrderUpdate, db: Session = Depends(get_db)) -> Order:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    if payload.status is not None and payload.status != order.status:
        new_status = payload.status
        if new_status == OrderStatus.paid.value:
            # Ruta correcta para marcar paid a mano (ej. transferencia bancaria
            # confirmada): descuenta stock vía kardex, cuenta el cupón y manda
            # emails — todo idempotente. allow_from_any: el admin puede forzar.
            mark_order_paid(order, db, allow_from_any=True)
        elif new_status in (OrderStatus.failed.value, OrderStatus.canceled.value):
            # Libera la reserva de stock al cancelar/fallar (idempotente).
            mark_order_unpaid(
                order, db, new_status=new_status,
                note=f"[admin] estado → {new_status}",
            )
        else:
            # shipped/delivered solo desde un estado que pasó por pago: desde
            # failed/pending el stock no está reservado y el pedido no se cobró.
            if new_status in (OrderStatus.shipped.value, OrderStatus.delivered.value) and order.status not in (
                OrderStatus.paid.value, OrderStatus.shipped.value, OrderStatus.delivered.value,
            ):
                raise HTTPException(
                    status_code=409,
                    detail="La orden debe estar pagada antes de marcarla enviada/entregada",
                )
            order.status = new_status
            if new_status == OrderStatus.shipped.value and not order.shipped_at:
                order.shipped_at = datetime.now(timezone.utc)
    if payload.tracking_code is not None:
        order.tracking_code = payload.tracking_code or None
    if payload.admin_notes is not None:
        order.admin_notes = payload.admin_notes or None
    db.commit()
    db.refresh(order)
    return order
