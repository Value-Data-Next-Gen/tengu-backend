from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import Review
from ...schemas import ReviewAdminOut
from ...services.auth import require_admin

router = APIRouter(prefix="/reviews", dependencies=[Depends(require_admin)])


class ReviewModerate(BaseModel):
    status: Literal["pending", "approved", "rejected"] | None = None
    admin_notes: str | None = None


@router.get("", response_model=list[ReviewAdminOut])
def list_reviews(
    status: str | None = None, db: Session = Depends(get_db)
) -> list[Review]:
    q = db.query(Review)
    if status:
        q = q.filter(Review.status == status)
    return q.order_by(Review.created_at.desc()).all()


@router.patch("/{review_id}", response_model=ReviewAdminOut)
def moderate(review_id: int, payload: ReviewModerate, db: Session = Depends(get_db)) -> Review:
    review = db.get(Review, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Reseña no encontrada")
    if payload.status is not None:
        review.status = payload.status
        if payload.status == "approved" and not review.approved_at:
            review.approved_at = datetime.now(timezone.utc)
    if payload.admin_notes is not None:
        review.admin_notes = payload.admin_notes or None
    db.commit()
    db.refresh(review)
    return review


@router.delete("/{review_id}", status_code=204)
def delete_review(review_id: int, db: Session = Depends(get_db)) -> None:
    review = db.get(Review, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Reseña no encontrada")
    db.delete(review)
    db.commit()
