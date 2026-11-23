from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

MODES = {"direct", "selector", "screenshot", "custom", "video"}

DEFAULTS = {
    "user_agent": "MountainCamArchive/0.1 (personal non-commercial archive)",
    "timeout_seconds": 20,
    "retention_days": 7,
    "jpeg_quality": 88,
    "min_width": 200,
    "min_height": 120,
    "timezone": "Europe/Ljubljana",
    "workers": 12,
    "per_host": 2,
    "max_runtime_minutes": 12,
    "slots": ["07:00", "10:00", "13:00", "16:00", "19:00"],
}


class ConfigError(Exception):
    pass


@dataclass
class Camera:
    id: str
    name: str
    location: str
    url: str
    mode: str
    image_url: str | None = None
    selector: str | None = None
    wait_seconds: float = 3.0
    active: bool = True
    extra: dict = field(default_factory=dict)


def _problems(cam: Camera) -> list[str]:
    p = []
    if not re.fullmatch(r"[a-z0-9-]+", cam.id or ""):
        p.append("id sme vsebovati samo a-z, 0-9 in -")
    if cam.mode not in MODES:
        p.append(f"neznan mode '{cam.mode}' (dovoljeno: {', '.join(sorted(MODES))})")
    if not cam.name:
        p.append("manjka name")
    if not (cam.url or "").startswith(("http://", "https://")):
        p.append("url mora biti http(s)")
    if cam.mode == "direct" and not cam.image_url:
        p.append("mode direct zahteva image_url")
    if cam.mode == "selector" and not cam.selector:
        p.append("mode selector zahteva selector")
    if cam.mode == "custom" and not (cam.selector or cam.extra.get("steps")):
        p.append("mode custom zahteva selector ali extra.steps")
    return p


def validate_cameras(cams: list[Camera]) -> list[str]:
    errors, seen = [], set()
    for c in cams:
        for msg in _problems(c):
            errors.append(f"[{c.id}] {msg}")
        if c.id in seen:
            errors.append(f"[{c.id}] podvojen id")
        seen.add(c.id)
    return errors


def load_config(path: str | Path) -> tuple[dict, list[Camera]]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    settings = {**DEFAULTS, **(raw.get("settings") or {})}
    cams = []
    for item in raw.get("cameras") or []:
        cams.append(
            Camera(
                id=str(item.get("id", "")),
                name=item.get("name", ""),
                location=item.get("location", ""),
                url=item.get("url", ""),
                mode=item.get("mode", ""),
                image_url=item.get("image_url"),
                selector=item.get("selector"),
                wait_seconds=float(item.get("wait_seconds", 3)),
                active=bool(item.get("active", True)),
                extra=item.get("extra") or {},
            )
        )
    errors = validate_cameras(cams)
    if errors:
        raise ConfigError("Napake v konfiguraciji:\n" + "\n".join(errors))
    return settings, cams
