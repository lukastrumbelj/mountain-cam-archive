"""Samo preizkus logike na SINTETIČNEM HTML. Ne dokazuje, da se pravi HTML hribi.net razčleni pravilno."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from import_hribi import clean_image_url, list_cameras, make_id, parse_page  # noqa: E402

LIST = """<h2>Goriško</h2><a href="/spletna_kamera/ajdovscina/339">Ajdovščina</a>
<h2>Julijske Alpe</h2><a href="/spletna_kamera/pokljuka/1700">Pokljuka</a>
<a href="/spletna_kamera/vogel/16">Vogel</a>
<h2>Pohorje</h2><a href="/spletna_kamera/pohorje/5">Pohorje</a>"""

PAGE = """<title>Spletna kamera Pokljuka</title><h1>Pokljuka</h1>
<img src="https://www.hribi.net/slike/logo.png">
<img src="http://meteo.arso.gov.si/x/siwc_RUDNO-POL_s.jpg">
<img src="https://www.drsc.si/kamere/Jezersko/Jez1_0001.jpg?hribi.net">
<iframe src="https://www.whatsupcams.com/wgt/si_vogel5?hribi.net"></iframe>
<b>Država:</b> Slovenija<br><b>Gorovje:</b> Julijske Alpe<br>"""


def test_list_only_wanted_region():
    assert list(list_cameras(LIST).values()) == ["pokljuka", "vogel"]


def test_parse_page():
    p = parse_page(PAGE, "https://www.hribi.net/spletna_kamera/pokljuka/1700")
    assert p["name"] == "Pokljuka" and p["country"] == "Slovenija" and p["range"] == "Julijske Alpe"
    assert p["images"] == ["http://meteo.arso.gov.si/x/siwc_RUDNO-POL_s.jpg", "https://www.drsc.si/kamere/Jezersko/Jez1_0001.jpg"]
    assert p["skipped"] and "whatsupcams" in p["skipped"][0]


def test_video_and_players():
    html = ('<h1>X</h1><video src="a.mp4"></video>'
            '<iframe src="https://webtv.feratel.com/webtv/?cam=1"></iframe>'
            '<iframe src="https://www.youtube.com/embed/abc"></iframe>'
            '<iframe src="https://www.google.com/maps/embed?x"></iframe>')
    p = parse_page(html, "https://www.hribi.net/spletna_kamera/x/1")
    assert p["video"] is True
    assert p["players"] == ["https://webtv.feratel.com/webtv/?cam=1"]  # YouTube in zemljevid izločena
    assert any("youtube" in s for s in p["skipped"])


def test_norm_ignores_diacritics():
    from import_hribi import WANTED, norm
    assert norm("Kamniško-Savinjske Alpe") == "kamnisko savinjske alpe"
    assert any(norm("Kamniško Savinjske Alpe").startswith(r) for r in WANTED)
    assert norm("Slovenija") in norm("Avstrija, Slovenija")


def test_helpers():
    assert clean_image_url("https://a/b.jpg?hribi.net") == "https://a/b.jpg"
    assert clean_image_url("https://a/b.jpg?v=1") == "https://a/b.jpg?v=1"
    assert make_id("sele___zell", "1785", 1, 1) == "sele-zell-1785"
    assert make_id("pokljuka", "1700", 2, 3) == "pokljuka-1700-2"
