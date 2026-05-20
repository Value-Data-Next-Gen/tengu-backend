"""Magic link auth + JWT sessions para customers.

Mismo patrón que `services/auth.py` (admin) pero sin allowlist de emails:
cualquier persona con un email válido puede crear cuenta y recibir su
magic link. El scope del JWT es "customer".
"""
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Customer, CustomerLoginToken


def generate_customer_login_token(db: Session, email: str) -> str:
    """Crea un magic link token de un solo uso. Si el customer no existe,
    lo crea con email solamente (lo demás se completa al primer login)."""
    email = email.lower().strip()
    customer = db.query(Customer).filter(Customer.email == email).first()
    if not customer:
        db.add(Customer(email=email))
        db.commit()

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.magic_link_ttl_minutes)
    db.add(CustomerLoginToken(email=email, token=token, expires_at=expires_at))
    db.commit()
    return token


def consume_customer_login_token(db: Session, token: str) -> str | None:
    """Si el token es válido + no usado + no expirado, lo marca como usado y
    devuelve el email. Si no, None."""
    row = db.query(CustomerLoginToken).filter(CustomerLoginToken.token == token).first()
    if not row or row.used_at is not None:
        return None
    if row.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        return None
    row.used_at = datetime.now(timezone.utc)
    db.commit()
    return row.email


def issue_customer_jwt(email: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.session_ttl_hours)).timestamp()),
        "scope": "customer",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_customer_jwt(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    if payload.get("scope") != "customer":
        return None
    return payload


def require_customer(request: Request, db: Session = Depends(get_db)) -> Customer:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sin sesión")
    token = auth.split(" ", 1)[1].strip()
    payload = decode_customer_jwt(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesión inválida")
    email = payload.get("sub")
    customer = db.query(Customer).filter(Customer.email == email).first()
    if not customer:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Cuenta no existe")
    return customer


def optional_customer(request: Request, db: Session = Depends(get_db)) -> Customer | None:
    """Devuelve el Customer si hay Bearer JWT válido, None si no.
    No falla si no hay sesión — útil para endpoints que aceptan auth o token público."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth.split(" ", 1)[1].strip()
    payload = decode_customer_jwt(token)
    if not payload:
        return None
    email = payload.get("sub")
    return db.query(Customer).filter(Customer.email == email).first()
