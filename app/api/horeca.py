from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import HorecaLead
from ..services.email import send_email

router = APIRouter(prefix="/api/horeca", tags=["horeca"])


class HorecaContactIn(BaseModel):
    company: str = Field(min_length=2, max_length=200)
    contact_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    phone: str = Field(min_length=6, max_length=40)
    city: str | None = Field(default=None, max_length=120)
    business_type: str | None = Field(default=None, max_length=80)
    kg_per_month: str | None = Field(default=None, max_length=40)
    machine_type: str | None = Field(default=None, max_length=120)
    message: str | None = Field(default=None, max_length=1000)


@router.post("/contact", status_code=201)
def submit_horeca_lead(payload: HorecaContactIn, db: Session = Depends(get_db)) -> Response:
    lead = HorecaLead(
        company=payload.company.strip(),
        contact_name=payload.contact_name.strip(),
        email=payload.email.lower(),
        phone=payload.phone.strip(),
        city=payload.city.strip() if payload.city else None,
        business_type=payload.business_type,
        kg_per_month=payload.kg_per_month,
        machine_type=payload.machine_type,
        message=payload.message.strip() if payload.message else None,
    )
    db.add(lead)
    db.commit()

    # Notificar admin (primer admin email configurado)
    admin_to = settings.admin_emails_list[0] if settings.admin_emails_list else None
    if admin_to:
        body = f"""
            <p><strong>Nuevo lead B2B (Horeca)</strong></p>
            <ul>
              <li><strong>Empresa:</strong> {lead.company}</li>
              <li><strong>Contacto:</strong> {lead.contact_name}</li>
              <li><strong>Email:</strong> {lead.email}</li>
              <li><strong>Teléfono:</strong> {lead.phone}</li>
              <li><strong>Ciudad:</strong> {lead.city or '-'}</li>
              <li><strong>Tipo:</strong> {lead.business_type or '-'}</li>
              <li><strong>kg/mes estimado:</strong> {lead.kg_per_month or '-'}</li>
              <li><strong>Máquina:</strong> {lead.machine_type or '-'}</li>
            </ul>
            <p><strong>Mensaje:</strong></p>
            <p>{lead.message or '(sin mensaje)'}</p>
        """
        send_email(admin_to, f"Nuevo lead Horeca · {lead.company}", body)

    return Response(status_code=201)
