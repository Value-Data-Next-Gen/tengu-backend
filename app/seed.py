import json
from pathlib import Path

from sqlalchemy.orm import Session

from .models import Product, Variant


SEED_PATH = Path(__file__).resolve().parents[1] / "seed" / "products.json"


def seed_products(db: Session) -> int:
    if db.query(Product).count() > 0:
        return 0

    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    for entry in data:
        variants = [Variant(size_g=v["size_g"], price_clp=v["price_clp"]) for v in entry["variants"]]
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
