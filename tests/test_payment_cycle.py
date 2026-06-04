"""Integración del ciclo de pago completo: orden → cupón → MP → webhook → admin."""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import DiscountCode, Order, Variant
from app.services import mercadopago
from app.services.subscriptions_cron import _cancel_stale_pending_orders


def _mock_mp(monkeypatch, **overrides):
    """Configura el módulo mercadopago con respuestas fake."""
    monkeypatch.setattr(mercadopago, "is_configured", lambda: True)
    monkeypatch.setattr(
        mercadopago, "create_preference",
        overrides.get("create_preference", lambda **kw: {"id": "pref-1", "init_point": "http://mp.test/pay"}),
    )
    if "get_payment" in overrides:
        monkeypatch.setattr(mercadopago, "get_payment", overrides["get_payment"])
    if "search" in overrides:
        monkeypatch.setattr(mercadopago, "search_payments_by_external_reference", overrides["search"])


def _create_order(client, order_payload, **extra):
    res = client.post("/api/orders", json={**order_payload, **extra})
    assert res.status_code == 201, res.text
    return res.json()


def _payment(order_id: int, total: int, status: str = "approved", **extra) -> dict:
    return {
        "id": 999111,
        "status": status,
        "external_reference": f"tengu-{order_id}",
        "transaction_amount": float(total),
        "date_created": "2026-06-03T12:00:00Z",
        **extra,
    }


# --- Creación de orden + stock + cupón ---


def test_create_order_with_coupon_reserves_stock(client, db, seed, order_payload):
    order = _create_order(client, order_payload, coupon_code="DIEZ")
    assert order["subtotal_clp"] == 20000
    assert order["discount_clp"] == 2000
    assert order["total_clp"] == 18000
    assert order["status"] == "pending"
    variant = db.query(Variant).filter(Variant.size_g == 250).first()
    db.refresh(variant)
    assert variant.stock_qty == 8  # 10 - 2 reservadas


def test_coupon_100_marks_paid_without_gateway(client, db, seed, order_payload):
    order = _create_order(client, order_payload, coupon_code="TODO")
    assert order["total_clp"] == 0
    assert order["status"] == "paid"


def test_category_coupon_preview_works(client, seed):
    """El preview de cupones por categoría resuelve la categoría server-side."""
    res = client.post("/api/checkout/validate-coupon", json={
        "code": "SOLOCAFE",
        "subtotal_clp": 28000,
        "items": [
            {"product_slug": "test-blend", "subtotal_clp": 20000},
            {"product_slug": "test-mug", "subtotal_clp": 8000},
        ],
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["valid"] is True
    assert body["discount_clp"] == 4000  # 20% solo sobre los 20000 de café


# --- Mercado Pago init ---


def test_mp_init_with_discount_sends_single_item_with_final_total(client, db, seed, order_payload, monkeypatch):
    captured = {}

    def fake_create_preference(**kw):
        captured.update(kw)
        return {"id": "pref-1", "init_point": "http://mp.test/pay"}

    _mock_mp(monkeypatch, create_preference=fake_create_preference)
    order = _create_order(client, order_payload, coupon_code="DIEZ")
    res = client.post("/api/checkout/mercadopago/init", json={"order_id": order["id"]})
    assert res.status_code == 200, res.text
    items = captured["items"]
    assert len(items) == 1
    assert items[0]["unit_price"] == 18000  # total CON descuento
    assert "DIEZ" in items[0]["title"]


def test_mp_init_without_discount_sends_item_detail(client, seed, order_payload, monkeypatch):
    captured = {}

    def fake_create_preference(**kw):
        captured.update(kw)
        return {"id": "pref-1", "init_point": "http://mp.test/pay"}

    _mock_mp(monkeypatch, create_preference=fake_create_preference)
    order = _create_order(client, order_payload)
    res = client.post("/api/checkout/mercadopago/init", json={"order_id": order["id"]})
    assert res.status_code == 200
    total_items = sum(i["unit_price"] * i["quantity"] for i in captured["items"])
    assert total_items == order["total_clp"]


# --- Webhook notify ---


def test_webhook_approved_marks_paid_and_counts_coupon_once(client, db, seed, order_payload, monkeypatch):
    order = _create_order(client, order_payload, coupon_code="UNICO")
    _mock_mp(monkeypatch, get_payment=lambda pid: _payment(order["id"], order["total_clp"]))

    for _ in range(2):  # el retry del webhook debe ser idempotente
        res = client.post("/api/checkout/mercadopago/notify?data.id=999111&type=payment", json={})
        assert res.status_code == 200, res.text

    db.expire_all()
    o = db.get(Order, order["id"])
    assert o.status == "paid"
    assert o.paid_at is not None
    coupon = db.query(DiscountCode).filter(DiscountCode.code == "UNICO").first()
    assert coupon.used_count == 1


def test_webhook_ipn_unsigned_still_processed(client, db, seed, order_payload, monkeypatch):
    """Formato IPN legacy (id+topic, sin x-signature) con secret configurado:
    antes devolvía 401 y MP reintentaba para siempre; ahora se procesa."""
    from app.config import settings
    monkeypatch.setattr(settings, "mp_cs_wbhk", "un-secret-configurado")
    order = _create_order(client, order_payload)
    _mock_mp(monkeypatch, get_payment=lambda pid: _payment(order["id"], order["total_clp"]))

    res = client.post(f"/api/checkout/mercadopago/notify?id=999111&topic=payment", json={})
    assert res.status_code == 200, res.text
    db.expire_all()
    assert db.get(Order, order["id"]).status == "paid"


def test_webhook_null_external_reference_ignored(client, seed, order_payload, monkeypatch):
    """MP puede mandar external_reference null (visto en prod 2026-06-03): antes 500."""
    _create_order(client, order_payload)
    _mock_mp(monkeypatch, get_payment=lambda pid: {
        "id": 1, "status": "approved", "external_reference": None, "transaction_amount": 1000.0,
    })
    res = client.post("/api/checkout/mercadopago/notify?data.id=1&type=payment", json={})
    assert res.status_code == 200
    assert res.json().get("ignored") is True


def test_webhook_amount_mismatch_blocks_and_releases_stock(client, db, seed, order_payload, monkeypatch):
    order = _create_order(client, order_payload, coupon_code="DIEZ")
    # MP cobró el subtotal sin descuento (el bug que tuvo la clienta)
    _mock_mp(monkeypatch, get_payment=lambda pid: _payment(order["id"], 20000))

    res = client.post("/api/checkout/mercadopago/notify?data.id=999111&type=payment", json={})
    assert res.status_code == 200
    assert res.json().get("warning") == "amount_mismatch"
    db.expire_all()
    o = db.get(Order, order["id"])
    assert o.status == "failed"
    assert "amount_mismatch" in (o.admin_notes or "")
    variant = db.query(Variant).filter(Variant.size_g == 250).first()
    assert variant.stock_qty == 10  # reserva liberada


# --- Verify ---


def test_verify_requires_access_token(client, db, seed, order_payload, monkeypatch):
    order = _create_order(client, order_payload)
    _mock_mp(monkeypatch, search=lambda ref: [_payment(order["id"], order["total_clp"])])
    db.expire_all()
    o = db.get(Order, order["id"])
    o.mp_preference_id = "pref-1"
    db.commit()

    assert client.post(f"/api/checkout/mercadopago/verify/{order['id']}").status_code == 422
    assert client.post(
        f"/api/checkout/mercadopago/verify/{order['id']}?token=token-invalido-123"
    ).status_code == 404
    res = client.post(
        f"/api/checkout/mercadopago/verify/{order['id']}?token={o.access_token}"
    )
    assert res.status_code == 200, res.text
    assert res.json()["order_status"] == "paid"


# --- Admin ---


def test_admin_cannot_ship_unpaid_order(client, seed, order_payload):
    order = _create_order(client, order_payload)
    res = client.patch(f"/api/admin/orders/{order['id']}", json={"status": "shipped"})
    assert res.status_code == 409


def test_admin_cancel_returns_coupon_use_and_stock(client, db, seed, order_payload, monkeypatch):
    order = _create_order(client, order_payload, coupon_code="UNICO")
    _mock_mp(monkeypatch, get_payment=lambda pid: _payment(order["id"], order["total_clp"]))
    client.post("/api/checkout/mercadopago/notify?data.id=999111&type=payment", json={})

    res = client.patch(f"/api/admin/orders/{order['id']}", json={"status": "canceled"})
    assert res.status_code == 200, res.text
    db.expire_all()
    coupon = db.query(DiscountCode).filter(DiscountCode.code == "UNICO").first()
    assert coupon.used_count == 0  # uso devuelto: el cupón max_uses=1 revive
    variant = db.query(Variant).filter(Variant.size_g == 250).first()
    assert variant.stock_qty == 10


def test_admin_notes_save(client, seed, order_payload):
    order = _create_order(client, order_payload)
    res = client.patch(f"/api/admin/orders/{order['id']}", json={"admin_notes": "nota de prueba"})
    assert res.status_code == 200
    assert res.json()["admin_notes"] == "nota de prueba"


# --- Cron de expiración ---


def test_stale_cron_cancels_recovers_and_skips_bank_transfer(client, db, seed, order_payload, monkeypatch):
    old = datetime.now(timezone.utc) - timedelta(hours=30)

    abandoned = _create_order(client, order_payload)
    transfer = _create_order(
        client, {**order_payload, "customer_email": "otro@test.cl"}, payment_method="bank_transfer",
    )
    mp_paid = _create_order(client, {**order_payload, "customer_email": "tercero@test.cl"})

    db.expire_all()
    for oid in (abandoned["id"], transfer["id"], mp_paid["id"]):
        db.get(Order, oid).created_at = old
    o3 = db.get(Order, mp_paid["id"])
    o3.mp_preference_id = "pref-x"
    db.commit()

    _mock_mp(monkeypatch, search=lambda ref: [_payment(mp_paid["id"], mp_paid["total_clp"])])
    _cancel_stale_pending_orders(db)

    db.expire_all()
    assert db.get(Order, abandoned["id"]).status == "canceled"      # sin pago iniciado → expira
    assert db.get(Order, transfer["id"]).status == "pending"        # transferencia → se respeta
    assert db.get(Order, mp_paid["id"]).status == "paid"            # webhook perdido → recuperada
