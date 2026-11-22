from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

from ..config import Camera
from . import browser_capture, css_capture, direct_image
from .errors import CaptureError
from .validate import validate_image


@dataclass
class CaptureResult:
    camera_id: str
    ok: bool
    data: bytes | None = None
    width: int = 0
    height: int = 0
    size: int = 0
    error: str | None = None
    stage: str | None = None
    captured_at_utc: datetime | None = None
    duration_s: float = 0.0


def _raw_capture(cam: Camera, settings: dict) -> bytes:
    if cam.mode == "direct":
        return direct_image.fetch(cam, settings)
    if cam.mode == "selector":
        return css_capture.capture(cam, settings)
    if cam.mode in ("screenshot", "custom"):
        return browser_capture.capture(cam, settings)
    raise CaptureError(f"neznan mode {cam.mode}", "capture")


def capture_camera(cam: Camera, settings: dict) -> CaptureResult:
    """Zajame in validira sliko ene kamere. Nikoli ne vrže izjeme: napaka je v rezultatu."""
    t0 = time.monotonic()
    try:
        raw = _raw_capture(cam, settings)
        captured_at = datetime.now(timezone.utc)
        img = validate_image(raw, settings)
        return CaptureResult(
            cam.id, True, img.data, img.width, img.height, img.size,
            captured_at_utc=captured_at, duration_s=time.monotonic() - t0,
        )
    except CaptureError as e:
        return CaptureResult(cam.id, False, error=str(e), stage=e.stage,
                             duration_s=time.monotonic() - t0)
    except Exception as e:  # nepričakovana napaka ene kamere ne sme ustaviti ostalih
        return CaptureResult(cam.id, False, error=f"{type(e).__name__}: {e}", stage="capture",
                             duration_s=time.monotonic() - t0)


def capture_all(cams: list[Camera], settings: dict) -> list[CaptureResult]:
    return [capture_camera(c, settings) for c in cams if c.active]
