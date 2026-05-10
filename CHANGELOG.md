# Changelog

## [0.1.0] — 2026-05-10

### Added
- Catálogo: modelo Product + Variant, seed desde `seed/products.json`
- Endpoints: `/api/products`, `/api/products/{slug}`
- Newsletter: modelo Subscription, endpoint `POST /api/newsletter` con EmailStr
- Pedidos: modelos Order + OrderItem con statuses (pending/paid/failed/canceled)
- Checkout: integración Webpay Plus sandbox (Transbank SDK 6.x)
- Endpoints: `POST /api/orders`, `GET /api/orders/{id}`, `POST /api/checkout/webpay/init`, `POST /api/checkout/webpay/return`
- IVA 19% configurable en settings
- Tarifas de envío RM/Regiones/Pickup configurables

### Notas
- Workaround TLS en `services/webpay.py` por cadena de CAs root rota del ambiente local. **Revertir antes de producción**.
