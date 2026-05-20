import re
import secrets
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import Product, Variant
from ...schemas import ProductIn, ProductOut, ProductPatch, VariantIn
from ...services.auth import require_admin
from ...seed import SEED_IMAGES, UPLOADS_DIR, ensure_uploads_seeded

router = APIRouter(prefix="/products", dependencies=[Depends(require_admin)])

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB


class VariantUpdate(BaseModel):
    price_clp: int | None = Field(default=None, gt=0)  # no aceptamos café gratis (consistente con VariantIn)
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


@router.get("/categories", response_model=list[str])
def list_categories(db: Session = Depends(get_db)) -> list[str]:
    rows = db.query(func.distinct(Product.category)).all()
    return sorted([r[0] for r in rows if r[0]])


@router.post("", response_model=AdminProductOut, status_code=201)
def create_product(payload: ProductIn, db: Session = Depends(get_db)) -> Product:
    existing = db.query(Product).filter(Product.slug == payload.slug).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Ya existe un producto con slug '{payload.slug}'")
    product = Product(
        slug=payload.slug,
        name=payload.name,
        origin=payload.origin,
        region=payload.region,
        variety=payload.variety,
        process=payload.process,
        altitude_masl=payload.altitude_masl,
        harvest=payload.harvest,
        roast_profile=payload.roast_profile,
        producer=payload.producer,
        body=payload.body,
        acidity=payload.acidity,
        tasting_notes=payload.tasting_notes,
        category=payload.category,
        featured=payload.featured,
        is_published=payload.is_published,
        description=payload.description,
        variants=[Variant(size_g=v.size_g, price_clp=v.price_clp, stock_qty=v.stock_qty) for v in payload.variants],
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.patch("/{slug}", response_model=AdminProductOut)
def update_product(slug: str, payload: ProductPatch, db: Session = Depends(get_db)) -> Product:
    product = db.query(Product).filter(Product.slug == slug).first()
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(product, field, value)
    db.commit()
    db.refresh(product)
    return product


@router.delete("/{slug}", status_code=204)
def delete_product(slug: str, db: Session = Depends(get_db)) -> None:
    product = db.query(Product).filter(Product.slug == slug).first()
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    # También borra imagen del disco si existe
    if product.image:
        target = Path(UPLOADS_DIR) / product.image
        if target.exists():
            target.unlink()
    db.delete(product)  # cascade borra variantes
    db.commit()


@router.post("/{slug}/variants", response_model=AdminVariantOut, status_code=201)
def add_variant(slug: str, payload: VariantIn, db: Session = Depends(get_db)) -> Variant:
    product = db.query(Product).filter(Product.slug == slug).first()
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    duplicate = next((v for v in product.variants if v.size_g == payload.size_g), None)
    if duplicate:
        raise HTTPException(status_code=409, detail=f"Ya existe variante de {payload.size_g}g")
    variant = Variant(
        product_id=product.id,
        size_g=payload.size_g,
        price_clp=payload.price_clp,
        stock_qty=payload.stock_qty,
    )
    db.add(variant)
    db.commit()
    db.refresh(variant)
    return variant


@router.delete("/variants/{variant_id}", status_code=204)
def delete_variant(variant_id: int, db: Session = Depends(get_db)) -> None:
    variant = db.get(Variant, variant_id)
    if not variant:
        raise HTTPException(status_code=404, detail="Variante no encontrada")
    # No permitir borrar la última variante
    siblings_count = (
        db.query(func.count(Variant.id)).filter(Variant.product_id == variant.product_id).scalar()
    )
    if siblings_count <= 1:
        raise HTTPException(status_code=409, detail="No se puede borrar la última variante del producto")
    db.delete(variant)
    db.commit()


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
    # Timestamp + hex evitan colisión cuando hay dos uploads en el mismo segundo.
    filename = f"{safe_slug}-{int(time.time())}-{secrets.token_hex(3)}{ext}"
    target = Path(UPLOADS_DIR) / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(contents)

    # Dejamos la imagen anterior en disco como fallback para HTML prerendered con la URL vieja.
    product.image = filename
    db.commit()
    db.refresh(product)
    return product


# Optimización masiva de imágenes: PNGs grandes (fotos de catálogo de
# 1.5+ MB) → WebP q=82 redimensionadas a max 1200px. Reduce el peso ~10×
# sin pérdida visible. Solo procesa imágenes que no son ya WebP o que pasan
# el umbral de tamaño.
@router.post("/optimize-images")
def optimize_images(db: Session = Depends(get_db)) -> dict:
    from PIL import Image

    MAX_DIMENSION = 1200  # px, lado mayor
    WEBP_QUALITY = 82
    SIZE_THRESHOLD = 300 * 1024  # 300 KB; debajo no vale la pena recodificar

    results: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []

    for product in db.query(Product).all():
        if not product.image:
            continue
        src = Path(UPLOADS_DIR) / product.image
        if not src.exists():
            errors.append({"slug": product.slug, "error": "archivo no existe"})
            continue
        size_before = src.stat().st_size
        is_webp = product.image.lower().endswith(".webp")
        if is_webp and size_before < SIZE_THRESHOLD:
            skipped.append({"slug": product.slug, "reason": "ya optimizada"})
            continue
        try:
            with Image.open(src) as im:
                # PNG con transparencia → fondo blanco antes de WebP lossy
                if im.mode in ("RGBA", "LA", "P"):
                    bg = Image.new("RGB", im.size, (255, 255, 255))
                    im = im.convert("RGBA")
                    bg.paste(im, mask=im.split()[-1] if im.mode == "RGBA" else None)
                    im = bg
                elif im.mode != "RGB":
                    im = im.convert("RGB")
                # Resize manteniendo aspect ratio si excede MAX_DIMENSION
                im.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)
                safe_slug = re.sub(r"[^a-z0-9-]", "", product.slug.lower())
                new_name = f"{safe_slug}-opt-{int(time.time())}-{secrets.token_hex(3)}.webp"
                target = Path(UPLOADS_DIR) / new_name
                im.save(target, format="WEBP", quality=WEBP_QUALITY, method=6)
            size_after = target.stat().st_size
            product.image = new_name
            db.commit()
            results.append({
                "slug": product.slug,
                "before_bytes": size_before,
                "after_bytes": size_after,
                "ratio": round(size_after / size_before, 3),
                "new_file": new_name,
            })
        except Exception as e:
            errors.append({"slug": product.slug, "error": str(e)})

    total_before = sum(r["before_bytes"] for r in results)
    total_after = sum(r["after_bytes"] for r in results)
    return {
        "optimized": results,
        "skipped": skipped,
        "errors": errors,
        "total_bytes_before": total_before,
        "total_bytes_after": total_after,
        "savings_pct": round((1 - total_after / total_before) * 100, 1) if total_before else 0,
    }


# GC: borra archivos en UPLOADS_DIR que no son referenciados por ningún
# Product.image o Post.cover. Deja siempre los archivos seed iniciales (en
# caso que un futuro reset de DB necesite volver a ellos).
@router.post("/cleanup-orphan-images")
def cleanup_orphan_images(db: Session = Depends(get_db)) -> dict:
    from ...models import Post
    referenced: set[str] = set()
    for prod in db.query(Product).all():
        if prod.image:
            referenced.add(prod.image)
    for post in db.query(Post).all():
        # post.cover es URL ej. "/uploads/foo.jpg" → extraemos basename
        if post.cover and post.cover.startswith("/uploads/"):
            referenced.add(post.cover.removeprefix("/uploads/"))

    # Nunca borrar archivos del seed (los necesitamos para restore-images).
    seed_names = {p.name for p in SEED_IMAGES.glob("*")}

    deleted: list[str] = []
    bytes_freed = 0
    if UPLOADS_DIR.exists():
        for f in UPLOADS_DIR.iterdir():
            if not f.is_file():
                continue
            if f.name in referenced or f.name in seed_names:
                continue
            try:
                bytes_freed += f.stat().st_size
                f.unlink()
                deleted.append(f.name)
            except OSError:
                continue
    return {"deleted": deleted, "bytes_freed": bytes_freed, "kept": len(referenced)}


# Recovery: restaura imágenes faltantes apuntando al seed más parecido por
# overlap de tokens del slug. Útil cuando se pierde /home/uploads por mala
# config (ver UPLOADS_DIR + MSYS issue) y la DB tiene filenames huérfanos.
@router.post("/restore-images")
def restore_seed_images(db: Session = Depends(get_db)) -> dict:
    ensure_uploads_seeded()  # idempotente: copia seed/images → /home/uploads si vacío
    seed_files = list(SEED_IMAGES.glob("*.jpg")) + list(SEED_IMAGES.glob("*.png")) + list(SEED_IMAGES.glob("*.webp"))
    seed_map = {p.stem: p.name for p in seed_files}

    updated: list[dict] = []
    skipped: list[str] = []
    unmatched: list[str] = []

    for prod in db.query(Product).all():
        if prod.image and (UPLOADS_DIR / prod.image).exists():
            skipped.append(prod.slug)
            continue
        slug_tokens = set(prod.slug.split("-"))
        best_filename: str | None = None
        best_score = 0
        for seed_stem, seed_filename in seed_map.items():
            score = len(slug_tokens & set(seed_stem.split("-")))
            if score > best_score:
                best_score = score
                best_filename = seed_filename
        if best_filename and best_score >= 1:
            prod.image = best_filename
            updated.append({"slug": prod.slug, "image": best_filename, "score": best_score})
        else:
            unmatched.append(prod.slug)

    db.commit()
    return {"updated": updated, "skipped": skipped, "unmatched": unmatched}


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
