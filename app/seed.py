import json
import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from .config import settings
from .models import Category, HeroSlide, Post, Product, Variant


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = BACKEND_ROOT / "seed" / "products.json"
SEED_POSTS_PATH = BACKEND_ROOT / "seed" / "posts.json"
SEED_IMAGES = BACKEND_ROOT / "seed" / "images"
UPLOADS_DIR = Path(settings.uploads_dir) if settings.uploads_dir else BACKEND_ROOT / "uploads"


DEFAULT_NONCOFFEE_CATEGORIES = [
    ("Tazas", "Tazas y vasos térmicos", 200),
    ("Equipo de preparación", "V60, AeroPress, prensas, kettles", 210),
    ("Molinillos", "Manuales y eléctricos", 220),
    ("Accesorios", "Filtros, balanzas, jarras, lecheras", 230),
]


def _ensure_default_categories(db: Session) -> None:
    """Crea categorías comunes para productos no-café. is_visible=False:
    quedan disponibles en /admin/categories sin aparecer en la tienda hasta
    que el admin las active. Idempotente."""
    for name, desc, sort_order in DEFAULT_NONCOFFEE_CATEGORIES:
        existing = db.query(Category).filter(Category.name == name).first()
        if existing:
            continue
        db.add(Category(name=name, description=desc, is_visible=False, sort_order=sort_order))
    db.commit()


def ensure_uploads_seeded() -> None:
    """Copia los archivos del seed que aún no estén en UPLOADS_DIR.
    Idempotente: corre en cada startup. Cuando agregamos un PNG nuevo al
    seed, el siguiente deploy lo trae al disco persistente sin pisar lo
    que ya estaba ahí."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    if not SEED_IMAGES.exists():
        return
    for src in SEED_IMAGES.glob("*"):
        if not src.is_file():
            continue
        target = UPLOADS_DIR / src.name
        if not target.exists():
            shutil.copy2(src, target)


def seed_products(db: Session) -> int:
    ensure_uploads_seeded()

    # Seed de categorías comunes para no-café (invisibles hasta que admin las
    # active + sume productos). Idempotente — solo crea si no existen.
    _ensure_default_categories(db)

    if db.query(Product).count() > 0:
        return 0

    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    # Auto-crear categorías visibles a partir de los productos del seed
    seen_cats: set[str] = set()
    for entry in data:
        if entry["category"] not in seen_cats:
            if not db.query(Category).filter(Category.name == entry["category"]).first():
                db.add(Category(name=entry["category"], is_visible=True))
            seen_cats.add(entry["category"])
    db.flush()
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


# Slides default del hero: mismos base names que servía HeroCarousel hardcodeado.
# title vacío → el frontend usa el titular por defecto (conserva el diseño).
DEFAULT_HERO_SLIDES = [
    {"image": "hero-bg", "eyebrow": "Tostado en Chile", "sort_order": 10},
    {"image": "hero-bag", "eyebrow": "Origen único", "sort_order": 20},
    {"image": "hero-atmosphere", "eyebrow": "Café de especialidad", "sort_order": 30},
]


def seed_hero_slides(db: Session) -> int:
    """Siembra los slides default del carrusel si la tabla está vacía. Idempotente:
    una vez que el admin tiene slides (default o propios), no vuelve a tocarla."""
    if db.query(HeroSlide).count() > 0:
        return 0
    for entry in DEFAULT_HERO_SLIDES:
        db.add(HeroSlide(**entry))
    db.commit()
    return len(DEFAULT_HERO_SLIDES)


def seed_posts(db: Session) -> int:
    """Carga los posts iniciales desde seed/posts.json si la tabla está vacía.
    El JSON sale de exportar frontend/src/data/blog.ts (formato camelCase TS,
    mapeamos a snake_case del modelo)."""
    if db.query(Post).count() > 0:
        return 0
    if not SEED_POSTS_PATH.exists():
        return 0
    data = json.loads(SEED_POSTS_PATH.read_text(encoding="utf-8"))
    for entry in data:
        post = Post(
            slug=entry["slug"],
            title=entry["title"],
            excerpt=entry["excerpt"],
            meta_description=entry.get("metaDescription", ""),
            cover=entry.get("cover", ""),
            published_at=entry["publishedAt"],
            reading_minutes=entry.get("readingMinutes", 5),
            author=entry.get("author", "Equipo Tengu"),
            tags=entry.get("tags", []),
            body=entry["body"],
            is_published=True,
        )
        db.add(post)
    db.commit()
    return len(data)
