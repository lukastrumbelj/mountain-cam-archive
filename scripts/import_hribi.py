"""Uvoz kamer s hribi.net (Julijske, Kamniško-Savinjske Alpe, Karavanke).

Pred uporabo preberi pogoje: https://www.hribi.net/pogoji.asp
Skripta je vljudna (robots.txt, premor med zahtevki, prepoznaven User-Agent, predpomnilnik).

    python scripts/import_hribi.py --limit 5            # poskus na 5 straneh
    python scripts/import_hribi.py                      # vse -> out/hribi_import.yaml
    python scripts/import_hribi.py --apply              # še doda v config/cameras.yaml (varnostna kopija)
    python scripts/import_hribi.py --allow-hosts feratel.com   # dovoli video predvajalnike tega gostitelja

Slike: kamera je aktivna samo, če jo uspešno zajamemo.

Video (kjer na strani ni slike):
  * <video> neposredno na strani hribi.net -> mode: video, aktivna, če zajem uspe;
  * predvajalnik v iframe tretje osebe -> mode: video, a NEAKTIVNA in neobiskana, dokler gostitelja
    ne dovoliš z --allow-hosts (najprej preberi njegove pogoje uporabe; skripta izpiše seznam gostiteljev);
  * YouTube in WhatsUpCams se vedno preskočita (pogoji prepovedujejo samodejni dostop).
Zajem videa potrebuje Playwright in Google Chrome (python -m playwright install chromium kot rezerva).
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
import unicodedata
import urllib.robotparser
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
import yaml
from bs4 import BeautifulSoup, NavigableString

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.capture.capture_manager import capture_camera  # noqa: E402
from backend.config import Camera, load_config  # noqa: E402

BASE = "https://www.hribi.net"
LIST_URL = BASE + "/spletne_kamere_v_gorah"
WANTED = ("julijske alpe", "kamnisko savinjske alpe", "karavanke")
HARD_SKIP = ("whatsupcams", "youtube", "youtu.be")
AD_HOSTS = ("doubleclick", "googlesyndication", "googletagmanager", "google.com", "gstatic", "facebook",
            "twitter", "addthis", "hribi.net")
CAM_RE = re.compile(r"/spletna_kamera/([^/?#]+)/(\d+)")
IMG_RE = re.compile(r"\.(jpe?g|png|webp)(\?|$)", re.I)
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "b", "strong", "legend", "caption", "th", "dt"}


def norm(s: str) -> str:
    """Male črke, brez diakritik (š -> s), presledki namesto vezajev."""
    s = unicodedata.normalize("NFKD", s.strip().lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[\s\-–]+", " ", s)


def list_cameras(html: str, regions=WANTED) -> dict[str, str]:
    """{url: slug} za kamere pod naslovi iskanih gorovij. Če naslovov ne najde, vrne vse."""
    soup = BeautifulSoup(html, "html.parser")
    region, found, every = None, {}, {}
    for node in soup.descendants:
        if isinstance(node, NavigableString):
            if node.find_parent("a"):
                continue
            t = norm(str(node))
            parent = node.parent.name if node.parent else ""
            if t and len(t) < 80 and any(t.startswith(r) for r in regions):
                region = t
            elif t and len(t) < 80 and parent in HEADING_TAGS:
                region = None
        elif getattr(node, "name", None) == "a":
            m = CAM_RE.search(node.get("href", ""))
            if m:
                url = urljoin(BASE, m.group(0))
                every[url] = m.group(1)
                if region:
                    found[url] = m.group(1)
    return found or every


def clean_image_url(src: str) -> str:
    u = urlparse(src)
    return src.split("?")[0] if u.query == "hribi.net" else src


def parse_page(html: str, page_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n")
    grab = lambda label: (re.search(label + r":\s*\n?\s*([^\n]+)", text) or [None, ""])[1].strip()
    h1 = soup.find("h1")
    name = h1.get_text(strip=True) if h1 else re.sub(r"^Spletna kamera\s*", "", soup.title.get_text(strip=True) if soup.title else "")
    images, skipped, players = [], [], []
    for img in soup.find_all("img"):
        src = urljoin(page_url, img.get("src", ""))
        if "/slike/" in src or not IMG_RE.search(src) or any(h in src for h in HARD_SKIP):
            continue
        images.append(clean_image_url(src))
    for tag in soup.find_all(["iframe", "video", "a"]):
        ref = tag.get("src") or tag.get("href") or ""
        if any(h in ref for h in HARD_SKIP):
            skipped.append(ref)
    for fr in soup.find_all("iframe"):
        src = urljoin(page_url, fr.get("src", ""))
        if src.startswith("http") and not any(h in src for h in AD_HOSTS + HARD_SKIP):
            players.append(src)
    return {"name": name, "country": grab("Država"), "range": grab("Gorovje"),
            "images": list(dict.fromkeys(images)), "skipped": skipped,
            "video": soup.find("video") is not None, "players": list(dict.fromkeys(players))}


def make_id(slug: str, num: str, n: int, total: int, suffix: str = "") -> str:
    base = re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-") + f"-{num}" + suffix
    return base + (f"-{n}" if total > 1 else "")


def to_block(c: Camera) -> dict:
    b = {"id": c.id, "name": c.name, "location": c.location, "url": c.url, "mode": c.mode}
    if c.mode == "direct":
        b["image_url"] = c.image_url
        b["wait_seconds"] = 0
    else:
        b["selector"] = c.selector
        b["wait_seconds"] = c.wait_seconds
    b["active"] = c.active
    return b


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "config" / "cameras.yaml"))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--delay", type=float, default=1.5)
    ap.add_argument("--country", default="Slovenija")
    ap.add_argument("--no-validate", action="store_true")
    ap.add_argument("--allow-hosts", default="", help="gostitelji video predvajalnikov, ločeni z vejico")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "out"))
    a = ap.parse_args()
    allowed = [h.strip().lower() for h in a.allow_hosts.split(",") if h.strip()]

    settings, existing = load_config(a.config)
    known_urls = {c.image_url for c in existing if c.image_url}
    known_ids = {c.id for c in existing}
    out = Path(a.out)
    cache = out / "hribi_cache"
    cache.mkdir(parents=True, exist_ok=True)

    client = httpx.Client(headers={"User-Agent": settings["user_agent"]}, timeout=30, follow_redirects=True)
    # robots.txt beremo prek httpx (urllib na Macu pogosto nima SSL certifikatov in tiho odpove).
    rp = urllib.robotparser.RobotFileParser()
    try:
        rr = client.get(BASE + "/robots.txt")
    except httpx.HTTPError as e:
        print(f"Ne morem prebrati robots.txt ({type(e).__name__}: {e}). Ustavljam.")
        return 1
    if rr.status_code == 200:
        rp.parse(rr.text.splitlines())
    elif rr.status_code == 404:
        rp.parse([])  # robots.txt ne obstaja: ni omejitev
    else:
        print(f"robots.txt: HTTP {rr.status_code}. Ustavljam.")
        return 1

    def get(url: str, key: str) -> str | None:
        f = cache / f"{key}.html"
        if f.exists():
            return f.read_text(encoding="utf-8")
        if not rp.can_fetch("*", url):
            print(f"robots.txt prepoveduje: {url}")
            return None
        time.sleep(a.delay)
        r = client.get(url)
        if r.status_code != 200:
            print(f"HTTP {r.status_code}: {url}")
            return None
        f.write_text(r.text, encoding="utf-8")
        return r.text

    def preview(cid: str, data: bytes) -> None:
        d = out / "hribi_preview"
        d.mkdir(exist_ok=True)
        (d / f"{cid}.jpg").write_bytes(data)

    html = get(LIST_URL, "_list")
    if not html:
        return 1
    pages = list_cameras(html)
    print(f"Strani za pregled: {len(pages)}")

    new, pending_hosts = [], Counter()
    report = Counter()
    for i, (url, slug) in enumerate(list(pages.items())[: a.limit]):
        num = CAM_RE.search(url).group(2)
        page = get(url, f"{slug}_{num}")
        if not page:
            continue
        p = parse_page(page, url)
        # država vsebuje iskano (tudi "Avstrija, Slovenija"); gorovje se začne z iskanim
        if norm(a.country) not in norm(p["country"]) or not any(norm(p["range"]).startswith(r) for r in WANTED):
            report["drugo gorovje/država"] += 1
            continue
        loc = f"{p['name']}, {p['range']}"
        imgs = p["images"]
        count = 0

        for n, img in enumerate(imgs, 1):
            cid = make_id(slug, num, n, len(imgs))
            if img in known_urls or cid in known_ids:
                report["že v konfiguraciji"] += 1
                continue
            cam = Camera(cid, p["name"] + (f" ({n})" if len(imgs) > 1 else ""), loc, url, "direct",
                         image_url=img, wait_seconds=0, active=True)
            if urlparse(img).netloc.endswith("hribi.net"):
                report["kopija hribi.net"] += 1
            if not a.no_validate:
                r = capture_camera(cam, settings)
                if not r.ok:
                    report["napaka zajema"] += 1
                    cam.active = False
                    print(f"  neveljavno [{r.stage}] {img}: {r.error}")
                else:
                    preview(cid, r.data)
            known_urls.add(img)
            known_ids.add(cid)
            new.append(cam)
            count += 1

        # Video samo tam, kjer ni slike.
        if not imgs:
            targets = ([(url, None)] if p["video"] else []) + [(s, urlparse(s).netloc.lower()) for s in p["players"]]
            for n, (target, host) in enumerate(targets, 1):
                cid = make_id(slug, num, n, len(targets), "-video")
                if cid in known_ids:
                    report["že v konfiguraciji"] += 1
                    continue
                cam = Camera(cid, p["name"] + " (video)", loc, target, "video", selector="video",
                             wait_seconds=5, active=False)
                if host is None or any(h in host for h in allowed):
                    # tvoja stran ali dovoljen gostitelj: preizkusi zajem frame-a
                    if a.no_validate:
                        cam.active = True
                    else:
                        r = capture_camera(cam, settings)
                        cam.active = r.ok
                        if r.ok:
                            preview(cid, r.data)
                        else:
                            report["video: napaka zajema"] += 1
                            print(f"  video neveljavno [{r.stage}] {target}: {r.error}")
                else:
                    pending_hosts[host] += 1  # ne obiščemo, dokler ni dovoljen
                    report["video: čaka na dovoljenje gostitelja"] += 1
                known_ids.add(cid)
                new.append(cam)
                count += 1

        if not count and p["skipped"]:
            report["preskočeno (YouTube/WhatsUpCams)"] += 1
        print(f"[{i + 1}/{len(pages)}] {p['name']}: {count} kamer")

    text = "".join("\n".join("  " + ln for ln in yaml.safe_dump([to_block(c)], allow_unicode=True,
                                                                  sort_keys=False).splitlines()) + "\n\n"
                   for c in new)
    (out / "hribi_import.yaml").write_text("# Uvoz s hribi.net\n" + text, encoding="utf-8")
    print(f"\nNovih kamer: {len(new)} (aktivnih {sum(c.active for c in new)}) -> {out / 'hribi_import.yaml'}")
    for k, v in report.items():
        print(f"  {k}: {v}")
    if pending_hosts:
        print("\nGostitelji video predvajalnikov, ki čakajo na tvojo odločitev (preberi njihove pogoje uporabe;"
              " nato --allow-hosts):")
        for h, n in pending_hosts.most_common():
            print(f"  {h}: {n}")

    if a.apply and new:
        cfg = Path(a.config)
        shutil.copy(cfg, cfg.with_suffix(".yaml.bak"))
        body = cfg.read_text(encoding="utf-8").rstrip("\n") + "\n\n  # --- uvoz s hribi.net ---\n" + text
        cfg.write_text(body, encoding="utf-8")
        print(f"Dodano v {cfg} (varnostna kopija: {cfg.with_suffix('.yaml.bak').name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
