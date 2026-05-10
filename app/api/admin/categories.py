from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import Category, Product
from ...schemas import CategoryIn, CategoryPatch, CategoryWithCount
from ...services.auth import require_admin

router = APIRouter(prefix="/categories", dependencies=[Depends(require_admin)])


def _with_count(cat: Category, count: int) -> CategoryWithCount:
    return CategoryWithCount(
        id=cat.id,
        name=cat.name,
        description=cat.description,
        is_visible=cat.is_visible,
        sort_order=cat.sort_order,
        product_count=count,
    )


@router.get("", response_model=list[CategoryWithCount])
def list_all(db: Session = Depends(get_db)) -> list[CategoryWithCount]:
    cats = db.query(Category).order_by(Category.sort_order, Category.name).all()
    counts = dict(
        db.query(Product.category, func.count(Product.id)).group_by(Product.category).all()
    )
    return [_with_count(c, counts.get(c.name, 0)) for c in cats]


@router.post("", response_model=CategoryWithCount, status_code=201)
def create_category(payload: CategoryIn, db: Session = Depends(get_db)) -> CategoryWithCount:
    existing = db.query(Category).filter(Category.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Ya existe categoría '{payload.name}'")
    cat = Category(
        name=payload.name,
        description=payload.description,
        is_visible=payload.is_visible,
        sort_order=payload.sort_order,
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return _with_count(cat, 0)


@router.patch("/{category_id}", response_model=CategoryWithCount)
def update_category(
    category_id: int, payload: CategoryPatch, db: Session = Depends(get_db)
) -> CategoryWithCount:
    cat = db.get(Category, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Categoría no encontrada")
    old_name = cat.name
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(cat, field, value)
    # Si se renombra, actualizar todos los productos
    if payload.name is not None and payload.name != old_name:
        db.query(Product).filter(Product.category == old_name).update(
            {Product.category: payload.name}
        )
    db.commit()
    db.refresh(cat)
    count = db.query(func.count(Product.id)).filter(Product.category == cat.name).scalar() or 0
    return _with_count(cat, count)


@router.delete("/{category_id}", status_code=204)
def delete_category(category_id: int, db: Session = Depends(get_db)) -> None:
    cat = db.get(Category, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Categoría no encontrada")
    count = db.query(func.count(Product.id)).filter(Product.category == cat.name).scalar() or 0
    if count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"No se puede borrar '{cat.name}': tiene {count} productos. Reasigna o borra los productos primero.",
        )
    db.delete(cat)
    db.commit()
