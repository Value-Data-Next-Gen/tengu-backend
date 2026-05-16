"""Endpoints públicos para que el frontend lea settings y cotice envíos."""
from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Comuna
from ..schemas import RegionOut, ShippingQuoteIn, ShippingQuoteOut, SiteSettingsOut
from ..services.shipping import get_settings, quote_shipping

router = APIRouter(prefix="/api/site", tags=["site"])


@router.get("/settings", response_model=SiteSettingsOut)
def public_settings(db: Session = Depends(get_db)) -> SiteSettingsOut:
    """Lo que necesita el frontend para mostrar copy + umbral de envío gratis."""
    return get_settings(db)


# Orden norte→sur (no alfabético). Las regiones que no estén en este orden caen al final.
REGION_ORDER = [
    "Arica y Parinacota", "Tarapacá", "Antofagasta", "Atacama", "Coquimbo",
    "Valparaíso", "Región Metropolitana", "O'Higgins", "Maule", "Ñuble",
    "Biobío", "Araucanía", "Los Ríos", "Los Lagos", "Aysén", "Magallanes",
]


@router.get("/regions", response_model=list[RegionOut])
def list_regions(db: Session = Depends(get_db)) -> list[RegionOut]:
    """Árbol región → [comunas] para los selects encadenados del checkout."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for row in db.query(Comuna).order_by(Comuna.region, Comuna.name).all():
        grouped[row.region].append(row.name)
    order_idx = {name: i for i, name in enumerate(REGION_ORDER)}
    sorted_regions = sorted(grouped.keys(), key=lambda r: (order_idx.get(r, 999), r))
    return [RegionOut(name=r, comunas=grouped[r]) for r in sorted_regions]


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
