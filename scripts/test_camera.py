"""Test zajema.  Primeri:
    python scripts/test_camera.py kamnisko-sedlo
    python scripts/test_camera.py --all            (samo aktivne)
    python scripts/test_camera.py --validate       (samo preveri cameras.yaml)
Slike se shranijo v out/<id>.jpg
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.capture.capture_manager import capture_camera  # noqa: E402
from backend.config import ConfigError, load_config  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("camera_id", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--config", default=str(ROOT / "config" / "cameras.yaml"))
    ap.add_argument("--out", default=str(ROOT / "out"))
    a = ap.parse_args()

    try:
        settings, cams = load_config(a.config)
    except ConfigError as e:
        print(e)
        return 2
    if a.validate:
        print(f"OK: {len(cams)} kamer, {sum(c.active for c in cams)} aktivnih")
        return 0

    if a.all:
        targets = [c for c in cams if c.active]
    elif a.camera_id:
        targets = [c for c in cams if c.id == a.camera_id]
        if not targets:
            print(f"Kamera '{a.camera_id}' ne obstaja.")
            return 2
    else:
        ap.print_help()
        return 2

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    failed = 0
    for cam in targets:
        r = capture_camera(cam, settings)
        if r.ok:
            (out / f"{cam.id}.jpg").write_bytes(r.data)
            print(f"OK    {cam.id:20} {r.width}x{r.height} {r.size/1024:.0f} KB {r.duration_s:.1f}s")
        else:
            failed += 1
            print(f"NAPAKA {cam.id:19} [{r.stage}] {r.error}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
