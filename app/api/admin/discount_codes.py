"""Admin CRUD para códigos de descuento."""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import DiscountCode
from ...services.auth import require_admin
from ...services.coupons import normalize_code

router = APIRouter(prefix="/discount-codes", dependencies=[Depends(require_admin)])


class DiscountCodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    description: str | None
    kind: str
    value: int
    min_subtotal_clp: int
    valid_from: datetime | None
    valid_until: datetime | None
    max_uses: int | None
    used_count: int
    applies_to: str
    applies_value: str | None
    is_active: bool
    created_at: datetime


class DiscountCodeIn(BaseModel):
    code: str = Field(min_length=2, max_length=40)
    description: str | None = Field(default=None, max_length=300)
    kind: Literal["percent", "fixed"]
    value: int = Field(gt=0)
    min_subtotal_clp: int = Field(default=0, ge=0)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    max_uses: int | None = Field(default=None, ge=1)
    applies_to: Literal["all", "category", "product"] = "all"
    applies_value: str | None = Field(default=None, max_length=120)
    is_active: bool = True

    @field_validator("code")
    @classmethod
    def _normalize(cls, v: str) -> str:
        return normalize_code(v)

    @field_validator("value")
    @classmethod
    def _percent_max_100(cls, v: int, info) -> int:
        # NOTE: validar contra kind requiere model_validator, no field_validator.
        # Lo dejamos al validate-by-call abajo.
        return v


class DiscountCodePatch(BaseModel):
    description: str | None = None
    kind: Literal["percent", "fixed"] | None = None
    value: int | None = Field(default=None, gt=0)
    min_subtotal_clp: int | None = Field(default=None, ge=0)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    max_uses: int | None = Field(default=None, ge=1)
    applies_to: Literal["all", "category", "product"] | None = None
    applies_value: str | None = None
    is_active: bool | None = None


def _validate_business_rules(payload: DiscountCodeIn | DiscountCodePatch, existing: DiscountCode | None = None) -> None:
    kind = getattr(payload, "kind", None) or (existing.kind if existing else None)
    value = getattr(payload, "value", None)
    if value is None and existing:
        value = existing.value
    if kind == "percent" and value is not None and not (1 <= value <= 100):
        raise HTTPException(status_code=422, detail="Para cupones porcentuales, value debe ser 1-100.")


@router.get("", response_model=list[DiscountCodeOut])
def list_codes(db: Session = Depends(get_db)) -> list[DiscountCode]:
    return db.query(DiscountCode).order_by(DiscountCode.created_at.desc()).all()


@router.post("", response_model=DiscountCodeOut, status_code=201)
def create_code(payload: DiscountCodeIn, db: Session = Depends(get_db)) -> DiscountCode:
    _validate_business_rules(payload)
    existing = db.query(DiscountCode).filter(DiscountCode.code == payload.code).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Ya existe un código con código '{payload.code}'.")
    code = DiscountCode(**payload.model_dump())
    db.add(code)
    db.commit()
    db.refresh(code)
    return code


@router.patch("/{code_id}", response_model=DiscountCodeOut)
def update_code(code_id: int, payload: DiscountCodePatch, db: Session = Depends(get_db)) -> DiscountCode:
    code = db.get(DiscountCode, code_id)
    if not code:
        raise HTTPException(status_code=404, detail="Código no encontrado")
    _validate_business_rules(payload, existing=code)
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(code, field, value)
    db.commit()
    db.refresh(code)
    return code


@router.delete("/{code_id}", status_code=204)
def delete_code(code_id: int, db: Session = Depends(get_db)) -> None:
    code = db.get(DiscountCode, code_id)
    if not code:
        raise HTTPException(status_code=404, detail="Código no encontrado")
    db.delete(code)
    db.commit()
