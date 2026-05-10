import csv
import io

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import Subscription
from ...services.auth import require_admin

router = APIRouter(prefix="/subscriptions", dependencies=[Depends(require_admin)])


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    created_at: str

    @classmethod
    def from_model(cls, m: Subscription) -> "SubscriptionOut":
        return cls(id=m.id, email=m.email, created_at=m.created_at.isoformat())


@router.get("", response_model=list[SubscriptionOut])
def list_subscriptions(db: Session = Depends(get_db)) -> list[SubscriptionOut]:
    rows = db.query(Subscription).order_by(Subscription.created_at.desc()).all()
    return [SubscriptionOut.from_model(r) for r in rows]


@router.get("/export.csv")
def export_csv(db: Session = Depends(get_db)) -> StreamingResponse:
    rows = db.query(Subscription).order_by(Subscription.created_at.asc()).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["email", "created_at"])
    for r in rows:
        writer.writerow([r.email, r.created_at.isoformat()])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="suscriptores-tengu.csv"'},
    )
