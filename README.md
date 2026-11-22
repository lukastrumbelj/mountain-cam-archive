# Arhiv slovenskih gorskih spletnih kamer

Samodejno zajema slike gorskih kamer in jih arhivira (zadnjih 7 dni). Stanje: **faza 2**, lokalni zajem. R2, Actions in spletna stran sledijo.

## Lokalni zagon

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium        # samo če uporabljaš mode selector/screenshot/custom

python scripts/test_camera.py --validate        # preveri cameras.yaml
python scripts/test_camera.py kamnisko-sedlo    # ena kamera -> out/kamnisko-sedlo.jpg
python scripts/test_camera.py --all             # vse aktivne kamere
python -m pytest tests                          # offline testi
```

## Dodajanje kamere

Samo nov blok v `config/cameras.yaml`:

```yaml
  - id: moja-kamera          # a-z, 0-9, -
    name: Moja kamera
    location: Kraj, gorovje
    url: https://stran-kamere.si/
    mode: direct             # direct | selector | screenshot | custom
    image_url: https://.../slika.jpg
    wait_seconds: 0
    active: true
```

Za `selector` dodaj `selector: "img#cam"`. Za `custom` lahko dodaš `extra.steps` (`click`, `wait`, `hide`).

## Pravila

- Sistem ne obhaja prijav, CAPTCHA ali drugih zaščit. Če jih zazna, kamero preskoči.
- Pred vklopom kamere preveri pogoje uporabe vira.
- Skrivnosti (R2 ključi, tokeni) so samo v GitHub Secrets / Cloudflare secrets, nikoli v repozitoriju.
