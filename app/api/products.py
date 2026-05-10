from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Product
from ..schemas import ProductOut

router = APIRouter(prefix="/api/products", tags=["products"])


@router.get("", response_model=list[ProductOut])
def list_products(db: Session = Depends(get_db)) -> list[Product]:
    """Solo productos publicados. Admin usa /api/admin/products para ver todos."""
    return (
        db.query(Product)
        .filter(Product.is_published == True)  # noqa: E712
        .order_by(Product.featured.desc(), Product.name)
        .all()
    )


@router.get("/{slug}", response_model=ProductOut)
def get_product(slug: str, db: Session = Depends(get_db)) -> Product:
    product = (
        db.query(Product)
        .filter(Product.slug == slug, Product.is_published == True)  # noqa: E712
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return product
