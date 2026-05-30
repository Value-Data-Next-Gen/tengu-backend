"""Admin para los leads B2B / Mayorista (HorecaLead).

Sin esto los leads del form de /horeca quedan solo en la DB + un email al
admin (que no sale si SMTP no está configurado). Acá se ven, se marcan como
contactados y se les agrega notas."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import HorecaLead
from ...services.auth import require_admin

router = APIRouter(prefix="/horeca-leads", dependencies=[Depends(require_admin)])


class HorecaLeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    company: str
    contact_name: str
    email: str
    phone: str
    city: str | None
    business_type: str | None
    kg_per_month: str | None
    machine_type: str | None
    message: str | None
    contacted_at: datetime | None
    notes: str | None
    created_at: datetime


class HorecaLeadPatch(BaseModel):
    contacted: bool | None = None
    notes: str | None = Field(default=None, max_length=1000)


@router.get("", response_model=list[HorecaLeadOut])
def list_leads(status: str | None = None, db: Session = Depends(get_db)) -> list[HorecaLead]:
    """Lista los leads más recientes primero. status='pending' (sin contactar)
    o status='contacted' filtra; sin status devuelve todos."""
    q = db.query(HorecaLead)
    if status == "pending":
        q = q.filter(HorecaLead.contacted_at.is_(None))
    elif status == "contacted":
        q = q.filter(HorecaLead.contacted_at.isnot(None))
    return q.order_by(HorecaLead.created_at.desc()).all()


@router.patch("/{lead_id}", response_model=HorecaLeadOut)
def update_lead(lead_id: int, payload: HorecaLeadPatch, db: Session = Depends(get_db)) -> HorecaLead:
    lead = db.get(HorecaLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    if payload.contacted is not None:
        # Marcar/desmarcar contactado. Al marcar, sella la fecha; al desmarcar, la limpia.
        lead.contacted_at = datetime.now(timezone.utc) if payload.contacted else None
    if payload.notes is not None:
        lead.notes = payload.notes or None
    db.commit()
    db.refresh(lead)
    return lead


@router.delete("/{lead_id}", status_code=204)
def delete_lead(lead_id: int, db: Session = Depends(get_db)) -> None:
    lead = db.get(HorecaLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    db.delete(lead)
    db.commit()
