from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from ...config import settings
from ...db import get_db
from ...services.auth import (
    consume_login_token,
    decode_session_jwt,
    generate_login_token,
    issue_session_jwt,
    require_admin,
)
from ...services.email import send_email

router = APIRouter()


class LoginRequest(BaseModel):
    email: EmailStr


class LoginVerifyRequest(BaseModel):
    token: str


class LoginVerifyResponse(BaseModel):
    jwt: str
    email: str
    expires_in_hours: int


class MeResponse(BaseModel):
    email: str


@router.post("/login/request", status_code=204)
def login_request(payload: LoginRequest, db: Session = Depends(get_db)) -> Response:
    """Genera magic link y lo envía por email. Siempre devuelve 204
    independientemente de si el email es admin (no revela admins)."""
    token = generate_login_token(db, payload.email)
    if token:
        link = f"{settings.frontend_url}/admin/login/verify?token={token}"
        html = f"""
            <p>Hola,</p>
            <p>Hiciste click en "entrar" en el admin de Tengu Roastery. Usa este link
               para entrar (válido por {settings.magic_link_ttl_minutes} minutos):</p>
            <p><a href="{link}" style="display:inline-block;background:#1F4E9C;color:#fff;
               padding:12px 20px;border-radius:6px;text-decoration:none">Entrar al admin</a></p>
            <p>Si no fuiste tú, ignora este correo.</p>
        """
        text = f"Link de admin (válido {settings.magic_link_ttl_minutes} min): {link}"
        send_email(payload.email, "Tu link de admin · Tengu Roastery", html, text)
    return Response(status_code=204)


@router.post("/login/verify", response_model=LoginVerifyResponse)
def login_verify(payload: LoginVerifyRequest, db: Session = Depends(get_db)) -> LoginVerifyResponse:
    email = consume_login_token(db, payload.token)
    if not email:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Token inválido o expirado")
    jwt_token = issue_session_jwt(email)
    return LoginVerifyResponse(jwt=jwt_token, email=email, expires_in_hours=settings.session_ttl_hours)


@router.get("/me", response_model=MeResponse)
def me(email: str = Depends(require_admin)) -> MeResponse:
    return MeResponse(email=email)


# Helper: servir como noop si quieren validar el JWT del frontend antes de cargar la página.
@router.post("/me/check", response_model=MeResponse)
def check_jwt(token: str, _: Session = Depends(get_db)) -> MeResponse:
    payload = decode_session_jwt(token)
    if not payload or payload.get("scope") != "admin":
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Token inválido")
    return MeResponse(email=payload["sub"])
