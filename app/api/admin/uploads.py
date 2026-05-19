"""Endpoint genérico de upload de imágenes para admin.

Útil para forms donde la imagen no está atada a un campo específico de un
modelo (ej. cover del Post, brochures, attachments). El cliente sube,
recibe la URL `/uploads/<filename>` y la pega en el campo que corresponda.
"""
import re
import secrets
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from ...seed import UPLOADS_DIR
from ...services.auth import require_admin

router = APIRouter(prefix="/uploads", dependencies=[Depends(require_admin)])

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB


class UploadOut(BaseModel):
    url: str  # ej. "/uploads/cover-1747000000.png"
    filename: str
    size_bytes: int


@router.post("", response_model=UploadOut)
async def upload_image(file: UploadFile = File(...)) -> UploadOut:
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="Formato no soportado (jpg/png/webp)")

    contents = await file.read()
    if len(contents) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Imagen demasiado grande (máx 5 MB)")

    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[file.content_type]
    # Base: nombre original del archivo (sanitizado) + timestamp + 6 chars hex
    # para evitar colisión entre dos uploads en el mismo segundo.
    raw_base = Path(file.filename or "upload").stem
    safe_base = re.sub(r"[^a-z0-9-]+", "-", raw_base.lower()).strip("-") or "upload"
    filename = f"{safe_base}-{int(time.time())}-{secrets.token_hex(3)}{ext}"
    target = Path(UPLOADS_DIR) / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(contents)

    return UploadOut(url=f"/uploads/{filename}", filename=filename, size_bytes=len(contents))
