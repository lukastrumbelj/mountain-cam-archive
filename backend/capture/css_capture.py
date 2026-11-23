from __future__ import annotations

from ..config import Camera
from .browser_capture import run_browser


def capture(cam: Camera, settings: dict) -> bytes:
    """Način selector: Playwright zajame samo element s CSS selektorjem."""
    return run_browser(cam, settings, element=True)
