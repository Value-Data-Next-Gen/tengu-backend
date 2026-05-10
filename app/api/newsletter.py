from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Subscription

router = APIRouter(prefix="/api/newsletter", tags=["newsletter"])


class SubscribeIn(BaseModel):
    email: EmailStr


class SubscribeOut(BaseModel):
    status: str
    message: str


@router.post("", response_model=SubscribeOut, status_code=201)
def subscribe(payload: SubscribeIn, db: Session = Depends(get_db)) -> SubscribeOut:
    email = payload.email.lower()
    sub = Subscription(email=email)
    db.add(sub)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return SubscribeOut(status="already_subscribed", message="Ya estabas inscrito. ¡Gracias!")
    return SubscribeOut(status="subscribed", message="¡Listo! Te avisaremos de los nuevos cafés.")
