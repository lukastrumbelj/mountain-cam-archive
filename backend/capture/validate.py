from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageStat, UnidentifiedImageError

from .errors import CaptureError


@dataclass
class ValidImage:
    data: bytes  # JPEG
    width: int
    height: int

    @property
    def size(self) -> int:
        return len(self.data)


def validate_image(data: bytes, settings: dict) -> ValidImage:
    """Preveri sliko; vrne JPEG. Original JPEG ostane nespremenjen (brez izgube kakovosti)."""
    if len(data) < 3000:
        raise CaptureError(f"slika je premajhna ({len(data)} B)", "invalid")
    if data.lstrip()[:1] == b"<":
        raise CaptureError("odgovor je HTML, ne slika", "invalid")
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, SyntaxError) as e:
        raise CaptureError(f"poškodovana ali neveljavna slika: {e}", "invalid")

    w, h = img.size
    if w < settings["min_width"] or h < settings["min_height"]:
        raise CaptureError(f"slika je premajhna ({w}x{h})", "invalid")

    stat = ImageStat.Stat(img.convert("L"))
    if stat.stddev[0] < 3:
        raise CaptureError("slika je prazna ali enobarvna", "invalid")

    if img.format == "JPEG":
        return ValidImage(data, w, h)

    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=settings["jpeg_quality"], optimize=True)
    return ValidImage(out.getvalue(), w, h)
