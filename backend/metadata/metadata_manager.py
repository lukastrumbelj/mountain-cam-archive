"""Metapodatki v R2 (brez baze):

  archive/{id}/YYYY/MM/DD/HH-MM.jpg     slika
  archive/{id}/YYYY/MM/DD/index.json    zajemi tega dne
  meta/status.json                      stanje vseh kamer (+ seznam dni z zajemi)
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

STATUS_KEY = "meta/status.json"
NO_CACHE = "public, max-age=60"
IMG_CACHE = "public, max-age=86400"


def day_prefix(cam_id: str, d: date) -> str:
    return f"archive/{cam_id}/{d:%Y}/{d:%m}/{d:%d}"


def image_key(cam_id: str, d: date, slot: str) -> str:
    return f"{day_prefix(cam_id, d)}/{slot}.jpg"


def index_key(cam_id: str, d: date) -> str:
    return f"{day_prefix(cam_id, d)}/index.json"


def _load(storage, key: str, default):
    raw = storage.get(key)
    return json.loads(raw) if raw else default


def _save(storage, key: str, obj) -> None:
    storage.put(key, json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8"),
                "application/json; charset=utf-8", NO_CACHE)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_status(storage) -> dict:
    return _load(storage, STATUS_KEY, {"version": 1, "cameras": {}})


def save_status(storage, status: dict, retention_days: int) -> None:
    status["updated_at"] = iso(datetime.now(timezone.utc))
    status["retention_days"] = retention_days
    _save(storage, STATUS_KEY, status)


def upsert_index_entry(storage, cam_id: str, d: date, entry: dict) -> None:
    """Doda/zamenja vnos za termin. Uspešen vnos se nikoli ne prepiše z napako."""
    key = index_key(cam_id, d)
    idx = _load(storage, key, {"camera_id": cam_id, "date": d.isoformat(), "captures": []})
    caps = idx["captures"]
    for i, old in enumerate(caps):
        if old["slot"] == entry["slot"]:
            if old["status"] == "ok" and entry["status"] != "ok":
                return
            caps[i] = entry
            break
    else:
        caps.append(entry)
    caps.sort(key=lambda c: c["slot"])
    _save(storage, key, idx)


def update_status(status: dict, cam, *, ok: bool, attempt_utc: datetime, error: str | None = None,
                  stage: str | None = None, image: str | None = None, d: date | None = None,
                  slot: str | None = None) -> None:
    e = status["cameras"].setdefault(cam.id, {"consecutive_failures": 0, "dates": []})
    e.update(name=cam.name, location=cam.location, url=cam.url, active=cam.active,
             last_attempt_utc=iso(attempt_utc))
    if ok:
        e.update(status="ok", error=None, stage=None, last_success_utc=iso(attempt_utc),
                 last_image=image, last_date=d.isoformat(), last_slot=slot, consecutive_failures=0)
        if d.isoformat() not in e["dates"]:
            e["dates"] = sorted(e["dates"] + [d.isoformat()])
    else:
        e.update(status="error", error=error, stage=stage,
                 consecutive_failures=e.get("consecutive_failures", 0) + 1)


def mark_inactive(status: dict, cam) -> None:
    e = status["cameras"].setdefault(cam.id, {"consecutive_failures": 0, "dates": []})
    e.update(name=cam.name, location=cam.location, url=cam.url, active=False, status="inactive")
