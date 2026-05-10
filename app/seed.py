import json
import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from .models import Product, Variant


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = BACKEND_ROOT / "seed" / "products.json"
SEED_IMAGES = BACKEND_ROOT / "seed" / "images"
UPLOADS_DIR = BACKEND_ROOT / "uploads"


def ensure_uploads_seeded() -> None:
    """Copia las imágenes seed al directorio uploads/ si está vacío."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    if any(UPLOADS_DIR.iterdir()):
        return
    if not SEED_IMAGES.exists():
        return
    for src in SEED_IMAGES.glob("*"):
        if src.is_file():
            shutil.copy2(src, UPLOADS_DIR / src.name)


def seed_products(db: Session) -> int:
    ensure_uploads_seeded()

    if db.query(Product).count() > 0:
        return 0

    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    for entry in data:
        variants = [
            Variant(
                size_g=v["size_g"],
                price_clp=v["price_clp"],
                stock_qty=v.get("stock_qty", 50),
            )
            for v in entry["variants"]
        ]
        product = Product(
            slug=entry["slug"],
            name=entry["name"],
            origin=entry["origin"],
            region=entry.get("region"),
            variety=entry.get("variety"),
            process=entry.get("process"),
            altitude_masl=entry.get("altitude_masl"),
            harvest=entry.get("harvest"),
            roast_profile=entry["roast_profile"],
            producer=entry.get("producer"),
            body=entry.get("body"),
            acidity=entry.get("acidity"),
            tasting_notes=entry.get("tasting_notes", []),
            image=entry.get("image"),
            category=entry["category"],
            featured=entry.get("featured", False),
            variants=variants,
        )
        db.add(product)

    db.commit()
    return len(data)
