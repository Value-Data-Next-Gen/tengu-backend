import hmac

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from ...config import settings
from ...db import get_db
from ...models import AdminUser
from ...services.auth import (
    current_admin_user,
    issue_session_jwt,
    verify_password,
)

router = APIRouter()


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class LoginOut(BaseModel):
    jwt: str
    email: str
    role: str
    expires_in_hours: int


class MeOut(BaseModel):
    email: str
    role: str


@router.post("/login", response_model=LoginOut)
def login(payload: LoginIn, db: Session = Depends(get_db)) -> LoginOut:
    """Login con email + password contra AdminUser. Si el usuario aún no seteó su
    contraseña (password_hash None), se acepta la compartida ADMIN_PASSWORD como
    fallback (transición sin lockout). Devuelve JWT con el rol."""
    email = payload.email.lower().strip()
    user = db.query(AdminUser).filter(AdminUser.email == email).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    if user.password_hash:
        ok = verify_password(payload.password, user.password_hash)
    else:
        # Fallback: contraseña compartida hasta que el usuario setee la propia.
        ok = hmac.compare_digest(payload.password, settings.admin_password)
    if not ok:
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    return LoginOut(
        jwt=issue_session_jwt(email, user.role),
        email=email,
        role=user.role,
        expires_in_hours=settings.session_ttl_hours,
    )


@router.get("/me", response_model=MeOut)
def me(user: AdminUser = Depends(current_admin_user)) -> MeOut:
    return MeOut(email=user.email, role=user.role)
