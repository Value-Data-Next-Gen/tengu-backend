from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Category, Product, SiteSettings
from ..schemas import ProductOut, VariantOut

router = APIRouter(prefix="/api/products", tags=["products"])


def _hidden_categories(db: Session) -> set[str]:
    """Categorías con is_visible=False — sus productos se ocultan del público."""
    return {c.name for c in db.query(Category).filter(Category.is_visible == False).all()}  # noqa: E712


def _low_stock_threshold(db: Session) -> int:
    s = db.query(SiteSettings).first()
    return s.low_stock_threshold if s else 10


def _to_out(product: Product, threshold: int) -> ProductOut:
    """Serializa Product → ProductOut exponiendo stock_qty SOLO si está bajo
    el threshold. Evita filtrar inventario completo al público."""
    return ProductOut(
        id=product.id,
        slug=product.slug,
        name=product.name,
        origin=product.origin,
        region=product.region,
        variety=product.variety,
        process=product.process,
        altitude_masl=product.altitude_masl,
        harvest=product.harvest,
        roast_profile=product.roast_profile,
        producer=product.producer,
        body=product.body,
        acidity=product.acidity,
        tasting_notes=product.tasting_notes or [],
        image=product.image,
        category=product.category,
        featured=product.featured,
        is_published=product.is_published,
        description=product.description,
        grind_options=product.grind_options or ["grano-entero", "molido"],
        variants=[
            VariantOut(
                id=v.id,
                size_g=v.size_g,
                price_clp=v.price_clp,
                stock_low=(v.stock_qty if (threshold > 0 and v.stock_qty <= threshold) else None),
                compare_at_price_clp=v.compare_at_price_clp,
            )
            for v in product.variants
        ],
    )


@router.get("", response_model=list[ProductOut])
def list_products(db: Session = Depends(get_db)) -> list[ProductOut]:
    """Solo productos publicados de categorías visibles. Admin usa
    /api/admin/products para ver todos."""
    hidden = _hidden_categories(db)
    q = db.query(Product).filter(Product.is_published == True)  # noqa: E712
    if hidden:
        q = q.filter(Product.category.notin_(hidden))
    threshold = _low_stock_threshold(db)
    return [_to_out(p, threshold) for p in q.order_by(Product.featured.desc(), Product.name).all()]


@router.get("/{slug}", response_model=ProductOut)
def get_product(slug: str, db: Session = Depends(get_db)) -> ProductOut:
    product = (
        db.query(Product)
        .filter(Product.slug == slug, Product.is_published == True)  # noqa: E712
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    if product.category in _hidden_categories(db):
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return _to_out(product, _low_stock_threshold(db))
