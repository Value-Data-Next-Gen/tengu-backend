import hmac

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from ...config import settings
from ...db import get_db
from ...services.auth import issue_session_jwt, require_admin

router = APIRouter()


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class LoginOut(BaseModel):
    jwt: str
    email: str
    expires_in_hours: int


class MeOut(BaseModel):
    email: str


@router.post("/login", response_model=LoginOut)
def login(payload: LoginIn, _: Session = Depends(get_db)) -> LoginOut:
    """Login simple con email + password. El email debe estar en ADMIN_EMAILS y el
    password debe coincidir con ADMIN_PASSWORD. Devuelve JWT 72h."""
    email = payload.email.lower().strip()
    if email not in settings.admin_emails_list:
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    # comparación constante en tiempo para evitar timing attacks
    if not hmac.compare_digest(payload.password, settings.admin_password):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    return LoginOut(
        jwt=issue_session_jwt(email),
        email=email,
        expires_in_hours=settings.session_ttl_hours,
    )


@router.get("/me", response_model=MeOut)
def me(email: str = Depends(require_admin)) -> MeOut:
    return MeOut(email=email)
