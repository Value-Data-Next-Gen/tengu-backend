"""Lógica de validación y aplicación de DiscountCode.

Devuelve (discount_clp, error) — el caller decide qué hacer con el error.
Idéntico tanto en /validate-coupon (público, para mostrar antes de pagar)
como en create_order (autoritativo, recalcula server-side).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import DiscountCode


def normalize_code(raw: str) -> str:
    return (raw or "").strip().upper().replace(" ", "")


def evaluate_coupon(
    db: Session,
    raw_code: str,
    *,
    subtotal_clp: int,
    items: list[dict],
) -> tuple[int, str | None, DiscountCode | None]:
    """Valida un código + calcula el descuento aplicable.

    Returns (discount_clp, error_message, coupon).
    - Si el código no existe / no aplica → (0, "razón", None).
    - Si aplica → (descuento_calculado, None, coupon).

    `items` es una lista de dicts con al menos product_slug y subtotal_clp
    (línea entera). Se usa para applies_to=category|product: el descuento
    se aplica solo a la suma de líneas elegibles.
    """
    code = normalize_code(raw_code)
    if not code:
        return 0, "Ingresá un código.", None

    coupon = db.query(DiscountCode).filter(DiscountCode.code == code).first()
    if not coupon:
        return 0, "Código no válido.", None
    if not coupon.is_active:
        return 0, "Este código ya no está activo.", None

    now = datetime.now(timezone.utc)
    if coupon.valid_from and now < _aware(coupon.valid_from):
        return 0, "Este código aún no está vigente.", None
    if coupon.valid_until and now > _aware(coupon.valid_until):
        return 0, "Este código está vencido.", None
    if coupon.max_uses is not None and coupon.used_count >= coupon.max_uses:
        return 0, "Este código ya se agotó.", None
    if subtotal_clp < coupon.min_subtotal_clp:
        return 0, (
            f"El subtotal mínimo para este código es ${coupon.min_subtotal_clp:,.0f}".replace(",", ".")
        ), None

    # Base sobre la cual aplica el descuento
    if coupon.applies_to == "product" and coupon.applies_value:
        base = sum(
            int(i.get("subtotal_clp") or 0)
            for i in items
            if i.get("product_slug") == coupon.applies_value
        )
        if base == 0:
            return 0, "El código aplica a un producto que no está en tu carrito.", None
    elif coupon.applies_to == "category" and coupon.applies_value:
        # Necesitamos categoría de cada item — se debe pasar en items[].category
        base = sum(
            int(i.get("subtotal_clp") or 0)
            for i in items
            if i.get("category") == coupon.applies_value
        )
        if base == 0:
            return 0, "El código aplica a una categoría que no está en tu carrito.", None
    else:
        base = subtotal_clp

    if coupon.kind == "percent":
        discount = int(round(base * coupon.value / 100))
    else:  # fixed
        discount = min(int(coupon.value), base)

    # No permitir descuento negativo o que exceda base (defensivo)
    discount = max(0, min(discount, base))
    return discount, None, coupon


def _aware(dt: datetime) -> datetime:
    """SQLite devuelve datetimes naive. Las tratamos como UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
