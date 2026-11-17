"""Authenticity check: read the product/style code off the listing photos (wash tag, neck tag,
swing tag) with OCR, validate it against the brand's code format and against your own
database of known genuine / known fake codes.

Levels (best -> worst):
  PASS        code read from a photo AND found in known_codes.csv for the same team
  LIKELY      code read from a photo, correct format for the brand, not on the fake list
  WEAK        code only appears in the seller's text, not readable in any photo
  UNVERIFIED  no code found at all
  FAIL        code on fake list, code belongs to a different team, wrong brand format,
              or counterfeit words in the listing
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

from .models import AuthResult, Listing

try:
    import pytesseract
except ImportError:  # pragma: no cover
    pytesseract = None

LEVELS = ["FAIL", "UNVERIFIED", "WEAK", "LIKELY", "PASS"]

# OCR confuses these; normalise depending on whether the slot should be a digit or a letter
_D = "[0-9OoQDIlSBZ]"
_L = "[A-Z0158]"
_TO_DIGIT = str.maketrans({"O": "0", "o": "0", "Q": "0", "D": "0", "I": "1", "l": "1",
                           "S": "5", "B": "8", "Z": "2"})
_TO_LETTER = str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B"})

# brand -> list of (regex, normaliser)
def _nike(m):  # CW3858-100  /  658894-106
    pre, suf = m.group(1), m.group(2)
    if len(pre) == 6 and pre[:2].translate(_TO_DIGIT).isdigit() and not pre[:2].isalpha():
        pre = pre.translate(_TO_DIGIT)
    else:
        pre = pre[:2].translate(_TO_LETTER) + pre[2:].translate(_TO_DIGIT)
    return f"{pre}-{suf.translate(_TO_DIGIT)}"


def _adidas(m):  # GH7656 / H31090
    s = m.group(0)
    if s[:2].isalpha():
        return s[:2] + s[2:].translate(_TO_DIGIT)
    return s[0].translate(_TO_LETTER) + s[1:].translate(_TO_DIGIT)


def _puma(m):  # 765722 01
    return f"{m.group(1).translate(_TO_DIGIT)} {m.group(2).translate(_TO_DIGIT)}"


def _nb(m):  # MT930000
    s = m.group(0)
    return s[:2].translate(_TO_LETTER) + s[2:].translate(_TO_DIGIT)


CODE_PATTERNS: dict[str, list] = {
    "nike": [(re.compile(rf"(?<![A-Z0-9])((?:{_L}{{2}}|{_D}{{2}}){_D}{{4}})\s?[-–—_]\s?({_D}{{3}})(?![0-9])"), _nike)],
    "adidas": [(re.compile(rf"(?<![A-Za-z0-9])(?:[A-Z]{{2}}{_D}{{4}}|[A-Z]{_D}{{5}})(?![A-Za-z0-9])"), _adidas)],
    "puma": [(re.compile(rf"(?<![0-9])({_D}{{6}})[ -]({_D}{{2}})(?![0-9])"), _puma)],
    "new balance": [(re.compile(rf"(?<![A-Za-z0-9])[A-Z]{{2}}{_D}{{6}}(?![A-Za-z0-9])"), _nb)],
}
STRICT_FORMAT = {
    "nike": re.compile(r"^(?:[A-Z]{2}\d{4}|\d{6})-\d{3}$"),
    "adidas": re.compile(r"^(?:[A-Z]{2}\d{4}|[A-Z]\d{5})$"),
    "puma": re.compile(r"^\d{6} \d{2}$"),
    "new balance": re.compile(r"^[A-Z]{2}\d{6}$"),
}
BRAND_WORDS = {
    "nike": ["nike", "jordan", "dri-fit", "dri fit", "vaporknit", "aeroswift"],
    "adidas": ["adidas", "climacool", "heat.rdy", "heat rdy", "adizero"],
    "puma": ["puma", "drycell"],
    "new balance": ["new balance"],
    # brands we recognise but have no reliable code format for
    "other": ["umbro", "kappa", "macron", "hummel", "castore", "le coq", "reebok", "champion",
              "mitchell & ness", "mitchell and ness", "lotto", "diadora", "joma", "errea",
              "under armour", "erreà", "admiral", "le coq sportif"],
}
# Common junk the adidas pattern could catch on a tag
_JUNK = {"XL2020", "XS2020"}


def detect_brand(text: str) -> str | None:
    t = text.lower()
    for brand, words in BRAND_WORDS.items():
        if any(w in t for w in words):
            return None if brand == "other" else brand
    return None


def extract_codes(text: str, brand: str | None) -> list[tuple[str, str]]:
    """Return [(brand, code)] found in text. If brand known, only that brand's patterns."""
    brands = [brand] if brand in CODE_PATTERNS else list(CODE_PATTERNS)
    out: list[tuple[str, str]] = []
    for b in brands:
        for rx, norm in CODE_PATTERNS[b]:
            for m in rx.finditer(text):
                code = norm(m)
                if code in _JUNK or not STRICT_FORMAT[b].match(code):
                    continue
                if (b, code) not in out:
                    out.append((b, code))
    # without a known brand the adidas/NB patterns are noisy -> keep nike/puma only
    if brand is None:
        out = [(b, c) for b, c in out if b in ("nike", "puma")] or out[:2]
    return out


def ocr_image(data: bytes, lang: str = "eng") -> str:
    if pytesseract is None:
        raise RuntimeError("pytesseract not installed")
    im = Image.open(io.BytesIO(data))
    im = ImageOps.exif_transpose(im).convert("L")
    w, h = im.size
    scale = 2200 / max(w, h)
    if scale > 1.05:
        im = im.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    variants = [
        ImageOps.autocontrast(im),
        ImageOps.autocontrast(im).filter(ImageFilter.SHARPEN).point(lambda p: 255 if p > 140 else 0),
    ]
    texts = []
    for v in variants:
        texts.append(pytesseract.image_to_string(v, lang=lang, config="--psm 11"))
    # tags are often photographed sideways
    for angle in (90, 270):
        texts.append(pytesseract.image_to_string(variants[0].rotate(angle, expand=True),
                                                 lang=lang, config="--psm 11"))
    return "\n".join(texts)


class CodeDB:
    """known_codes.csv: code,brand,team,season,kit,version,notes
       fake_codes.csv:  code,notes"""

    def __init__(self, data_dir: Path):
        self.known: dict[str, dict] = {}
        self.fake: dict[str, str] = {}
        kp, fp = data_dir / "known_codes.csv", data_dir / "fake_codes.csv"
        if kp.exists():
            for row in csv.DictReader(_strip_comments(kp)):
                if row.get("code"):
                    self.known[row["code"].strip().upper()] = row
        if fp.exists():
            for row in csv.DictReader(_strip_comments(fp)):
                if row.get("code"):
                    self.fake[row["code"].strip().upper()] = row.get("notes", "")


def _strip_comments(path: Path):
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]


def verify(listing: Listing, db: CodeDB, fetch_image, cfg: dict) -> AuthResult:
    text = listing.text
    brand = detect_brand(text)
    res = AuthResult(level="UNVERIFIED", brand=brand)

    image_codes: list[tuple[str, str]] = []
    for url in listing.image_urls[: cfg.get("max_images", 8)]:
        try:
            data = fetch_image(url)
            ocr_text = ocr_image(data, cfg.get("ocr_lang", "eng"))
        except Exception as e:  # noqa: BLE001
            res.reasons.append(f"image skipped ({e.__class__.__name__})")
            continue
        img_brand = brand or detect_brand(ocr_text)
        for bc in extract_codes(ocr_text, img_brand):
            if bc not in image_codes:
                image_codes.append(bc)
        if brand is None and img_brand:
            res.brand = brand = img_brand

    text_codes = [bc for bc in extract_codes(text, brand) if bc not in image_codes]
    res.codes = [c for _, c in image_codes] + [c for _, c in text_codes]

    # 1. known fakes
    for c in res.codes:
        if c.upper() in db.fake:
            res.level = "FAIL"
            res.reasons.append(f"code {c} is on your fake list ({db.fake[c.upper()]})")
            return res

    # 2. different brands' codes on one shirt -> suspicious
    if len({b for b, _ in image_codes}) > 1 and brand:
        res.reasons.append("codes from multiple brand formats in photos")

    # 3. known genuine codes: team must match the listing
    for _, c in image_codes:
        row = db.known.get(c.upper())
        if not row:
            continue
        team = (row.get("team") or "").lower()
        if team and team not in text.lower():
            res.level = "FAIL"
            res.reasons.append(f"code {c} belongs to {row['team']} {row.get('season','')}, "
                               f"not the team in the listing (classic fake sign)")
            return res
        res.level = "PASS"
        res.reasons.append(f"code {c} matches {row.get('team')} {row.get('season','')} "
                           f"{row.get('kit','')} {row.get('version','')}".strip())
        return res

    if image_codes:
        res.level = "LIKELY"
        res.reasons.append(f"code {image_codes[0][1]} read from photo, valid {image_codes[0][0]} format, "
                           "not in your database yet - verify on Google before bidding")
    elif text_codes:
        res.level = "WEAK"
        res.reasons.append("code only in seller text, not readable in photos")
    else:
        res.reasons.append("no product code found in photos (ask seller for a clear tag photo)")
    return res


def level_ok(level: str, minimum: str) -> bool:
    return LEVELS.index(level) >= LEVELS.index(minimum)
