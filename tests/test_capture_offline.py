"""Offline testi: lokalni HTTP strežnik, brez interneta. Ne dokazujejo delovanja pravih kamer."""
import http.server
import io
import sys
import threading
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.capture.capture_manager import capture_camera  # noqa: E402
from backend.config import Camera, ConfigError, DEFAULTS, load_config  # noqa: E402


def _gradient(fmt="JPEG", size=(640, 360)):
    img = Image.new("RGB", size)
    px = img.load()
    for x in range(size[0]):
        for y in range(size[1]):
            px[x, y] = (x % 256, y % 256, (x + y) % 256)
    b = io.BytesIO()
    img.save(b, fmt)
    return b.getvalue()


FILES = {
    "/ok.jpg": ("image/jpeg", _gradient("JPEG")),
    "/ok.png": ("image/png", _gradient("PNG")),
    "/blank.jpg": ("image/jpeg", (lambda b: (Image.new("RGB", (640, 360), "white").save(b, "JPEG"), b.getvalue())[1])(io.BytesIO())),
    "/page.html": ("text/html", b"<html>" + b"x" * 5000 + b"</html>"),
}


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in FILES:
            ct, body = FILES[self.path]
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def base():
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def cam(url):
    return Camera("t", "Test", "x", "http://x", "direct", image_url=url, wait_seconds=0)


def test_ok_jpeg_unchanged(base):
    r = capture_camera(cam(base + "/ok.jpg"), DEFAULTS)
    assert r.ok and r.data == FILES["/ok.jpg"][1] and (r.width, r.height) == (640, 360)


def test_png_converted_to_jpeg(base):
    r = capture_camera(cam(base + "/ok.png"), DEFAULTS)
    assert r.ok and r.data[:3] == b"\xff\xd8\xff"


@pytest.mark.parametrize("path,stage", [("/blank.jpg", "invalid"), ("/page.html", "invalid"), ("/nope.jpg", "reachable")])
def test_rejects_bad(base, path, stage):
    r = capture_camera(cam(base + path), DEFAULTS)
    assert not r.ok and r.stage == stage


def test_unreachable_does_not_raise():
    r = capture_camera(cam("http://127.0.0.1:1/x.jpg"), {**DEFAULTS, "timeout_seconds": 1})
    assert not r.ok and r.stage == "reachable"


def test_real_config_is_valid():
    _, cams = load_config(Path(__file__).resolve().parent.parent / "config" / "cameras.yaml")
    assert any(c.active for c in cams)


def test_config_errors(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("cameras:\n  - {id: A b, name: x, url: ftp://x, mode: direct}\n")
    with pytest.raises(ConfigError) as e:
        load_config(p)
    assert "id sme" in str(e.value) and "image_url" in str(e.value)
