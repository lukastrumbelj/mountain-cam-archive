"""Zajem vseh aktivnih kamer + shranjevanje.

    python -m backend.main --local out/archive          # brez R2 (test)
    python -m backend.main                              # R2 (okoljske spremenljivke R2_*)
    python -m backend.main --only kamnisko-sedlo --manual
    python -m backend.main --require-slot --tolerance 45   # za cron: preskoči, če ni termin
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from .capture.capture_manager import capture_camera
from .config import load_config
from .metadata import metadata_manager as mm
from .storage.r2_storage import LocalStorage, R2Storage
from .timeutil import local_parts, nearest_slot


def run_capture(cams, settings, storage, capture_fn=capture_camera, manual=False, only=None) -> list[dict]:
    tz = settings["timezone"]
    status = mm.load_status(storage)
    report = []

    for cam in cams:
        if only and cam.id not in only:
            continue
        if not cam.active:
            mm.mark_inactive(status, cam)
            continue

        res = capture_fn(cam, settings)
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
        report.append({"id": cam.id, "ok": ok, "slot": slot, "error": err})

    mm.save_status(storage, status, settings["retention_days"])
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
    for r in report:
        print(("OK     " if r["ok"] else "NAPAKA ") + f"{r['id']:20} {r['slot']} {r['error'] or ''}")
    # Ena kamera ne sme podreti izvajanja; napaka samo če ni uspela nobena.
    return 0 if any(r["ok"] for r in report) or not report else 1


if __name__ == "__main__":
    sys.exit(main())
