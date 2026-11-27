"""Brisanje starih slik.

    python -m backend.cleanup --local out/archive --dry-run
    python -m backend.cleanup                      # R2

Pravila (da se nič ne izbriše prezgodaj):
  - starost se računa po DATUMU v poti (lokalni čas Europe/Ljubljana), ne po času datoteke;
  - ohranijo se dnevi >= danes - retention_days (torej dodatni delni dan);
  - briše samo ključe oblike archive/{id}/YYYY/MM/DD/... in weather/YYYY/MM/DD/...; meta/ in ostalo se ne dotakne.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import load_config
from .metadata import metadata_manager as mm
from .storage.r2_storage import LocalStorage, R2Storage

KEY_RE = re.compile(r"^(?:archive/[a-z0-9-]+|weather)/(\d{4})/(\d{2})/(\d{2})/[^/]+$")


def run_cleanup(storage, settings, today: date | None = None, dry_run: bool = False) -> dict:
    days = int(settings["retention_days"])
    if days < 1:
        raise ValueError("retention_days mora biti >= 1")
    today = today or datetime.now(ZoneInfo(settings["timezone"])).date()
    cutoff = today - timedelta(days=days)  # dnevi pred tem datumom se izbrišejo

    old = []
    for key in [*storage.list("archive/"), *storage.list("weather/")]:
        m = KEY_RE.match(key)
        if not m:
            continue
        try:
            d = date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            continue
        if d < cutoff:
            old.append(key)

    if not dry_run:
        if old:
            storage.delete(old)
        status = mm.load_status(storage)
        changed = False
        for cam in status.get("cameras", {}).values():
            kept = [d for d in cam.get("dates", []) if d >= cutoff.isoformat()]
            if kept != cam.get("dates", []):
                cam["dates"], changed = kept, True
        if changed or old:
            mm.save_status(storage, status, days)
    return {"deleted": len(old), "cutoff": cutoff.isoformat(), "dry_run": dry_run}


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(root / "config" / "cameras.yaml"))
    ap.add_argument("--local")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    settings, _ = load_config(a.config)
    storage = LocalStorage(a.local) if a.local else R2Storage.from_env()
    r = run_cleanup(storage, settings, dry_run=a.dry_run)
    print(f"Izbrisanih: {r['deleted']} (starejše od {r['cutoff']})" + (" [dry-run]" if r["dry_run"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
