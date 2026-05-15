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

## Deploy — Render con SQLite

El repo trae un [`render.yaml`](./render.yaml) listo. Pasos:

1. En Render: **New > Blueprint** → conectar este repo (`Value-Data-Next-Gen/tengu-backend`).
2. Render detecta el blueprint, crea el servicio `tengu-backend` y monta un disco persistente de 1 GB en `/var/data`.
3. Setear en el dashboard (env vars marcadas como `sync: false`):
   - `CORS_ORIGINS` = `https://<tu-sitio>.netlify.app`
   - `FRONTEND_URL` = `https://<tu-sitio>.netlify.app`
   - `WEBPAY_RETURN_URL` = `https://tengu-backend.onrender.com/api/checkout/webpay/return`
   - `ADMIN_PASSWORD` = uno seguro, no el de dev
   - (opcional) credenciales SMTP, Webpay live, Khipu.

> **SQLite + Render**: la DB vive en `/var/data/tengu.db` sobre disco persistente. **Requiere plan Starter ($7/mo)** — el plan Free no soporta discos y SQLite se perdería en cada redeploy. Si quieres migrar a Postgres después, basta cambiar `DATABASE_URL` a `postgresql://…`.

> **Uploads de admin**: el directorio `backend/uploads/` no está en el disco persistente — las imágenes seed se restauran en cada deploy desde `backend/seed/images/`, pero las imágenes subidas por admin se pierden al redeployar. Para producción real, mover a S3/R2 o ampliar el mount del disco.

## License

MIT — ver [LICENSE](LICENSE).
