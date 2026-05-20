"""One-shot: baja las imágenes PNG de productos desde producción, las
convierte a WebP q=82 con resize a 1200px, y las re-sube vía POST
/api/admin/products/{slug}/image. La DB queda con .webp como filename.

Hace el trabajo pesado (Pillow) localmente para no tocar el container Azure.

Uso:
  cd backend
  .venv\\Scripts\\python.exe scripts\\optimize_product_images.py

Requiere Pillow local (pip install Pillow) y variables ADMIN_EMAIL/
ADMIN_PASSWORD en el entorno o en .env.
"""
import os
import sys
from io import BytesIO

import requests
from dotenv import dotenv_values
from PIL import Image

ROOT = "C:/Users/Gonzalo/Desktop/Value Data Projects/coffe ecommerce/backend"
BACKEND_URL = "https://tengu-backend.azurewebsites.net"

env = dotenv_values(f"{ROOT}/.env")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL") or env.get("ADMIN_EMAILS", "").split(",")[0].strip() or "g.rojaschacon@gmail.com"
# Priorizamos env de shell para inyectar el password real de prod (el de
# .env local puede ser uno de dev distinto al de Azure App Settings).
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD") or env.get("ADMIN_PASSWORD")
if not ADMIN_PASSWORD:
    sys.exit("Falta ADMIN_PASSWORD en .env o env")

MAX_DIM = 1200
QUALITY = 82
SIZE_THRESHOLD = 300 * 1024


def recode(png_bytes: bytes) -> bytes:
    im = Image.open(BytesIO(png_bytes))
    if im.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        rgba = im.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[-1])
        im = bg
    elif im.mode != "RGB":
        im = im.convert("RGB")
    im.thumbnail((MAX_DIM, MAX_DIM), Image.LANCZOS)
    out = BytesIO()
    im.save(out, format="WEBP", quality=QUALITY, method=6)
    return out.getvalue()


def main() -> None:
    # 1) Login
    r = requests.post(
        f"{BACKEND_URL}/api/admin/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=30,
    )
    r.raise_for_status()
    jwt = r.json()["jwt"]
    H = {"Authorization": f"Bearer {jwt}"}

    # 2) Lista de productos admin (incluye image filename y is_published)
    r = requests.get(f"{BACKEND_URL}/api/admin/products", headers=H, timeout=30)
    r.raise_for_status()
    products = r.json()
    print(f"Productos: {len(products)}")

    total_before = 0
    total_after = 0
    skipped: list[str] = []
    results: list[tuple[str, int, int]] = []
    errors: list[tuple[str, str]] = []

    for p in products:
        slug = p["slug"]
        img = p.get("image")
        if not img:
            skipped.append(f"{slug} (sin imagen)")
            continue
        if img.lower().endswith(".webp"):
            skipped.append(f"{slug} (ya .webp)")
            continue
        # Bajar
        r = requests.get(f"{BACKEND_URL}/uploads/{img}", timeout=60)
        if r.status_code != 200:
            errors.append((slug, f"GET {img} → {r.status_code}"))
            continue
        size_before = len(r.content)
        if size_before < SIZE_THRESHOLD:
            skipped.append(f"{slug} ({size_before:,}B ya chica)")
            continue
        # Recodificar
        try:
            webp_bytes = recode(r.content)
        except Exception as e:
            errors.append((slug, f"recode error: {e}"))
            continue
        size_after = len(webp_bytes)
        # Subir
        files = {"file": (f"{slug}.webp", webp_bytes, "image/webp")}
        r = requests.post(
            f"{BACKEND_URL}/api/admin/products/{slug}/image",
            headers=H, files=files, timeout=60,
        )
        if r.status_code != 200:
            errors.append((slug, f"POST upload → {r.status_code} {r.text[:120]}"))
            continue
        new_image = r.json().get("image", "?")
        results.append((slug, size_before, size_after))
        total_before += size_before
        total_after += size_after
        print(f"  {slug}: {size_before:>9,} -> {size_after:>7,} ({100*size_after//size_before}%) -> {new_image}")

    print("\n" + "=" * 60)
    print(f"OPTIMIZADAS: {len(results)} productos")
    if total_before:
        print(f"TOTAL: {total_before/1024:,.0f} KB -> {total_after/1024:,.0f} KB "
              f"({100 - 100*total_after//total_before}% menos)")
    if skipped:
        print(f"SKIPPED: {len(skipped)}")
        for s in skipped:
            print(f"  - {s}")
    if errors:
        print(f"ERRORS: {len(errors)}")
        for slug, msg in errors:
            print(f"  - {slug}: {msg}")
    print("=" * 60)


if __name__ == "__main__":
    main()
