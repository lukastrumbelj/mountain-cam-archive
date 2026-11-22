from __future__ import annotations

import time

import httpx

from ..config import Camera
from .errors import CaptureError

# Ponovni poskus samo pri začasnih napakah. 401/403/404 se ne ponavljajo in se ne obhajajo.
_RETRY_STATUS = {429, 500, 502, 503, 504}


def fetch(cam: Camera, settings: dict) -> bytes:
    headers = {"User-Agent": settings["user_agent"], "Accept": "image/*,*/*;q=0.5"}
    headers.update(cam.extra.get("headers") or {})
    last = "neznana napaka"
    for attempt in range(3):
        try:
            r = httpx.get(
                cam.image_url,
                headers=headers,
                timeout=settings["timeout_seconds"],
                follow_redirects=True,
            )
        except httpx.HTTPError as e:
            last = f"{type(e).__name__}: {e}"
        else:
            if r.status_code == 200:
                ctype = r.headers.get("content-type", "").lower()
                if "image" not in ctype and r.content[:3] != b"\xff\xd8\xff":
                    raise CaptureError(f"odgovor ni slika ({ctype or 'brez content-type'})", "invalid")
                return r.content
            last = f"HTTP {r.status_code}"
            if r.status_code not in _RETRY_STATUS:
                raise CaptureError(last, "reachable")
        time.sleep(2 * (attempt + 1))
    raise CaptureError(f"vir ni dosegljiv: {last}", "reachable")
