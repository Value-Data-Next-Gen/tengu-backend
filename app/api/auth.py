"""Auth público — magic link para customers.

Endpoints:
- POST /api/auth/request-link  → manda email con magic link (siempre 204)
- GET  /api/auth/verify?token= → consume token, devuelve JWT
- GET  /api/auth/me             → datos del customer logueado (Bearer JWT)
- PATCH /api/auth/me            → actualizar perfil / preferencias / dirección
- POST /api/auth/logout         → no-op (el cliente borra el JWT local)
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Customer, Order
from ..schemas import (
    AuthGoogleIn,
    AuthRequestLinkIn,
    AuthVerifyOut,
    CustomerOut,
    CustomerPatch,
    OrderCreatedOut,
)
from ..services.customer_auth import (
    consume_customer_login_token,
    generate_customer_login_token,
    issue_customer_jwt,
    require_customer,
)
from ..services.email import send_email

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _send_magic_link(email: str, token: str) -> None:
    """Envía el magic link al email. En dev (SMTP_HOST=__console__) imprime al log."""
    link = f"{settings.frontend_url}/cuenta/callback?token={token}"
    html = f"""
    <p>Hola,</p>
    <p>Para entrar a tu cuenta Tengu Roastery haz click aquí:</p>
    <p><a href="{link}"><strong>Iniciar sesión</strong></a></p>
    <p>El link vence en {settings.magic_link_ttl_minutes} minutos. Si no lo pediste, ignora este mail.</p>
    <p>—<br/>Tengu Roastery</p>
    """
    send_email(email, "Tu link para entrar a Tengu Roastery", html)


@router.post("/request-link", status_code=204)
def request_link(payload: AuthRequestLinkIn, db: Session = Depends(get_db)) -> None:
    """Genera un magic link y lo envía por email. Siempre 204 para no
    filtrar si el email existe o no."""
    token = generate_customer_login_token(db, payload.email)
    if token:
        _send_magic_link(payload.email.lower(), token)


@router.get("/verify", response_model=AuthVerifyOut)
def verify_link(token: str = Query(...), db: Session = Depends(get_db)) -> AuthVerifyOut:
    email = consume_customer_login_token(db, token)
    if not email:
        raise HTTPException(status_code=401, detail="Token inválido o vencido")
    return AuthVerifyOut(jwt=issue_customer_jwt(email), email=email)


@router.post("/google", response_model=AuthVerifyOut)
def google_login(payload: AuthGoogleIn, db: Session = Depends(get_db)) -> AuthVerifyOut:
    """Verifica el ID token de Google contra los servidores de Google y
    upserta el Customer. Mismo formato de respuesta que magic link."""
    if not settings.google_client_id:
        raise HTTPException(
            status_code=503,
            detail="Login con Google no configurado",
        )
    # Import lazy: solo se carga google-auth si el endpoint se usa.
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    try:
        idinfo = google_id_token.verify_oauth2_token(
            payload.id_token,
            google_requests.Request(),
            settings.google_client_id,
        )
    except ValueError as err:
        raise HTTPException(status_code=401, detail=f"Token Google inválido: {err}") from err

    email = idinfo.get("email", "").lower().strip()
    if not email or not idinfo.get("email_verified", False):
        raise HTTPException(status_code=401, detail="Email no verificado en Google")

    customer = db.query(Customer).filter(Customer.email == email).first()
    if not customer:
        customer = Customer(email=email, name=idinfo.get("name"))
        db.add(customer)
        db.commit()
    elif not customer.name and idinfo.get("name"):
        # Si el customer ya existía (compra previa anónima), llena el nombre desde Google.
        customer.name = idinfo["name"]
        db.commit()

    return AuthVerifyOut(jwt=issue_customer_jwt(email), email=email)


@router.get("/me", response_model=CustomerOut)
def get_me(customer: Customer = Depends(require_customer)) -> Customer:
    return customer


@router.patch("/me", response_model=CustomerOut)
def patch_me(
    patch: CustomerPatch,
    db: Session = Depends(get_db),
    customer: Customer = Depends(require_customer),
) -> Customer:
    for field, value in patch.model_dump(exclude_unset=True).items():
        setattr(customer, field, value)
    db.commit()
    db.refresh(customer)
    return customer


@router.get("/me/orders", response_model=list[OrderCreatedOut])
def list_my_orders(
    db: Session = Depends(get_db),
    customer: Customer = Depends(require_customer),
) -> list[Order]:
    """Devuelve las órdenes del cliente autenticado, incluyendo el access_token
    de cada una para que el dashboard pueda linkear a /thanks/{id}?token=..."""
    return (
        db.query(Order)
        .filter(Order.customer_id == customer.id)
        .order_by(Order.created_at.desc())
        .all()
    )


@router.post("/logout", status_code=204)
def logout() -> None:
    """No-op server-side; el cliente borra su JWT del localStorage."""
    return None
