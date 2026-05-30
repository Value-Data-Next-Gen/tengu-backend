"""Admin CRUD para los slides del carrusel del home (HeroSlide)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import HeroSlide
from ...schemas import HeroSlideAdminOut, HeroSlideIn, HeroSlidePatch
from ...services.auth import require_admin

router = APIRouter(prefix="/hero-slides", dependencies=[Depends(require_admin)])


@router.get("", response_model=list[HeroSlideAdminOut])
def list_slides(db: Session = Depends(get_db)) -> list[HeroSlide]:
    return db.query(HeroSlide).order_by(HeroSlide.sort_order, HeroSlide.id).all()


@router.post("", response_model=HeroSlideAdminOut, status_code=201)
def create_slide(payload: HeroSlideIn, db: Session = Depends(get_db)) -> HeroSlide:
    slide = HeroSlide(**payload.model_dump())
    db.add(slide)
    db.commit()
    db.refresh(slide)
    return slide


@router.patch("/{slide_id}", response_model=HeroSlideAdminOut)
def update_slide(slide_id: int, payload: HeroSlidePatch, db: Session = Depends(get_db)) -> HeroSlide:
    slide = db.get(HeroSlide, slide_id)
    if not slide:
        raise HTTPException(status_code=404, detail="Slide no encontrado")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(slide, field, value)
    db.commit()
    db.refresh(slide)
    return slide


@router.delete("/{slide_id}", status_code=204)
def delete_slide(slide_id: int, db: Session = Depends(get_db)) -> None:
    slide = db.get(HeroSlide, slide_id)
    if not slide:
        raise HTTPException(status_code=404, detail="Slide no encontrado")
    db.delete(slide)
    db.commit()
