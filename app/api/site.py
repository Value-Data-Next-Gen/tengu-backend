"""Endpoints públicos para que el frontend lea settings y cotice envíos."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import ShippingQuoteIn, ShippingQuoteOut, SiteSettingsOut
from ..services.shipping import get_settings, quote_shipping

router = APIRouter(prefix="/api/site", tags=["site"])


@router.get("/settings", response_model=SiteSettingsOut)
def public_settings(db: Session = Depends(get_db)) -> SiteSettingsOut:
    """Lo que necesita el frontend para mostrar copy + umbral de envío gratis."""
    return get_settings(db)


shipping_router = APIRouter(prefix="/api/shipping", tags=["shipping"])


@shipping_router.post("/quote", response_model=ShippingQuoteOut)
def quote(payload: ShippingQuoteIn, db: Session = Depends(get_db)) -> ShippingQuoteOut:
    result = quote_shipping(
        db,
        region=payload.region,
        comuna=payload.comuna,
        weight_g=payload.weight_g,
        mode=payload.mode,
        subtotal_clp=payload.subtotal_clp,
    )
    return ShippingQuoteOut(**result)
