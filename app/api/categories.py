"""API pública de categorías. Solo retorna las visibles."""
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Category, Product
from ..schemas import CategoryWithCount

router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.get("", response_model=list[CategoryWithCount])
def list_categories(db: Session = Depends(get_db)) -> list[CategoryWithCount]:
    cats = (
        db.query(Category)
        .filter(Category.is_visible == True)  # noqa: E712
        .order_by(Category.sort_order, Category.name)
        .all()
    )
    counts = dict(
        db.query(Product.category, func.count(Product.id))
        .filter(Product.is_published == True)  # noqa: E712
        .group_by(Product.category)
        .all()
    )
    return [
        CategoryWithCount(
            id=c.id,
            name=c.name,
            description=c.description,
            is_visible=c.is_visible,
            sort_order=c.sort_order,
            product_count=counts.get(c.name, 0),
        )
        for c in cats
    ]
