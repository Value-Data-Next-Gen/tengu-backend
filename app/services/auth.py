"""Magic link auth + JWT sessions for admin + cuentas AdminUser con roles."""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import AdminLoginToken, AdminUser


# --- Hash de contraseñas (pbkdf2, stdlib — sin dependencias extra) ---

_PBKDF2_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    """Devuelve 'pbkdf2_sha256$iters$salt_hex$hash_hex'."""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


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


def issue_session_jwt(email: str, role: str = "admin") -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.session_ttl_hours)).timestamp()),
        "scope": "admin",
        "role": role,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_session_jwt(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None


def current_admin_user(request: Request, db: Session = Depends(get_db)) -> AdminUser:
    """Valida el JWT y carga el AdminUser activo. La autoridad vive en la DB
    (rol/estado en vivo), no en el JWT — así desactivar o cambiar rol aplica al
    instante."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sin sesión")
    token = auth.split(" ", 1)[1].strip()
    payload = decode_session_jwt(token)
    if not payload or payload.get("scope") != "admin":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesión inválida")
    email = (payload.get("sub") or "").lower()
    user = db.query(AdminUser).filter(AdminUser.email == email).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")
    return user


def require_admin(request: Request, db: Session = Depends(get_db)) -> str:
    """Dependencia: cualquier admin activo. Devuelve el email (varios endpoints
    lo usan como created_by)."""
    return current_admin_user(request, db).email


def require_super_admin(request: Request, db: Session = Depends(get_db)) -> AdminUser:
    """Dependencia: solo super_admin. Devuelve el AdminUser."""
    user = current_admin_user(request, db)
    if user.role != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requiere super admin")
    return user
