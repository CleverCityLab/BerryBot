import os
from pathlib import Path
import mimetypes

MEDIA_DIR = Path(os.getenv("MEDIA_DIR", "/app/product_images"))
MEDIA_PUBLIC_ROOT = os.getenv("MEDIA_PUBLIC_ROOT", "product_images")
ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".avif"}


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def ext_from_mime_or_name(mime: str | None, filename: str | None) -> str:
    if filename:
        suf = Path(filename).suffix.lower()
        if suf in ALLOWED_EXTS:
            return suf
    if mime:
        ext = (mimetypes.guess_extension(mime) or "").lower()
        if ext == ".jpe":
            ext = ".jpg"
        if ext in ALLOWED_EXTS:
            return ext
    return ".jpg"
