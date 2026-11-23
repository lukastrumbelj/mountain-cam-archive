"""Zajem vseh aktivnih kamer + shranjevanje.

    python -m backend.main --local out/archive          # brez R2 (test)
    python -m backend.main                              # R2 (okoljske spremenljivke R2_*)
    python -m backend.main --only kamnisko-sedlo --manual
    python -m backend.main --require-slot --tolerance 30   # za cron: preskoči, če ni termin
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .capture.capture_manager import CaptureResult, capture_camera
from .config import load_config
from .metadata import metadata_manager as mm
from .storage.r2_storage import LocalStorage, R2Storage
from .timeutil import local_parts, nearest_slot


def _host_limited(fn, per_host: int, max_timeouts: int = 2):
    """Največ `per_host` hkratnih zahtev na strežnik. Če strežnik ob zagonu ni dosegljiv
    (>= max_timeouts timeoutov in nobenega uspeha), preostale kamere tega strežnika preskoči."""
    locks, guard = defaultdict(lambda: threading.BoundedSemaphore(per_host)), threading.Lock()
    timeouts, successes = defaultdict(int), defaultdict(int)

    def wrapped(cam, settings):
        host = urlparse(cam.image_url or cam.url).netloc
        with guard:
            sem = locks[host]
        with sem:
            with guard:
                if timeouts[host] >= max_timeouts and not successes[host]:
                    return CaptureResult(cam.id, False, stage="reachable",
                                         error=f"strežnik {host} ni dosegljiv iz zagona (preskočeno)")
            res = fn(cam, settings)
            with guard:
                if res.ok:
                    successes[host] += 1
                elif res.error and "Timeout" in res.error:
                    timeouts[host] += 1
            return res
    return wrapped


def _store(cam, res, settings, storage, status, manual):
    tz = settings["timezone"]
    now = res.captured_at_utc or datetime.now(timezone.utc)
    slot_info = None if manual else nearest_slot(now, settings["slots"], tz,
                                                 settings.get("slot_tolerance_minutes", 90))
    local_date, hhmm, local_dt = local_parts(now, tz)
    if slot_info:
        local_date, slot = slot_info
        planned = slot
    else:
        slot, planned = hhmm, None  # ročni zajem / zunaj tolerance: ime po dejanskem času

    entry = {"camera_id": cam.id, "name": cam.name, "date": local_date.isoformat(),
             "slot": slot, "planned_slot": planned.replace("-", ":") if planned else None,
             "captured_at_local": local_dt.isoformat(timespec="seconds"),
             "captured_at_utc": mm.iso(now), "timezone": tz,
             "path": None, "size": 0, "status": "error", "error": None}
    ok, err, stage = res.ok, res.error, res.stage
    key = None

    if ok:
        key = mm.image_key(cam.id, local_date, slot)
        try:  # najprej slika, potem index: index nikoli ne kaže na manjkajočo sliko
            storage.put(key, res.data, "image/jpeg", mm.IMG_CACHE)
            entry.update(path=key, size=res.size, width=res.width, height=res.height, status="ok")
        except Exception as e:
            ok, err, stage = False, f"shranjevanje: {type(e).__name__}: {e}", "storage"
    if not ok:
        entry["error"] = err

    try:
        mm.upsert_index_entry(storage, cam.id, local_date, entry)
    except Exception as e:
        ok, err, stage = False, f"index: {type(e).__name__}: {e}", "storage"

    mm.update_status(status, cam, ok=ok, attempt_utc=now, error=err, stage=stage,
                     image=key, d=local_date, slot=slot)
    return {"id": cam.id, "ok": ok, "slot": slot, "error": err}


def run_capture(cams, settings, storage, capture_fn=capture_camera, manual=False, only=None) -> list[dict]:
    """Zajem poteka vzporedno (workers niti), shranjevanje po vrsti v glavni niti.
    Po max_runtime_minutes se čakanje prekine: nedokončane kamere so zabeležene kot napaka,
    status in že shranjene slike pa se vseeno zapišejo."""
    status = mm.load_status(storage)
    report, todo = [], []
    for cam in cams:
        if only and cam.id not in only:
            continue
        if not cam.active:
            mm.mark_inactive(status, cam)
            continue
        todo.append(cam)

    fn = _host_limited(capture_fn, int(settings.get("per_host", 2)))
    deadline = time.monotonic() + float(settings.get("max_runtime_minutes", 12)) * 60
    ex = ThreadPoolExecutor(max_workers=max(1, int(settings.get("workers", 12))))
    pending = {ex.submit(fn, cam, settings): cam for cam in todo}
    done_n = 0
    try:
        while pending:
            left = deadline - time.monotonic()
            if left <= 0:
                print(f"Časovna omejitev: nedokončanih {len(pending)} kamer", flush=True)
                break
            done, _ = wait(pending, timeout=left, return_when=FIRST_COMPLETED)
            for f in done:
                cam = pending.pop(f)
                try:
                    res = f.result()
                except Exception as e:  # capture_camera ne vrže, a zaščita za druge capture_fn
                    res = CaptureResult(cam.id, False, error=f"{type(e).__name__}: {e}", stage="capture")
                r = _store(cam, res, settings, storage, status, manual)
                report.append(r)
                done_n += 1
                print(f"[{done_n}/{len(todo)}] {'OK' if r['ok'] else 'NAPAKA'} {r['id']} {r['error'] or ''}", flush=True)
        for f, cam in list(pending.items()):  # časovna omejitev
            f.cancel()
            res = CaptureResult(cam.id, False, error="časovna omejitev zagona", stage="reachable")
            report.append(_store(cam, res, settings, storage, status, manual))
    finally:
        ex.shutdown(wait=False, cancel_futures=True)

    mm.save_status(storage, status, settings["retention_days"])
    order = {c.id: i for i, c in enumerate(cams)}
    report.sort(key=lambda r: order.get(r["id"], 0))
    return report


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(root / "config" / "cameras.yaml"))
    ap.add_argument("--local", help="mapa za lokalno shranjevanje namesto R2")
    ap.add_argument("--only", nargs="*", help="samo te kamere")
    ap.add_argument("--manual", action="store_true", help="ime slike po dejanskem času, ne po terminu")
    ap.add_argument("--require-slot", action="store_true",
                    help="če ni termina znotraj tolerance, ne naredi ničesar (za cron zimski/poletni čas)")
    ap.add_argument("--tolerance", type=int, help="toleranca v minutah (privzeto 90)")
    a = ap.parse_args()

    settings, cams = load_config(a.config)
    if a.tolerance:
        settings["slot_tolerance_minutes"] = a.tolerance

    if a.require_slot:
        near = nearest_slot(datetime.now(timezone.utc), settings["slots"], settings["timezone"],
                            settings.get("slot_tolerance_minutes", 90))
        if near is None:
            print("Zdaj ni termina zajema (zimski/poletni cron), preskočeno.")
            return 0

    storage = LocalStorage(a.local) if a.local else R2Storage.from_env()
    report = run_capture(cams, settings, storage, manual=a.manual, only=a.only)
    bad = [r for r in report if not r["ok"]]
    print(f"Skupaj: {len(report)}, uspešnih: {len(report) - len(bad)}, napak: {len(bad)}")
    # Ena kamera ne sme podreti izvajanja; napaka samo če ni uspela nobena.
    return 0 if any(r["ok"] for r in report) or not report else 1


if __name__ == "__main__":
    sys.exit(main())
