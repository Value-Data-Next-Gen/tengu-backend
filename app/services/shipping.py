"""Cálculo de envío Blue Express desde Rancagua + cotización de site settings.

Las tarifas, zonas y mapeo comuna→zona viven en DB (editables desde /admin).
Si la DB está vacía, se siembra con los valores del tarifario oficial provisto
por el cliente (tarifario_rancagua.xlsx, mayo 2026).
"""
from sqlalchemy.orm import Session

from ..models import ComunaZone, ShippingRate, SiteSettings


# --- Tarifario Blue Express desde Rancagua (mayo 2026) ---
# Origen fijo: Centro (Rancagua, O'Higgins).
# Bandas de peso:
SIZE_BANDS = [
    ("XS", 0, 500),
    ("S", 750, 3000),
    ("M", 3250, 6000),
    ("L", 6250, 20000),
]
# 24 valores = 4 tallas × 3 zonas × 2 modalidades. CLP.
SHIPPING_SEED = [
    # (size, zone, mode, price)
    ("XS", "ohiggins",     "domicilio",  3100), ("XS", "centro_otros", "domicilio",  4300), ("XS", "extremo",      "domicilio",  5200),
    ("S",  "ohiggins",     "domicilio",  4200), ("S",  "centro_otros", "domicilio",  5600), ("S",  "extremo",      "domicilio",  9500),
    ("M",  "ohiggins",     "domicilio",  4800), ("M",  "centro_otros", "domicilio",  7300), ("M",  "extremo",      "domicilio", 14500),
    ("L",  "ohiggins",     "domicilio",  5400), ("L",  "centro_otros", "domicilio",  9200), ("L",  "extremo",      "domicilio", 17000),
    ("XS", "ohiggins",     "punto",      2600), ("XS", "centro_otros", "punto",      3800), ("XS", "extremo",      "punto",      4700),
    ("S",  "ohiggins",     "punto",      3700), ("S",  "centro_otros", "punto",      5100), ("S",  "extremo",      "punto",      9000),
    ("M",  "ohiggins",     "punto",      4300), ("M",  "centro_otros", "punto",      6800), ("M",  "extremo",      "punto",     14000),
    ("L",  "ohiggins",     "punto",      4900), ("L",  "centro_otros", "punto",      8700), ("L",  "extremo",      "punto",     16500),
]

# Mapeo región → zona Blue Express desde Rancagua. Algunas comunas RM caen en
# centro_otros excepto un par "extremas" de la propia RM — admin puede ajustar.
REGION_ZONE_SEED: list[tuple[str, str | None, str]] = [
    ("O'Higgins", None, "ohiggins"),
    ("Región Metropolitana", None, "centro_otros"),
    ("Valparaíso", None, "centro_otros"),
    ("Maule", None, "centro_otros"),
    ("Ñuble", None, "centro_otros"),
    ("Biobío", None, "centro_otros"),
    ("Araucanía", None, "centro_otros"),
    ("Coquimbo", None, "centro_otros"),
    ("Los Ríos", None, "extremo"),
    ("Los Lagos", None, "extremo"),
    ("Aysén", None, "extremo"),
    ("Magallanes", None, "extremo"),
    ("Arica y Parinacota", None, "extremo"),
    ("Tarapacá", None, "extremo"),
    ("Antofagasta", None, "extremo"),
    ("Atacama", None, "extremo"),
]


def ensure_seeded(db: Session) -> None:
    """Idempotente: si no hay rates ni zones, siembra desde los defaults.
    Tampoco toca site_settings si ya existe."""
    if not db.query(SiteSettings).first():
        db.add(SiteSettings())
    if not db.query(ShippingRate).first():
        bands_by_size = {s: (mn, mx) for s, mn, mx in SIZE_BANDS}
        for size, zone, mode, price in SHIPPING_SEED:
            mn, mx = bands_by_size[size]
            db.add(ShippingRate(
                size_band=size, zone=zone, mode=mode,
                weight_min_g=mn, weight_max_g=mx, price_clp=price,
            ))
    if not db.query(ComunaZone).first():
        for region, comuna, zone in REGION_ZONE_SEED:
            db.add(ComunaZone(region=region, comuna=comuna, zone=zone))
    db.commit()


def get_settings(db: Session) -> SiteSettings:
    """Devuelve la fila singleton, creándola si no existe."""
    s = db.query(SiteSettings).first()
    if not s:
        s = SiteSettings()
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


def resolve_zone(db: Session, region: str, comuna: str | None) -> str:
    """Comuna exacta gana sobre región. Default = extremo (lo más caro,
    nunca underchargeás por error)."""
    if comuna:
        row = (
            db.query(ComunaZone)
            .filter(ComunaZone.region == region, ComunaZone.comuna == comuna)
            .first()
        )
        if row:
            return row.zone
    row = (
        db.query(ComunaZone)
        .filter(ComunaZone.region == region, ComunaZone.comuna.is_(None))
        .first()
    )
    return row.zone if row else "extremo"


def resolve_size_band(weight_g: int) -> str:
    """Talla por peso. Si supera el máximo de L, devuelve L igual (capamos)."""
    for size, _, max_g in SIZE_BANDS:
        if weight_g <= max_g:
            return size
    return "L"


def quote_shipping(
    db: Session,
    region: str,
    comuna: str | None,
    weight_g: int,
    mode: str,
    subtotal_clp: int,
) -> dict:
    """Cotización end-to-end. Aplica envío gratis sobre el umbral del settings."""
    settings_row = get_settings(db)
    if subtotal_clp >= settings_row.free_shipping_threshold_clp > 0:
        return {
            "cost_clp": 0,
            "zone": resolve_zone(db, region, comuna),
            "size_band": resolve_size_band(weight_g),
            "is_free": True,
            "reason": f"Envío gratis sobre ${settings_row.free_shipping_threshold_clp:,.0f}".replace(",", "."),
        }

    zone = resolve_zone(db, region, comuna)
    band = resolve_size_band(weight_g)
    rate = (
        db.query(ShippingRate)
        .filter(
            ShippingRate.size_band == band,
            ShippingRate.zone == zone,
            ShippingRate.mode == mode,
        )
        .first()
    )
    if not rate:
        # Fallback raro: no debería pasar si está bien seedeado.
        return {
            "cost_clp": 0,
            "zone": zone,
            "size_band": band,
            "is_free": False,
            "reason": "Tarifa no disponible, coordinamos por WhatsApp",
        }
    return {
        "cost_clp": rate.price_clp,
        "zone": zone,
        "size_band": band,
        "is_free": False,
        "reason": f"Banda {band} · zona {zone} · {mode}",
    }
