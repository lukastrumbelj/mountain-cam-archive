"""Zajem vremena: lokalni strežnik s tabelo (brez pravega ARSO) + Playwright Chromium."""
import http.server
import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import weather as W  # noqa: E402
from backend.capture.errors import CaptureError  # noqa: E402
from backend.cleanup import run_cleanup  # noqa: E402
from backend.storage.r2_storage import LocalStorage  # noqa: E402

pytest.importorskip("playwright")

ROW = "".join(f"<td>{i}</td>" for i in range(33))
TABLE = "<html><body><h2>ARSO vreme: napoved</h2><table border=1>" + "".join(
    f"<tr><th>vrstica {r}</th>{ROW}</tr>" for r in range(40)) + "</table></body></html>"


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    d = tmp_path_factory.mktemp("w")
    (d / "ok.html").write_text(TABLE)
    (d / "empty.html").write_text("<html><body></body></html>")
    (d / "robots.txt").write_text("User-agent: *\nDisallow: /private/\n")

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(d), **k)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def cfg(site):
    st = {**W.DEFAULTS, **W.W_DEFAULTS, "user_agent": "t/1", "timeout_seconds": 15}
    pages = [{"id": "ok", "name": "OK", "url": site + "/ok.html"},
             {"id": "missing", "name": "Manjka", "url": site + "/nope.html"},
             {"id": "empty", "name": "Prazna", "url": site + "/empty.html"}]
    return st, pages


def test_screenshot_save_and_meta(site, tmp_path):
    st, pages = cfg(site)
    shots = W.screenshot_pages(pages, st)
    assert isinstance(shots["ok"], bytes) and shots["ok"][:3] == b"\xff\xd8\xff"
    assert isinstance(shots["missing"], CaptureError) and "404" in str(shots["missing"])
    assert isinstance(shots["empty"], CaptureError)

    store = LocalStorage(tmp_path)
    now = datetime(2026, 11, 27, 11, 0, tzinfo=timezone.utc)  # 12:00 po slovenskem času
    rep = W.run_weather(pages, st, store, shots, now)
    assert [r["ok"] for r in rep] == [True, False, False]
    meta = json.loads(store.get(W.WEATHER_KEY))
    day = meta["days"]["2026-11-27"]
    assert day["ok"]["path"] == "weather/2026/11/27/ok.jpg" and day["ok"]["width"] >= 1900
    assert store.get(day["ok"]["path"])[:3] == b"\xff\xd8\xff"
    assert day["missing"]["status"] == "error" and meta["regions"]["ok"]["name"] == "OK"

    # napaka istega dne ne prepiše uspešnega posnetka; uspeh prepiše napako
    W.run_weather(pages, st, store, {"ok": CaptureError("x", "reachable"), "missing": shots["ok"]}, now)
    meta = json.loads(store.get(W.WEATHER_KEY))["days"]["2026-11-27"]
    assert meta["ok"]["status"] == "ok" and meta["missing"]["status"] == "ok"


def test_retention_prune_and_cleanup(site, tmp_path):
    st, pages = cfg(site)
    store = LocalStorage(tmp_path)
    img = W.screenshot_pages(pages[:1], st)["ok"]
    for day in range(10, 30):
        W.run_weather(pages[:1], st, store, {"ok": img}, datetime(2026, 11, day, 11, 0, tzinfo=timezone.utc))
    days = sorted(json.loads(store.get(W.WEATHER_KEY))["days"])
    assert days[0] == "2026-11-22" and days[-1] == "2026-11-29" and len(days) == 8
    # cleanup izbriše stare slike (po datumu v poti), meta/weather.json ostane
    r = run_cleanup(store, {"retention_days": 7, "timezone": "Europe/Ljubljana"}, today=datetime(2026, 11, 29).date())
    assert r["deleted"] == 12
    left = store.list("weather/")
    assert len(left) == 8 and all("2026/11/2" in k for k in left)
    assert store.get(W.WEATHER_KEY)


def test_robots(site):
    can = W.robots_checker([site + "/ok.html"], "t/1")
    assert can(site + "/ok.html") and not can(site + "/private/x.html")


def test_config_validation(tmp_path):
    p = tmp_path / "w.yaml"
    p.write_text("pages:\n- {id: A_B, name: x, url: 'https://a'}\n")
    with pytest.raises(ValueError):
        W.load_weather_config(p)
    st, pages = W.load_weather_config(Path(__file__).resolve().parent.parent / "config" / "weather.yaml")
    assert len(pages) == 8 and st["time"] == "12:00"
