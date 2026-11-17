"""Offline tests: OCR on synthetic tag images + full pipeline on fake listings. Run: python -m tests.test_offline"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile, yaml
from PIL import Image, ImageDraw, ImageFont

from jersey_sniper.authcheck import extract_codes, detect_brand, ocr_image
from jersey_sniper.infra import Http, format_deal
from jersey_sniper.models import Listing
from jersey_sniper.pipeline import Evaluator
from jersey_sniper.sources.catawiki import parse_lot_html

ROOT = Path(__file__).resolve().parent.parent
tmp = Path(tempfile.mkdtemp())

def tag(lines, name, rotate=0):
    im = Image.new("RGB", (700, 420), "white"); d = ImageDraw.Draw(im)
    try: f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)
    except OSError: f = ImageFont.load_default()
    for i, t in enumerate(lines): d.text((40, 40 + i * 55), t, fill="black", font=f)
    im = im.rotate(rotate, expand=True); p = tmp / name; im.save(p, quality=70); return str(p)

nike_tag = tag(["NIKE", "MADE IN THAILAND", "100% POLYESTER", "CW3858-100", "M / M"], "nike.jpg")
side_tag = tag(["adidas", "FABRIQUE EN CHINE", "ART. GH7656", "SIZE L"], "adidas.jpg", rotate=90)

# 1. OCR + code extraction
for p in (nike_tag, side_tag):
    txt = ocr_image(Path(p).read_bytes())
    b = detect_brand(txt); print(p.split('/')[-1], "->", b, extract_codes(txt, b))

# 2. OCR-confusion normalisation
print("noisy:", extract_codes("style CW38S8-1OO nike", "nike"), extract_codes("GH76S6", "adidas"))

# 3. Pipeline
cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
data = tmp / "data"; data.mkdir()
(data / "known_codes.csv").write_text("code,brand,team,season,kit,version,notes\nCW3858-100,nike,Lakers,2020-21,home,swingman,test\n")
(data / "fake_codes.csv").write_text("code,notes\n")
(data / "reference_prices.csv").write_text((ROOT / "data/reference_prices.csv").read_text())
ev = Evaluator(cfg, data, Http())
soon = datetime.now(timezone.utc) + timedelta(minutes=30)
cases = [
  Listing("catawiki","1","u","Nike Los Angeles Lakers James #23 swingman jersey","Excellent condition, with tags",
          price=60, ends_at=soon, image_urls=[nike_tag], estimate_low=180, estimate_high=250),
  Listing("catawiki","2","u","Nike Barcelona home shirt 2020","very good", price=40, ends_at=soon,
          image_urls=[nike_tag], estimate_low=150),          # Lakers code on Barca shirt -> FAIL
  Listing("catawiki","3","u","Real Madrid shirt replica AAA thai version","", price=10, estimate_low=100),
  Listing("catawiki","4","u","Lakers jersey nba","has a stain on the back", price=10, estimate_low=100, ends_at=soon),
  Listing("catawiki","5","u","Signed Juventus shirt 2019 with COA","Beckett certificate", price=300, ends_at=soon, estimate_low=350),
  Listing("ebay","6","u","Adidas Bayern trikot 2021 home","neu mit etikett", price=25, is_auction=False,
          image_urls=[side_tag]),                            # no reference price -> skipped
  Listing("catawiki","7","u","Kansas City Chiefs NFL jersey","", price=20, estimate_low=200, ends_at=soon),
]
for l in cases:
    deal, why = ev.evaluate(l)
    print(f"\n#{l.id} {l.title[:45]!r}: {why}")
    if deal: print(format_deal(deal))

# 4. Catawiki parser on a synthetic page
html = '''<html><head><meta property="og:title" content="Nike Chicago Bulls Jordan jersey"/>
<meta property="og:image" content="https://assets.catawiki.com/assets/2026/1/1/a/b/c/abc.jpg"/></head>
<script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"lot":{"title":"Nike Chicago Bulls Jordan #23 jersey",
"description":"Authentic jersey, excellent condition, tag code visible in photos",
"biddingEndTime":"2026-11-16T19:00:00Z","currentBid":{"amount":120,"currency":"EUR"},
"expertsEstimateMin":300,"expertsEstimateMax":400,
"images":[{"url":"https://assets.catawiki.com/assets/2026/1/1/d/e/f/def.jpg"}]}}}}</script></html>'''
l = parse_lot_html("123", "https://www.catawiki.com/en/l/123", html)
print("\ncatawiki parse:", l.title, l.price, l.estimate_low, l.estimate_high, l.ends_at, len(l.image_urls), l.extra)
