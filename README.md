# Tengu Roastery — Backend (FastAPI)

REST API que sirve catálogo, carrito, pedidos y pagos para [Tengu Roastery](https://tenguroastery.cl).

## Stack

- **Python 3.11+**
- **FastAPI** + **SQLAlchemy 2.0** + **Pydantic v2**
- **SQLite** en dev (autocreado), **Postgres** recomendado en producción
- **Webpay Plus (Transbank)** sandbox listo

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

- API: http://localhost:8000
- Docs: http://localhost:8000/docs
- OpenAPI: http://localhost:8000/openapi.json

## Endpoints

| Método | Path | Descripción |
|--------|------|-------------|
| `GET` | `/api/products` | Lista de cafés con variantes |
| `GET` | `/api/products/{slug}` | Detalle de producto |
| `POST` | `/api/newsletter` | Suscripción (EmailStr) |
| `POST` | `/api/orders` | Crear orden pending |
| `GET` | `/api/orders/{id}` | Detalle de orden |
| `POST` | `/api/checkout/webpay/init` | Crear transacción Webpay |
| `POST` | `/api/checkout/webpay/return` | Callback Transbank → redirect a frontend |

## Estructura

```
backend/
├── app/
│   ├── main.py           ← FastAPI app + lifespan + CORS
│   ├── config.py         ← Settings (pydantic-settings)
│   ├── db.py             ← SQLAlchemy engine + sessionmaker
│   ├── models.py         ← Product, Variant, Subscription, Order, OrderItem
│   ├── schemas.py        ← Pydantic schemas
│   ├── seed.py           ← Carga seed/products.json
│   ├── api/              ← Routers REST
│   └── services/
│       └── webpay.py     ← Wrapper Transbank SDK
├── seed/
│   └── products.json     ← FUENTE DE VERDAD del catálogo
├── data/                 ← SQLite (gitignored)
├── requirements.txt
└── .env.example
```

## Modificar el catálogo

Edita `seed/products.json` y borra `data/tengu.db` para re-seedar al próximo arranque. Si la app está corriendo, basta con borrar la DB y reiniciar uvicorn.

## Pasarela Webpay

Sandbox público de Transbank. Tarjetas de prueba:

| Caso | Tarjeta | CVV | RUT auth | Pass |
|------|---------|-----|----------|------|
| Aprobada | `4051 8856 0044 6623` | 123 | 11.111.111-1 | 123 |
| Rechazada | `5186 0595 5959 0568` | 123 | — | — |

Para producción: cambiar `IntegrationType.TEST` → `IntegrationType.LIVE` y mover commerce code + API key a env vars.

> ⚠️ El módulo `app/services/webpay.py` contiene un parche para saltar la verificación TLS en llamadas a Transbank. Esto es **solo por la cadena de CAs root rota del entorno de desarrollo**. **Quitar antes de producción**.

## Tests

(Pendiente.)

## Deploy

Recomendado: **Render** o **Railway**.

```bash
# Render: build command
pip install -r requirements.txt

# Render: start command
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Variables de entorno en producción:
- `DATABASE_URL=postgresql://...`
- `CORS_ORIGINS=https://tenguroastery.cl`
- `FRONTEND_URL=https://tenguroastery.cl`
- `WEBPAY_RETURN_URL=https://api.tenguroastery.cl/api/checkout/webpay/return`

## License

MIT — ver [LICENSE](LICENSE).
