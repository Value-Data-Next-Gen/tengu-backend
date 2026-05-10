"""Reseñas de productos. Pública para leer aprobadas + POST con moderación."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Product, Review
from ..schemas import ReviewIn, ReviewOut, ReviewSummary

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


@router.get("/{product_slug}", response_model=list[ReviewOut])
def list_reviews(product_slug: str, db: Session = Depends(get_db)) -> list[Review]:
    return (
        db.query(Review)
        .filter(Review.product_slug == product_slug, Review.status == "approved")
        .order_by(Review.created_at.desc())
        .all()
    )


@router.get("/{product_slug}/summary", response_model=ReviewSummary)
def review_summary(product_slug: str, db: Session = Depends(get_db)) -> ReviewSummary:
    rows = (
        db.query(func.count(Review.id), func.avg(Review.rating))
        .filter(Review.product_slug == product_slug, Review.status == "approved")
        .first()
    )
    count = int(rows[0] or 0)
    avg = round(float(rows[1] or 0), 1)
    return ReviewSummary(count=count, average=avg)


@router.post("", response_model=ReviewOut, status_code=201)
def submit_review(payload: ReviewIn, db: Session = Depends(get_db)) -> Review:
    product = db.query(Product).filter(Product.slug == payload.product_slug).first()
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    review = Review(
        product_slug=payload.product_slug,
        customer_name=payload.customer_name.strip(),
        customer_email=payload.customer_email.lower(),
        rating=payload.rating,
        title=payload.title,
        body=payload.body.strip(),
        status="pending",
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review
