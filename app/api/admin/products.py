import re
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import Product, Variant
from ...schemas import ProductOut
from ...services.auth import require_admin
from ...seed import UPLOADS_DIR

router = APIRouter(prefix="/products", dependencies=[Depends(require_admin)])

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB


class VariantUpdate(BaseModel):
    price_clp: int | None = Field(default=None, ge=0)
    stock_qty: int | None = Field(default=None, ge=0)


class AdminVariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    size_g: int
    price_clp: int
    stock_qty: int


class AdminProductOut(ProductOut):
    variants: list[AdminVariantOut]  # type: ignore[assignment]


@router.get("", response_model=list[AdminProductOut])
def list_products_admin(db: Session = Depends(get_db)) -> list[Product]:
    return db.query(Product).order_by(Product.name).all()


@router.patch("/variants/{variant_id}", response_model=AdminVariantOut)
def update_variant(
    variant_id: int, payload: VariantUpdate, db: Session = Depends(get_db)
) -> Variant:
    variant = db.get(Variant, variant_id)
    if not variant:
        raise HTTPException(status_code=404, detail="Variante no encontrada")
    if payload.price_clp is not None:
        variant.price_clp = payload.price_clp
    if payload.stock_qty is not None:
        variant.stock_qty = payload.stock_qty
    db.commit()
    db.refresh(variant)
    return variant


@router.post("/{slug}/image", response_model=AdminProductOut)
async def upload_image(
    slug: str, file: UploadFile = File(...), db: Session = Depends(get_db)
) -> Product:
    product = db.query(Product).filter(Product.slug == slug).first()
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="Formato no soportado (jpg/png/webp)")

    # Read into memory with size guard
    contents = await file.read()
    if len(contents) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Imagen demasiado grande (máx 5 MB)")

    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[file.content_type]
    safe_slug = re.sub(r"[^a-z0-9-]", "", product.slug.lower())
    filename = f"{safe_slug}{ext}"
    target = Path(UPLOADS_DIR) / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(contents)

    # If the previous image had a different extension, leave it (StaticFiles can serve both)
    product.image = filename
    db.commit()
    db.refresh(product)
    return product


# Cleanup helper used by tests / dev
@router.delete("/{slug}/image", status_code=204)
def delete_image(slug: str, db: Session = Depends(get_db)) -> None:
    product = db.query(Product).filter(Product.slug == slug).first()
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    if product.image:
        target = Path(UPLOADS_DIR) / product.image
        if target.exists():
            target.unlink()
    product.image = None
    db.commit()


# silence unused import (UPLOADS_DIR + shutil reserved for potential future moves)
_ = shutil
