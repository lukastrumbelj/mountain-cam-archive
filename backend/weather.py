"""Dnevni posnetek ARSO napovedi za hribe (JPG) -> R2.

    python -m backend.weather --local out/archive          # brez R2 (test)
    python -m backend.weather                              # R2 (okoljske spremenljivke R2_*)
    python -m backend.weather --only karavanke
    python -m backend.weather --require-slot --tolerance 30   # samo če je ura blizu settings.time

R2:  weather/YYYY/MM/DD/{id}.jpg   slika
     meta/weather.json             {regions, days: {YYYY-MM-DD: {id: zapis}}}
Največ ena slika na regijo na dan (ponovni zagon isti dan jo prepiše; napaka nikoli ne prepiše uspešnega).
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.robotparser
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
import yaml
from PIL import Image

from .capture.errors import CaptureError
from .capture.validate import validate_image
from .config import DEFAULTS
from .metadata import metadata_manager as mm
from .storage.r2_storage import LocalStorage, R2Storage
from .timeutil import nearest_slot

WEATHER_KEY = "meta/weather.json"
W_DEFAULTS = {"time": "12:00", "retention_days": 7, "viewport_width": 1900, "jpeg_quality": 85,
              "timeout_seconds": 40}


def load_weather_config(path) -> tuple[dict, list[dict]]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    st = {**DEFAULTS, **W_DEFAULTS, **(raw.get("settings") or {})}
    pages, seen = [], set()
    for p in raw.get("pages") or []:
        pid = str(p.get("id", ""))
        if not pid or not all(c.islower() or c.isdigit() or c == "-" for c in pid):
            raise ValueError(f"neveljaven id: {pid!r}")
        if pid in seen:
            raise ValueError(f"podvojen id: {pid}")
        if not str(p.get("url", "")).startswith(("http://", "https://")):
            raise ValueError(f"[{pid}] url mora biti http(s)")
        seen.add(pid)
        pages.append({"id": pid, "name": p.get("name") or pid, "url": p["url"]})
    return st, pages


def image_key(pid: str, d: date) -> str:
    return f"weather/{d:%Y}/{d:%m}/{d:%d}/{pid}.jpg"


def robots_checker(urls: list[str], user_agent: str):
    """Prebere robots.txt vsakega gostitelja (prek httpx). Vrne can_fetch(url).
    Če robots.txt ni berljiv (napaka omrežja, 5xx), vrže izjemo: raje nič kot kršitev."""
    parsers = {}
    for u in urls:
        host = urlparse(u)
        base = f"{host.scheme}://{host.netloc}"
        if base in parsers:
            continue
        rp = urllib.robotparser.RobotFileParser()
        r = httpx.get(base + "/robots.txt", headers={"User-Agent": user_agent}, timeout=20, follow_redirects=True)
        if r.status_code == 200:
            rp.parse(r.text.splitlines())
        elif r.status_code in (404, 410):
            rp.parse([])
        else:
            raise RuntimeError(f"robots.txt {base}: HTTP {r.status_code}")
        parsers[base] = rp

    def can_fetch(url: str) -> bool:
        h = urlparse(url)
        return parsers[f"{h.scheme}://{h.netloc}"].can_fetch(user_agent, url)
    return can_fetch


def screenshot_pages(pages: list[dict], st: dict) -> dict[str, bytes | CaptureError]:
    """Posname vse strani z enim brskalnikom. Vrne {id: JPEG bytes | CaptureError}."""
    from playwright.sync_api import Error as PWError
    from playwright.sync_api import TimeoutError as PWTimeout
    from playwright.sync_api import sync_playwright

    out: dict = {}
    timeout = int(st["timeout_seconds"] * 1000)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": int(st["viewport_width"]), "height": 900},
                                  user_agent=st["user_agent"], locale="sl-SI",
                                  timezone_id=st["timezone"], device_scale_factor=1)
        for pg in pages:
            page = ctx.new_page()
            try:
                resp = page.goto(pg["url"], wait_until="load", timeout=timeout)
                if resp is None or resp.status != 200:
                    raise CaptureError(f"HTTP {resp.status if resp else '?'}", "reachable")
                try:  # ikone se naložijo po load; ne čakamo v nedogled
                    page.wait_for_load_state("networkidle", timeout=8000)
                except PWTimeout:
                    pass
                if page.locator("table").count() == 0 and len(page.inner_text("body").strip()) < 200:
                    raise CaptureError("stran je prazna (brez tabele/besedila)", "invalid")
                png = page.screenshot(full_page=True, type="png", timeout=timeout)
                out[pg["id"]] = validate_image(png, st).data
            except CaptureError as e:
                out[pg["id"]] = e
            except (PWTimeout, PWError) as e:
                out[pg["id"]] = CaptureError(f"{type(e).__name__}: {str(e).splitlines()[0][:150]}", "reachable")
            finally:
                page.close()
        browser.close()
    return out


def run_weather(pages, st, storage, shots, now_utc: datetime | None = None) -> list[dict]:
    """Shrani posnetke in posodobi meta/weather.json. `shots` = izhod screenshot_pages."""
    now = now_utc or datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo(st["timezone"])).date()
    raw = storage.get(WEATHER_KEY)
    meta = json.loads(raw) if raw else {}
    meta.setdefault("days", {})
    meta["version"] = 1
    meta["regions"] = {p["id"]: {"name": p["name"], "url": p["url"]} for p in pages}
    day = meta["days"].setdefault(today.isoformat(), {})
    report = []
    for pg in pages:
        res = shots.get(pg["id"])
        if res is None:
            continue
        prev = day.get(pg["id"])
        if isinstance(res, bytes):
            key = image_key(pg["id"], today)
            try:
                storage.put(key, res, "image/jpeg", mm.IMG_CACHE)
                w, h = Image.open(io.BytesIO(res)).size
                day[pg["id"]] = {"path": key, "captured_at_utc": mm.iso(now), "size": len(res),
                                 "width": w, "height": h, "status": "ok", "error": None}
                report.append({"id": pg["id"], "ok": True, "error": None})
                continue
            except Exception as e:
                res = CaptureError(f"shranjevanje: {type(e).__name__}: {e}", "storage")
        if not (prev and prev.get("status") == "ok"):  # uspešen zapis se ne prepiše z napako
            day[pg["id"]] = {"path": None, "captured_at_utc": mm.iso(now), "status": "error", "error": str(res)}
        report.append({"id": pg["id"], "ok": False, "error": str(res)})

    cutoff = (today - timedelta(days=int(st["retention_days"]))).isoformat()
    meta["days"] = {d: v for d, v in sorted(meta["days"].items()) if d >= cutoff}
    meta["updated_at"] = mm.iso(now)
    storage.put(WEATHER_KEY, json.dumps(meta, ensure_ascii=False, indent=1).encode("utf-8"),
                "application/json; charset=utf-8", mm.NO_CACHE)
    return report


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(root / "config" / "weather.yaml"))
    ap.add_argument("--local")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--require-slot", action="store_true")
    ap.add_argument("--tolerance", type=int, default=30)
    ap.add_argument("--no-robots", action="store_true", help="samo za lokalne teste")
    a = ap.parse_args()

    st, pages = load_weather_config(a.config)
    cam_cfg = root / "config" / "cameras.yaml"
    if cam_cfg.exists():  # skupna user_agent in retention_days (isti kot pri čiščenju)
        cs = (yaml.safe_load(cam_cfg.read_text(encoding="utf-8")) or {}).get("settings") or {}
        st["user_agent"] = cs.get("user_agent", st["user_agent"])
        st["retention_days"] = cs.get("retention_days", st["retention_days"])
    if a.only:
        pages = [p for p in pages if p["id"] in a.only]
    if a.require_slot and nearest_slot(datetime.now(timezone.utc), [st["time"]], st["timezone"], a.tolerance) is None:
        print("Zdaj ni časa za dnevni posnetek vremena, preskočeno.")
        return 0
    if not pages:
        print("Ni strani za zajem.")
        return 1

    if not a.no_robots:
        try:
            can = robots_checker([p["url"] for p in pages], st["user_agent"])
        except (httpx.HTTPError, RuntimeError) as e:
            print(f"Ne morem prebrati robots.txt ({type(e).__name__}: {e}). Ustavljam.")
            return 1
        blocked = [p for p in pages if not can(p["url"])]
        for p in blocked:
            print(f"robots.txt prepoveduje: {p['url']}")
        pages_ok = [p for p in pages if p not in blocked]
        if not pages_ok:
            return 1
    else:
        pages_ok = pages

    storage = LocalStorage(a.local) if a.local else R2Storage.from_env()
    shots = screenshot_pages(pages_ok, st)
    report = run_weather(pages_ok, st, storage, shots)
    for r in report:
        print(("OK     " if r["ok"] else "NAPAKA ") + f"{r['id']:26} {r['error'] or ''}")
    bad = [r for r in report if not r["ok"]]
    print(f"Skupaj: {len(report)}, uspešnih: {len(report) - len(bad)}, napak: {len(bad)}")
    return 0 if any(r["ok"] for r in report) else 1


if __name__ == "__main__":
    sys.exit(main())
