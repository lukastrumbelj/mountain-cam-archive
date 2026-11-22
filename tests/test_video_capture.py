"""Pravi test zajema frame-a iz videa: lokalni strežnik + ffmpeg + Chrome (preskoči, če ni na voljo)."""
import http.server
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.capture.capture_manager import capture_camera  # noqa: E402
from backend.config import DEFAULTS, Camera  # noqa: E402

pytest.importorskip("playwright")
if not shutil.which("ffmpeg"):
    pytest.skip("ni ffmpeg", allow_module_level=True)


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    d = tmp_path_factory.mktemp("site")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=10:duration=4",
                    "-pix_fmt", "yuv420p", "-c:v", "libx264", str(d / "clip.mp4")], check=True)
    (d / "page.html").write_text('<html><body><video src="clip.mp4" autoplay muted loop playsinline '
                                 'width="640" height="360"></video></body></html>')
    (d / "outer.html").write_text('<html><body><iframe src="page.html" width="700" height="400"></iframe></body></html>')
    (d / "none.html").write_text("<html><body>brez videa</body></html>")

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(d), **k)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def cam(url, **extra):
    return Camera("v", "Video", "x", url, "video", wait_seconds=1, extra=extra)


def test_video_frame_direct(site):
    r = capture_camera(cam(site + "/page.html"), {**DEFAULTS, "timeout_seconds": 20})
    assert r.ok, r.error
    assert (r.width, r.height) == (640, 360) and r.data[:3] == b"\xff\xd8\xff"


def test_video_inside_iframe(site):
    r = capture_camera(cam(site + "/outer.html", frame="iframe"), {**DEFAULTS, "timeout_seconds": 20})
    assert r.ok, r.error


def test_no_video_is_reported(site):
    r = capture_camera(cam(site + "/none.html"), {**DEFAULTS, "timeout_seconds": 5})
    assert not r.ok and r.stage == "element"
