from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Category, Product
from ..schemas import ProductOut

router = APIRouter(prefix="/api/products", tags=["products"])


def _hidden_categories(db: Session) -> set[str]:
    """Categorías con is_visible=False — sus productos se ocultan del público."""
    return {c.name for c in db.query(Category).filter(Category.is_visible == False).all()}  # noqa: E712


@router.get("", response_model=list[ProductOut])
def list_products(db: Session = Depends(get_db)) -> list[Product]:
    """Solo productos publicados de categorías visibles. Admin usa
    /api/admin/products para ver todos."""
    hidden = _hidden_categories(db)
    q = db.query(Product).filter(Product.is_published == True)  # noqa: E712
    if hidden:
        q = q.filter(Product.category.notin_(hidden))
    return q.order_by(Product.featured.desc(), Product.name).all()


@router.get("/{slug}", response_model=ProductOut)
def get_product(slug: str, db: Session = Depends(get_db)) -> Product:
    product = (
        db.query(Product)
        .filter(Product.slug == slug, Product.is_published == True)  # noqa: E712
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    if product.category in _hidden_categories(db):
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return product
