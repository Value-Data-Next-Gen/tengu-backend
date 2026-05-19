"""Admin CRUD del blog."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import Post
from ...schemas import PostIn, PostOut, PostPatch
from ...services.auth import require_admin

router = APIRouter(prefix="/posts", dependencies=[Depends(require_admin)])


@router.get("", response_model=list[PostOut])
def list_posts_admin(db: Session = Depends(get_db)) -> list[Post]:
    """Admin ve TODOS los posts (publicados y borradores)."""
    return db.query(Post).order_by(Post.published_at.desc()).all()


@router.get("/{slug}", response_model=PostOut)
def get_post_admin(slug: str, db: Session = Depends(get_db)) -> Post:
    post = db.query(Post).filter(Post.slug == slug).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post no encontrado")
    return post


@router.post("", response_model=PostOut, status_code=201)
def create_post(payload: PostIn, db: Session = Depends(get_db)) -> Post:
    if db.query(Post).filter(Post.slug == payload.slug).first():
        raise HTTPException(status_code=409, detail=f"Ya existe un post con slug '{payload.slug}'")
    post = Post(
        slug=payload.slug,
        title=payload.title,
        excerpt=payload.excerpt,
        meta_description=payload.meta_description,
        cover=payload.cover,
        published_at=payload.published_at,
        reading_minutes=payload.reading_minutes,
        author=payload.author,
        tags=payload.tags,
        body=payload.body,
        is_published=payload.is_published,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


@router.patch("/{slug}", response_model=PostOut)
def update_post(slug: str, payload: PostPatch, db: Session = Depends(get_db)) -> Post:
    post = db.query(Post).filter(Post.slug == slug).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post no encontrado")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(post, field, value)
    db.commit()
    db.refresh(post)
    return post


@router.delete("/{slug}", status_code=204)
def delete_post(slug: str, db: Session = Depends(get_db)) -> None:
    post = db.query(Post).filter(Post.slug == slug).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post no encontrado")
    db.delete(post)
    db.commit()
