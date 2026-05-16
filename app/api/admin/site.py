"""Admin CRUD para site settings + shipping rates + comuna zones."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import ComunaZone, ShippingRate
from ...schemas import (
    ComunaZoneIn,
    ComunaZoneOut,
    ShippingRateOut,
    ShippingRatePatch,
    SiteSettingsOut,
    SiteSettingsPatch,
)
from ...services.auth import require_admin
from ...services.shipping import get_settings

router = APIRouter(prefix="/site", dependencies=[Depends(require_admin)])


# --- Settings ---


@router.get("/settings", response_model=SiteSettingsOut)
def get_admin_settings(db: Session = Depends(get_db)) -> SiteSettingsOut:
    return get_settings(db)


@router.patch("/settings", response_model=SiteSettingsOut)
def patch_settings(
    patch: SiteSettingsPatch, db: Session = Depends(get_db)
) -> SiteSettingsOut:
    s = get_settings(db)
    for field, value in patch.model_dump(exclude_unset=True).items():
        setattr(s, field, value)
    db.commit()
    db.refresh(s)
    return s


# --- Shipping rates ---


@router.get("/shipping-rates", response_model=list[ShippingRateOut])
def list_rates(db: Session = Depends(get_db)) -> list[ShippingRate]:
    return (
        db.query(ShippingRate)
        .order_by(ShippingRate.mode, ShippingRate.size_band, ShippingRate.zone)
        .all()
    )


@router.patch("/shipping-rates/{rate_id}", response_model=ShippingRateOut)
def patch_rate(
    rate_id: int, patch: ShippingRatePatch, db: Session = Depends(get_db)
) -> ShippingRate:
    rate = db.get(ShippingRate, rate_id)
    if not rate:
        raise HTTPException(status_code=404, detail="Tarifa no encontrada")
    rate.price_clp = patch.price_clp
    db.commit()
    db.refresh(rate)
    return rate


# --- Comuna zones ---


@router.get("/comuna-zones", response_model=list[ComunaZoneOut])
def list_zones(db: Session = Depends(get_db)) -> list[ComunaZone]:
    return db.query(ComunaZone).order_by(ComunaZone.region, ComunaZone.comuna).all()


@router.post("/comuna-zones", response_model=ComunaZoneOut, status_code=201)
def create_zone(payload: ComunaZoneIn, db: Session = Depends(get_db)) -> ComunaZone:
    row = ComunaZone(
        region=payload.region.strip(),
        comuna=payload.comuna.strip() if payload.comuna else None,
        zone=payload.zone,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/comuna-zones/{zone_id}", response_model=ComunaZoneOut)
def patch_zone(
    zone_id: int, payload: ComunaZoneIn, db: Session = Depends(get_db)
) -> ComunaZone:
    row = db.get(ComunaZone, zone_id)
    if not row:
        raise HTTPException(status_code=404, detail="Mapeo no encontrado")
    row.region = payload.region.strip()
    row.comuna = payload.comuna.strip() if payload.comuna else None
    row.zone = payload.zone
    db.commit()
    db.refresh(row)
    return row


@router.delete("/comuna-zones/{zone_id}", status_code=204)
def delete_zone(zone_id: int, db: Session = Depends(get_db)) -> None:
    row = db.get(ComunaZone, zone_id)
    if not row:
        raise HTTPException(status_code=404, detail="Mapeo no encontrado")
    db.delete(row)
    db.commit()
