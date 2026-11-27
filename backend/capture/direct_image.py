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
    for attempt in range(2):
        try:
            r = httpx.get(
                cam.image_url,
                headers=headers,
                timeout=httpx.Timeout(settings["timeout_seconds"], connect=8.0),
                follow_redirects=True,
            )
        except httpx.ConnectTimeout as e:  # strežnik se ne odziva: ponavljanje ne pomaga
            raise CaptureError(f"vir ni dosegljiv: ConnectTimeout: {e}", "reachable")
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
        time.sleep(1.5)
    raise CaptureError(f"vir ni dosegljiv: {last}", "reachable")
