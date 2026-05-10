"""Magic link auth + JWT sessions for admin."""
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import AdminLoginToken


def generate_login_token(db: Session, email: str) -> str:
    email = email.lower()
    if email not in settings.admin_emails_list:
        # Por seguridad no revelamos si el email es admin: simulamos que lo creamos
        # pero no lo persistimos. El cliente recibe siempre 204 igual.
        return ""

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.magic_link_ttl_minutes)
    db.add(AdminLoginToken(email=email, token=token, expires_at=expires_at))
    db.commit()
    return token


def consume_login_token(db: Session, token: str) -> str | None:
    """Returns email if token is valid + not used + not expired. Marks as used."""
    row = db.query(AdminLoginToken).filter(AdminLoginToken.token == token).first()
    if not row or row.used_at is not None:
        return None
    if row.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        return None
    row.used_at = datetime.now(timezone.utc)
    db.commit()
    return row.email


def issue_session_jwt(email: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.session_ttl_hours)).timestamp()),
        "scope": "admin",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_session_jwt(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None


def require_admin(request: Request, _: Session = Depends(get_db)) -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sin sesión")
    token = auth.split(" ", 1)[1].strip()
    payload = decode_session_jwt(token)
    if not payload or payload.get("scope") != "admin":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesión inválida")
    email = payload.get("sub")
    if not email or email.lower() not in settings.admin_emails_list:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")
    return email
