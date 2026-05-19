"""Endpoints públicos del blog."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Post
from ..schemas import PostOut

router = APIRouter(prefix="/api/posts", tags=["posts"])


@router.get("", response_model=list[PostOut])
def list_posts(db: Session = Depends(get_db)) -> list[Post]:
    """Lista pública: solo posts publicados, orden descendente por fecha."""
    return (
        db.query(Post)
        .filter(Post.is_published == True)  # noqa: E712
        .order_by(Post.published_at.desc())
        .all()
    )


@router.get("/{slug}", response_model=PostOut)
def get_post(slug: str, db: Session = Depends(get_db)) -> Post:
    post = (
        db.query(Post)
        .filter(Post.slug == slug, Post.is_published == True)  # noqa: E712
        .first()
    )
    if not post:
        raise HTTPException(status_code=404, detail="Post no encontrado")
    return post
