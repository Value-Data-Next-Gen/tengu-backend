"""Test funcional del kardex: invariante, overselling, reserva/liberación, pago.
Corre contra una DB SQLite temporal. No toca la DB de dev.

Uso:  .venv/Scripts/python.exe scripts/test_kardex.py
"""
import os
import tempfile

# DB temporal ANTES de importar la app (config lee env al import).
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/kardex_test.db".replace("\\", "/")
os.environ["SEED_ON_STARTUP"] = "true"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Order, StockMovement, Variant  # noqa: E402
from app.services import stock  # noqa: E402

PASS, FAIL = "✅", "❌"
errors = []


def check(label, cond):
    print(f"  {PASS if cond else FAIL} {label}")
    if not cond:
        errors.append(label)


def invariant_holds(db):
    """Para cada variante: suma de deltas del kardex == stock_qty."""
    ok = True
    for v in db.query(Variant).all():
        total = (
            db.query(func.coalesce(func.sum(StockMovement.delta), 0))
            .filter(StockMovement.variant_id == v.id)
            .scalar()
        )
        if int(total) != v.stock_qty:
            print(f"    desync variant={v.id}: ledger={total} stock_qty={v.stock_qty}")
            ok = False
    return ok


def order_payload(slug, size_g, qty):
    return {
        "customer_email": "tester@gmail.com",
        "customer_name": "Tester Kardex",
        "customer_phone": "+56912345678",
        "customer_rut": "12345678-5",
        "shipping_method": "pickup",
        "payment_method": "bank_transfer",
        "items": [{"product_slug": slug, "size_g": size_g, "quantity": qty, "grind": "grano-entero"}],
    }


with TestClient(app) as client:
    with SessionLocal() as db:
        print("\n[1] Invariante tras seed + apertura")
        check("ledger == stock_qty para todas las variantes", invariant_holds(db))
        n_moves = db.query(StockMovement).count()
        check(f"hay movimientos de apertura/seed ({n_moves})", n_moves > 0)

        # Elegir una variante para los tests y fijar su stock a 5 vía kardex.
        variant = db.query(Variant).first()
        slug = variant.product.slug
        size_g = variant.size_g
        stock.adjust_to(db, variant, 5, created_by="test")
        db.commit()
        vid = variant.id
        print(f"\n[2] Variante de prueba: {slug} {size_g}g, stock fijado a 5")
        check("stock_qty == 5", db.get(Variant, vid).stock_qty == 5)

    # [3] Reserva al crear orden
    print("\n[3] Crear orden de 3 unidades → reserva")
    r = client.post("/api/orders", json=order_payload(slug, size_g, 3))
    check(f"orden creada 201 (got {r.status_code})", r.status_code == 201)
    order1_id = r.json()["id"]
    with SessionLocal() as db:
        check("stock_qty bajó a 2", db.get(Variant, vid).stock_qty == 2)
        check("hay movimiento reserve de la orden", any(
            m.reason == "reserve" and m.delta == -3
            for m in db.query(StockMovement).filter(StockMovement.order_id == order1_id)
        ))

    # [4] Overselling: pedir 3 cuando quedan 2 → 409
    print("\n[4] Crear orden de 3 cuando quedan 2 → 409 (anti-overselling)")
    r = client.post("/api/orders", json=order_payload(slug, size_g, 3))
    # 422 = validación temprana por línea; 409 = backstop de reserva. Ambos
    # significan "rechazada sin vender de más".
    check(f"rechazada 409/422 (got {r.status_code})", r.status_code in (409, 422))
    with SessionLocal() as db:
        check("stock_qty sigue en 2 (no se tocó)", db.get(Variant, vid).stock_qty == 2)

    # [5] Liberación: cancelar la orden 1 → stock vuelve a 5
    print("\n[5] Cancelar orden 1 → libera reserva")
    with SessionLocal() as db:
        from app.services.order_lifecycle import mark_order_unpaid
        o = db.get(Order, order1_id)
        mark_order_unpaid(o, db, new_status="canceled", note="test cancel")
        db.commit()
        check("stock_qty volvió a 5", db.get(Variant, vid).stock_qty == 5)
        check("hay movimiento release +3", any(
            m.reason == "release" and m.delta == 3
            for m in db.query(StockMovement).filter(StockMovement.order_id == order1_id)
        ))
        # [5b] doble liberación no devuelve de más
        mark_order_unpaid(o, db, new_status="canceled", note="test cancel 2")
        db.commit()
        check("doble cancel NO sube stock por sobre 5", db.get(Variant, vid).stock_qty == 5)

    # [6] Pago: crear orden, pagar, verificar que NO doble-descuenta
    print("\n[6] Crear orden de 2 y pagar → stock baja una sola vez")
    r = client.post("/api/orders", json=order_payload(slug, size_g, 2))
    order2_id = r.json()["id"]
    with SessionLocal() as db:
        check("stock_qty bajó a 3 (reserva)", db.get(Variant, vid).stock_qty == 3)
        from app.services.order_lifecycle import mark_order_paid
        o = db.get(Order, order2_id)
        first = mark_order_paid(o, db)
        db.commit()
        check("mark_order_paid devolvió True la 1ª vez", first is True)
        check("stock_qty sigue en 3 (no re-descuenta al pagar)", db.get(Variant, vid).stock_qty == 3)
        # webhook reintenta → idempotente
        second = mark_order_paid(o, db)
        db.commit()
        check("mark_order_paid devolvió False la 2ª vez", second is False)
        check("stock_qty sigue en 3 tras reintento", db.get(Variant, vid).stock_qty == 3)

    # [7] Invariante final
    print("\n[7] Invariante final")
    with SessionLocal() as db:
        check("ledger == stock_qty para todas las variantes", invariant_holds(db))

print("\n" + ("=" * 40))
if errors:
    print(f"{FAIL} {len(errors)} checks fallaron:")
    for e in errors:
        print(f"   - {e}")
    raise SystemExit(1)
print(f"{PASS} Todos los checks pasaron.")
