from __future__ import annotations

from ..config import Camera
from .errors import CaptureError

_BLOCK_MARKERS = ("g-recaptcha", "h-captcha", "cf-challenge", "captcha", "access denied")


def _run_steps(page, steps: list[dict]) -> None:
    """Dovoljeni koraki: click (npr. piškotki), wait (sekunde), hide (CSS selektor)."""
    for step in steps or []:
        if "click" in step:
            try:
                page.locator(step["click"]).first.click(timeout=5000)
            except Exception:
                pass  # npr. pasica piškotkov ni prikazana
        elif "wait" in step:
            page.wait_for_timeout(int(float(step["wait"]) * 1000))
        elif "hide" in step:
            page.add_style_tag(content=f"{step['hide']}{{display:none!important}}")


def run_browser(cam: Camera, settings: dict, element: bool) -> bytes:
    from playwright.sync_api import TimeoutError as PWTimeout
    from playwright.sync_api import sync_playwright

    extra = cam.extra
    timeout = int(settings["timeout_seconds"] * 1000)
    quality = settings["jpeg_quality"]
    viewport = extra.get("viewport") or {"width": 1280, "height": 800}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            ctx = browser.new_context(
                user_agent=settings["user_agent"],
                viewport=viewport,
                locale="sl-SI",
                timezone_id=settings["timezone"],
            )
            page = ctx.new_page()
            try:
                resp = page.goto(cam.url, wait_until="domcontentloaded", timeout=timeout)
            except PWTimeout:
                raise CaptureError("stran ni dosegljiva (timeout)", "reachable")
            except Exception as e:
                raise CaptureError(f"stran ni dosegljiva: {e}", "reachable")
            if resp is None or resp.status >= 400:
                raise CaptureError(f"HTTP {resp.status if resp else '?'}", "reachable")

            _run_steps(page, extra.get("steps"))
            if cam.wait_seconds:
                page.wait_for_timeout(int(cam.wait_seconds * 1000))

            html = page.content().lower()
            if any(m in html for m in _BLOCK_MARKERS):
                raise CaptureError("zaznana zaščita/CAPTCHA, kamera preskočena", "blocked")

            if element and cam.selector:
                loc = page.locator(cam.selector).first
                try:
                    loc.wait_for(state="visible", timeout=10000)
                except PWTimeout:
                    raise CaptureError(f"element '{cam.selector}' ni najden", "element")
                return loc.screenshot(type="jpeg", quality=quality)

            return page.screenshot(
                type="jpeg",
                quality=quality,
                full_page=bool(extra.get("full_page", False)),
                clip=extra.get("clip"),
            )
        finally:
            browser.close()


def capture(cam: Camera, settings: dict) -> bytes:
    """Načina screenshot in custom."""
    return run_browser(cam, settings, element=bool(cam.selector))
