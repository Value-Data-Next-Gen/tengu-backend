"""Kardex de inventario: toda mutación de stock pasa por aquí.

`apply_movement()` es el ÚNICO lugar que escribe `Variant.stock_qty`, y siempre
deja un rastro en `stock_movements`. Sumar todos los `delta` de una variante
reconstruye su `stock_qty` (invariante del kardex).

Modelo de reserva (lo que cierra el overselling):
- Al crear una orden pending se reserva el stock (movimiento `reserve`, -qty).
  Como `stock_qty` ya refleja las reservas, la validación de disponibilidad de
  la siguiente orden ve el stock realmente libre.
- Si la orden se cancela/falla/expira, se libera (`release`, +qty).
- Si la orden se paga, la reserva queda firme (no se toca el stock de nuevo).

Idempotencia: se basa en el saldo NETO reservado por orden (suma de reserve +
release). Una orden "tiene stock tomado" si ese neto es negativo. Así:
- reserve no duplica si la orden ya tiene stock tomado.
- release no devuelve de más si ya se liberó.
- una recuperación failed→paid (que antes liberó) vuelve a reservar.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Order, Product, StockMovement, Variant

logger = logging.getLogger(__name__)

OPENING = "opening"
SEED = "seed"
RESERVE = "reserve"
RELEASE = "release"
RESTOCK = "restock"
ADJUST = "adjust"

VALID_REASONS = frozenset({OPENING, SEED, RESERVE, RELEASE, RESTOCK, ADJUST})


class StockError(Exception):
    """Error de negocio de inventario (stock insuficiente, cantidad inválida).
    El caller lo traduce a HTTPException con mensaje en español."""


def _find_variant(db: Session, product_slug: str, size_g: int) -> Variant | None:
    return (
        db.query(Variant)
        .join(Product, Variant.product_id == Product.id)
        .filter(Product.slug == product_slug, Variant.size_g == size_g)
        .first()
    )


def apply_movement(
    db: Session,
    variant: Variant,
    delta: int,
    reason: str,
    *,
    order: Order | None = None,
    note: str | None = None,
    created_by: str = "system",
) -> StockMovement:
    """Aplica un movimiento de stock: actualiza variant.stock_qty y registra la
    fila en el kardex. El stock nunca queda negativo; si un delta lo llevaría
    bajo 0 se capa a 0 y se registra el delta efectivamente aplicado."""
    if reason not in VALID_REASONS:
        raise StockError(f"Razón de movimiento inválida: {reason}")

    new_balance = variant.stock_qty + delta
    if new_balance < 0:
        logger.warning(
            "stock clamp: variant=%s reason=%s delta=%d (%d→0)",
            variant.id, reason, delta, variant.stock_qty,
        )
        delta = -variant.stock_qty  # bajamos solo hasta 0
        new_balance = 0

    variant.stock_qty = new_balance
    movement = StockMovement(
        variant_id=variant.id,
        product_slug=variant.product.slug if variant.product else "",
        size_g=variant.size_g,
        delta=delta,
        reason=reason,
        balance_after=new_balance,
        order_id=order.id if order is not None else None,
        note=(note or "")[:300] or None,
        created_by=created_by,
    )
    db.add(movement)
    return movement


def net_reserved(db: Session, order_id: int) -> int:
    """Saldo neto reservado por una orden = suma de deltas reserve + release.
    Negativo → la orden está tomando stock; 0 → no toma (nunca reservó o ya
    liberó)."""
    total = (
        db.query(func.coalesce(func.sum(StockMovement.delta), 0))
        .filter(
            StockMovement.order_id == order_id,
            StockMovement.reason.in_((RESERVE, RELEASE)),
        )
        .scalar()
    )
    return int(total or 0)


def is_holding_stock(db: Session, order_id: int) -> bool:
    return net_reserved(db, order_id) < 0


def reserve_for_order(
    db: Session, order: Order, *, strict: bool, created_by: str = "system"
) -> None:
    """Reserva (-qty) el stock de cada item de la orden.

    Idempotente: si la orden ya está tomando stock, no hace nada.

    strict=True (creación de orden): si algún item no alcanza, NO reserva nada y
    lanza StockError (el caller responde 409). Así se previene el overselling.

    strict=False (pago / recuperación / órdenes legacy): reserva lo que se pueda,
    capando a 0 sin fallar. Sirve para descontar stock al pagar órdenes creadas
    antes de existir el kardex, y para re-reservar tras una recuperación
    failed→paid (que había liberado el stock)."""
    if is_holding_stock(db, order.id):
        return

    if strict:
        shortages: list[str] = []
        for item in order.items:
            variant = _find_variant(db, item.product_slug, item.size_g)
            if variant is None:
                shortages.append(f"{item.product_name} {item.size_g}g (ya no existe)")
            elif variant.stock_qty < item.quantity:
                shortages.append(
                    f"{item.product_name} {item.size_g}g (quedan {variant.stock_qty})"
                )
        if shortages:
            raise StockError("Stock insuficiente para: " + "; ".join(shortages))

    for item in order.items:
        variant = _find_variant(db, item.product_slug, item.size_g)
        if variant is None:
            _note_missing_variant(order, item.product_slug, item.size_g)
            continue
        apply_movement(
            db, variant, -item.quantity, RESERVE,
            order=order, created_by=created_by,
            note=f"Reserva orden #{order.id}",
        )


def release_for_order(
    db: Session, order: Order, *, note: str | None = None, created_by: str = "system"
) -> None:
    """Devuelve (+qty) al stock lo que la orden tenga tomado. Idempotente: si la
    orden no está tomando stock (nunca reservó o ya se liberó), no hace nada.

    Calcula el neto por variante (reserve + release acumulados) para ser robusto
    ante varios ciclos reserve/release de la misma orden."""
    if not is_holding_stock(db, order.id):
        return

    rows = (
        db.query(StockMovement)
        .filter(
            StockMovement.order_id == order.id,
            StockMovement.reason.in_((RESERVE, RELEASE)),
        )
        .all()
    )
    net_by_variant: dict[tuple[int | None, str, int], int] = defaultdict(int)
    for r in rows:
        net_by_variant[(r.variant_id, r.product_slug, r.size_g)] += r.delta

    for (variant_id, slug, size_g), net in net_by_variant.items():
        if net >= 0:
            continue  # esta variante no tiene stock tomado por la orden
        variant = (
            db.get(Variant, variant_id) if variant_id is not None else None
        ) or _find_variant(db, slug, size_g)
        if variant is None:
            continue
        apply_movement(
            db, variant, -net, RELEASE,  # -net es positivo: devuelve stock
            order=order, created_by=created_by,
            note=note or f"Liberación orden #{order.id}",
        )


def restock(
    db: Session, variant: Variant, qty: int, *, created_by: str, note: str | None = None
) -> StockMovement:
    """Ingreso manual de inventario (+qty)."""
    if qty <= 0:
        raise StockError("La cantidad a ingresar debe ser un entero positivo.")
    return apply_movement(db, variant, qty, RESTOCK, created_by=created_by, note=note)


def adjust_to(
    db: Session, variant: Variant, new_qty: int, *, created_by: str, note: str | None = None
) -> StockMovement | None:
    """Ajusta el stock a un valor ABSOLUTO, registrando el delta firmado.
    Devuelve None si no hay cambio."""
    if new_qty < 0:
        raise StockError("El stock no puede ser negativo.")
    delta = new_qty - variant.stock_qty
    if delta == 0:
        return None
    return apply_movement(db, variant, delta, ADJUST, created_by=created_by, note=note)


def ensure_opening_balances(db: Session) -> int:
    """Crea un movimiento `opening` para cada variante que aún no tenga ningún
    movimiento, igualando el kardex a su stock_qty actual. Idempotente: una vez
    sembrada la apertura, no vuelve a tocarla. Devuelve cuántas sembró."""
    variants = db.query(Variant).all()
    if not variants:
        return 0
    # IDs de variantes que ya tienen al menos un movimiento.
    seeded_ids = {
        row[0]
        for row in db.query(StockMovement.variant_id)
        .filter(StockMovement.variant_id.isnot(None))
        .distinct()
        .all()
    }
    created = 0
    for v in variants:
        if v.id in seeded_ids:
            continue
        db.add(
            StockMovement(
                variant_id=v.id,
                product_slug=v.product.slug if v.product else "",
                size_g=v.size_g,
                delta=v.stock_qty,
                reason=OPENING,
                balance_after=v.stock_qty,
                note="Saldo inicial al activar el kardex",
                created_by="system",
            )
        )
        created += 1
    if created:
        db.commit()
    return created


def _note_missing_variant(order: Order, product_slug: str, size_g: int) -> None:
    tag = f"[stock] variante {product_slug}-{size_g}g no existe"
    existing = order.admin_notes or ""
    if tag not in existing:
        order.admin_notes = (existing + "\n" + tag).strip()[:1000]
