import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.cleanup import run_cleanup  # noqa: E402
from backend.config import DEFAULTS  # noqa: E402
from backend.storage.r2_storage import LocalStorage  # noqa: E402


def setup(tmp_path):
    st = LocalStorage(tmp_path)
    for d in ("2026/11/10", "2026/11/14", "2026/11/15", "2026/11/22"):
        st.put(f"archive/a/{d}/13-00.jpg", b"x", "image/jpeg")
        st.put(f"archive/a/{d}/index.json", b"{}", "application/json")
    st.put("meta/status.json", json.dumps({"cameras": {"a": {
        "dates": ["2026-11-10", "2026-11-14", "2026-11-15", "2026-11-22"]}}}).encode(), "application/json")
    st.put("archive/a/neveljavno/ostalo.txt", b"x", "text/plain")
    return st


def test_deletes_only_older_than_cutoff(tmp_path):
    st = setup(tmp_path)
    r = run_cleanup(st, DEFAULTS, today=date(2026, 11, 22))  # 7 dni -> rez 2026-11-15
    assert r["cutoff"] == "2026-11-15" and r["deleted"] == 4
    keys = st.list("archive/")
    assert not any("/2026/11/10/" in k or "/2026/11/14/" in k for k in keys)
    assert any("/2026/11/15/" in k for k in keys) and any("/2026/11/22/" in k for k in keys)
    assert "archive/a/neveljavno/ostalo.txt" in keys  # tuje ključe pusti
    assert st.get("meta/status.json") is not None
    assert json.loads(st.get("meta/status.json"))["cameras"]["a"]["dates"] == ["2026-11-15", "2026-11-22"]


def test_dry_run_deletes_nothing(tmp_path):
    st = setup(tmp_path)
    before = st.list("")
    r = run_cleanup(st, DEFAULTS, today=date(2026, 11, 22), dry_run=True)
    assert r["deleted"] == 4 and st.list("") == before


def test_retention_30_days_keeps_all(tmp_path):
    st = setup(tmp_path)
    assert run_cleanup(st, {**DEFAULTS, "retention_days": 30}, today=date(2026, 11, 22))["deleted"] == 0
