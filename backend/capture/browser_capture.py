from __future__ import annotations

import base64

from ..config import Camera
from .errors import CaptureError

_BLOCK_MARKERS = ("g-recaptcha", "h-captcha", "cf-challenge", "captcha", "access denied")

_JS_PLAY = "v => { v.muted = true; const p = v.play(); if (p && p.catch) p.catch(() => {}); }"
_JS_READY = "v => v.readyState >= 2 && v.videoWidth > 0"
# Trenutni frame v izvorni ločljivosti (brez kontrolnikov predvajalnika).
_JS_FRAME = """(v, q) => {
  const c = document.createElement('canvas');
  c.width = v.videoWidth; c.height = v.videoHeight;
  c.getContext('2d').drawImage(v, 0, 0);
  return c.toDataURL('image/jpeg', q);
}"""


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


def _launch(p, video: bool):
    args = ["--autoplay-policy=no-user-gesture-required"]
    if video:
        # Playwrightov Chromium nima H.264; Google Chrome (na GitHub runnerjih že nameščen) ga ima.
        try:
            return p.chromium.launch(channel="chrome", args=args)
        except Exception:
            pass
    return p.chromium.launch(args=args)


def _capture_video(page, cam: Camera, settings: dict, quality: int) -> bytes:
    from playwright.sync_api import TimeoutError as PWTimeout

    root = page.frame_locator(cam.extra["frame"]) if cam.extra.get("frame") else page
    loc = root.locator(cam.selector or "video").first
    try:
        loc.wait_for(state="attached", timeout=10000)
    except PWTimeout:
        raise CaptureError(f"video element '{cam.selector or 'video'}' ni najden", "element")

    loc.evaluate(_JS_PLAY)
    for _ in range(int(max(settings["timeout_seconds"], 15) * 2)):  # korak 0,5 s
        if loc.evaluate(_JS_READY):
            break
        page.wait_for_timeout(500)
    else:
        raise CaptureError("video se ne predvaja (ni slike)", "capture")
    page.wait_for_timeout(1000)  # svež frame po zagonu

    try:
        data_url = loc.evaluate(_JS_FRAME, quality / 100)
        return base64.b64decode(data_url.split(",", 1)[1])
    except Exception:  # npr. SecurityError (video z drugega vira brez CORS): posnetek elementa
        return loc.screenshot(type="jpeg", quality=quality)


def run_browser(cam: Camera, settings: dict, element: bool, video: bool = False) -> bytes:
    from playwright.sync_api import TimeoutError as PWTimeout
    from playwright.sync_api import sync_playwright

    extra = cam.extra
    timeout = int(settings["timeout_seconds"] * 1000)
    quality = settings["jpeg_quality"]
    viewport = extra.get("viewport") or {"width": 1280, "height": 800}

    with sync_playwright() as p:
        browser = _launch(p, video)
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

            if video:
                return _capture_video(page, cam, settings, quality)

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


def capture_video(cam: Camera, settings: dict) -> bytes:
    """Način video: trenutni frame iz <video> (neobvezno v iframe: extra.frame)."""
    return run_browser(cam, settings, element=False, video=True)
