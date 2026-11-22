import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.capture.capture_manager import CaptureResult  # noqa: E402
from backend.config import DEFAULTS, Camera  # noqa: E402
from backend.main import run_capture  # noqa: E402
from backend.storage.r2_storage import LocalStorage  # noqa: E402
from backend.timeutil import nearest_slot  # noqa: E402

UTC = timezone.utc
JPEG = b"\xff\xd8\xff" + b"0" * 4000


def test_slot_winter_and_summer():
    s = DEFAULTS["slots"]
    # zima (UTC+1): 06:03 UTC = 07:03
    assert nearest_slot(datetime(2026, 11, 22, 6, 3, tzinfo=UTC), s, "Europe/Ljubljana") == (date(2026, 11, 22), "07-00")
    # poletje (UTC+2): 05:03 UTC = 07:03
    assert nearest_slot(datetime(2026, 7, 22, 5, 3, tzinfo=UTC), s, "Europe/Ljubljana") == (date(2026, 7, 22), "07-00")
    # job z zamudo 40 min še vedno šteje za 13:00
    assert nearest_slot(datetime(2026, 11, 22, 12, 40, tzinfo=UTC), s, "Europe/Ljubljana")[1] == "13-00"
    # sredi noči: izven tolerance
    assert nearest_slot(datetime(2026, 11, 22, 1, 0, tzinfo=UTC), s, "Europe/Ljubljana") is None


def cams():
    mk = lambda i, active=True: Camera(i, i, "loc", "http://x", "direct", image_url="http://x/i.jpg", active=active)
    return [mk("a"), mk("bad"), mk("off", False)]


def fake(cam, settings):
    t = datetime(2026, 11, 22, 12, 5, tzinfo=UTC)  # 13:05 lokalno
    if cam.id == "bad":
        return CaptureResult(cam.id, False, error="HTTP 500", stage="reachable")
    return CaptureResult(cam.id, True, JPEG, 640, 360, len(JPEG), captured_at_utc=t)


def test_run_capture_isolated_failure_and_metadata(tmp_path):
    st = LocalStorage(tmp_path)
    rep = run_capture(cams(), DEFAULTS, st, capture_fn=fake)
    assert [r["ok"] for r in rep] == [True, False]  # 'bad' ni ustavil 'a', 'off' preskočena

    assert st.get("archive/a/2026/11/22/13-00.jpg") == JPEG
    idx = json.loads(st.get("archive/a/2026/11/22/index.json"))
    e = idx["captures"][0]
    assert e["status"] == "ok" and e["planned_slot"] == "13:00" and e["captured_at_utc"] == "2026-11-22T12:05:00Z"
    assert e["captured_at_local"].startswith("2026-11-22T13:05:00+01:00") and e["size"] == len(JPEG)

    s = json.loads(st.get("meta/status.json"))["cameras"]
    assert s["a"]["status"] == "ok" and s["a"]["dates"] == ["2026-11-22"]
    assert s["bad"]["status"] == "error" and s["bad"]["error"] == "HTTP 500" and s["bad"]["consecutive_failures"] == 1
    assert s["off"]["status"] == "inactive"


def test_failure_never_overwrites_ok_entry(tmp_path):
    st = LocalStorage(tmp_path)
    one = [Camera("a", "a", "l", "http://x", "direct", image_url="http://x/i.jpg")]
    run_capture(one, DEFAULTS, st, capture_fn=fake)
    run_capture(one, DEFAULTS, st, capture_fn=lambda c, s: CaptureResult(c.id, False, error="x", stage="reachable",
                captured_at_utc=datetime(2026, 11, 22, 12, 6, tzinfo=UTC)))
    idx = json.loads(st.get("archive/a/2026/11/22/index.json"))
    assert len(idx["captures"]) == 1 and idx["captures"][0]["status"] == "ok"


def test_manual_uses_actual_time(tmp_path):
    st = LocalStorage(tmp_path)
    one = [Camera("a", "a", "l", "http://x", "direct", image_url="http://x/i.jpg")]
    run_capture(one, DEFAULTS, st, capture_fn=fake, manual=True)
    assert st.get("archive/a/2026/11/22/13-05.jpg") == JPEG
