"""Gestión de cuentas admin (AdminUser).

- super_admin: lista, crea, cambia rol, activa/desactiva, resetea contraseñas.
- cualquier admin: cambia su propia contraseña.

Guardas anti-lockout: nadie puede desactivarse/borrarse a sí mismo, y siempre
queda al menos un super_admin activo.
"""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import AdminUser
from ...services.auth import (
    current_admin_user,
    hash_password,
    require_admin,
    require_super_admin,
)

router = APIRouter(prefix="/users", dependencies=[Depends(require_admin)])


class AdminUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    role: str
    is_active: bool
    has_password: bool  # False = sigue usando la contraseña compartida (fallback)
    created_at: datetime

    @classmethod
    def from_model(cls, u: AdminUser) -> "AdminUserOut":
        return cls(
            id=u.id, email=u.email, role=u.role, is_active=u.is_active,
            has_password=bool(u.password_hash), created_at=u.created_at,
        )


class AdminUserCreate(BaseModel):
    email: EmailStr
    role: Literal["super_admin", "admin"] = "admin"
    password: str | None = Field(default=None, min_length=8, max_length=128)


class AdminUserPatch(BaseModel):
    role: Literal["super_admin", "admin"] | None = None
    is_active: bool | None = None


class SetPasswordIn(BaseModel):
    password: str = Field(min_length=8, max_length=128)


def _active_super_count(db: Session, exclude_id: int | None = None) -> int:
    q = db.query(AdminUser).filter(
        AdminUser.role == "super_admin", AdminUser.is_active == True  # noqa: E712
    )
    if exclude_id is not None:
        q = q.filter(AdminUser.id != exclude_id)
    return q.count()


@router.get("", response_model=list[AdminUserOut])
def list_users(
    _: AdminUser = Depends(require_super_admin), db: Session = Depends(get_db)
) -> list[AdminUserOut]:
    rows = db.query(AdminUser).order_by(AdminUser.created_at.asc()).all()
    return [AdminUserOut.from_model(u) for u in rows]


@router.post("", response_model=AdminUserOut, status_code=201)
def create_user(
    payload: AdminUserCreate,
    _: AdminUser = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> AdminUserOut:
    email = payload.email.lower().strip()
    if db.query(AdminUser).filter(AdminUser.email == email).first():
        raise HTTPException(status_code=409, detail="Ya existe un usuario con ese email.")
    user = AdminUser(
        email=email,
        role=payload.role,
        password_hash=hash_password(payload.password) if payload.password else None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return AdminUserOut.from_model(user)


@router.patch("/{user_id}", response_model=AdminUserOut)
def update_user(
    user_id: int,
    payload: AdminUserPatch,
    actor: AdminUser = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> AdminUserOut:
    user = db.get(AdminUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    # Anti-lockout: no podés desactivarte ni bajarte de rol a vos mismo.
    if user.id == actor.id and (payload.is_active is False or payload.role == "admin"):
        raise HTTPException(status_code=409, detail="No podés desactivarte ni quitarte el super admin a vos mismo.")
    # No dejar el sistema sin ningún super admin activo.
    if (payload.role == "admin" or payload.is_active is False) and user.role == "super_admin":
        if _active_super_count(db, exclude_id=user.id) == 0:
            raise HTTPException(status_code=409, detail="Debe quedar al menos un super admin activo.")
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    db.commit()
    db.refresh(user)
    return AdminUserOut.from_model(user)


@router.post("/{user_id}/set-password", response_model=AdminUserOut)
def set_user_password(
    user_id: int,
    payload: SetPasswordIn,
    _: AdminUser = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> AdminUserOut:
    user = db.get(AdminUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    user.password_hash = hash_password(payload.password)
    db.commit()
    db.refresh(user)
    return AdminUserOut.from_model(user)


@router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    actor: AdminUser = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> None:
    user = db.get(AdminUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if user.id == actor.id:
        raise HTTPException(status_code=409, detail="No podés borrarte a vos mismo.")
    if user.role == "super_admin" and _active_super_count(db, exclude_id=user.id) == 0:
        raise HTTPException(status_code=409, detail="Debe quedar al menos un super admin activo.")
    db.delete(user)
    db.commit()


@router.post("/me/password", response_model=AdminUserOut)
def change_my_password(
    payload: SetPasswordIn,
    user: AdminUser = Depends(current_admin_user),
    db: Session = Depends(get_db),
) -> AdminUserOut:
    """Cualquier admin cambia su propia contraseña."""
    user.password_hash = hash_password(payload.password)
    db.commit()
    db.refresh(user)
    return AdminUserOut.from_model(user)
