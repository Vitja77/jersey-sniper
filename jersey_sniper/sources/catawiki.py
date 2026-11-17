"""Catawiki adapter (best-effort HTML/JSON scraping - Catawiki has no public buyer API).

Catawiki changes its front-end from time to time. The parser therefore doesn't depend on
fixed CSS selectors: it reads the page's embedded JSON (Next.js __NEXT_DATA__ / JSON-LD /
other <script type="application/json"> blobs) and searches it for keys that look like
title, current bid, expert estimate, end time and images.
If a field stops being found, run:  python sniper.py debug-lot <lot url>
and adjust the KEY_* regexes below.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from html import unescape

from ..models import Listing

BASE = "https://www.catawiki.com"
LOT_RX = re.compile(r'/(?:[a-z]{2}/)?l/(\d{6,})')

KEY_TITLE = re.compile(r"^(title|name|lotTitle|lot_title)$", re.I)
KEY_BID = re.compile(r"(current_?bid|highest_?bid|currentBidAmount|bid_?amount|latestBid)", re.I)
KEY_EST_LOW = re.compile(r"(estimate.*(min|low|from)|(min|low).*estimate|expertsEstimate.*min)", re.I)
KEY_EST_HIGH = re.compile(r"(estimate.*(max|high|to)|(max|high).*estimate|expertsEstimate.*max)", re.I)
KEY_END = re.compile(r"(bidding_?end|biddingEnd|end_?(date|time|at)|closes?_?at|closingTime|auctionEnd)", re.I)
KEY_DESC = re.compile(r"^(description|lotDescription|lot_description)$", re.I)
KEY_COND = re.compile(r"(condition)", re.I)
KEY_SHIP = re.compile(r"(shipping_?(cost|price|fee)|shippingCost)", re.I)
IMG_RX = re.compile(r'https://assets\.catawiki\.(?:nl|com)/[^"\'\s\\]+?\.(?:jpe?g|png|webp)', re.I)


class CatawikiSource:
    name = "catawiki"

    def __init__(self, cfg: dict, http):
        self.cfg = cfg
        self.http = http
        self.lang = cfg.get("lang", "en")

    # ---------- search ----------
    def search(self, query: str) -> list[str]:
        url = f"{BASE}/{self.lang}/s"
        html = self.http.get_text(url, params={"q": query})
        ids = []
        for m in LOT_RX.finditer(html):
            if m.group(1) not in ids:
                ids.append(m.group(1))
        return ids[: self.cfg.get("max_lots_per_query", 40)]

    def fetch_listings(self, queries: list[str], skip=None):
        seen = set()
        for q in queries:
            try:
                ids = self.search(q)
            except Exception as e:  # noqa: BLE001
                print(f"[catawiki] search '{q}' failed: {e}")
                continue
            for lot_id in ids:
                if lot_id in seen or (skip and skip(lot_id)):
                    continue
                seen.add(lot_id)
                time.sleep(self.cfg.get("request_delay_s", 3))
                try:
                    yield self.fetch_lot(lot_id)
                except Exception as e:  # noqa: BLE001
                    print(f"[catawiki] lot {lot_id} failed: {e}")

    # ---------- lot page ----------
    def fetch_lot(self, lot_id_or_url: str) -> Listing:
        m = LOT_RX.search(lot_id_or_url)
        lot_id = m.group(1) if m else lot_id_or_url
        url = f"{BASE}/{self.lang}/l/{lot_id}"
        html = self.http.get_text(url)
        return parse_lot_html(lot_id, url, html, self.cfg.get("ship_to", "si"))


# ---------- parsing helpers (module level so they can be unit tested) ----------
def _json_blobs(html: str):
    for m in re.finditer(r'<script[^>]*type="application/(?:ld\+)?json"[^>]*>(.*?)</script>', html, re.S):
        try:
            yield json.loads(unescape(m.group(1)) if m.group(1).lstrip().startswith("&") else m.group(1))
        except json.JSONDecodeError:
            continue
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if m:
        try:
            yield json.loads(m.group(1))
        except json.JSONDecodeError:
            pass


def _walk(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "_nextI18Next":  # UI translation strings, not lot data
                continue
            yield k, v, path
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v, path)


def _money(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = re.sub(r"[^\d,.]", "", v).replace(",", ".")
        try:
            return float(s) if s else None
        except ValueError:
            return None
    if isinstance(v, dict):
        for k in ("amount", "value", "EUR", "eur", "price"):
            if k in v:
                return _money(v[k])
    return None


def _time(v) -> datetime | None:
    try:
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, tz=timezone.utc)
        if isinstance(v, str) and re.match(r"\d{4}-\d{2}-\d{2}T", v):
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, OSError):
        return None
    return None


def _meta(html: str, prop: str) -> str | None:
    m = re.search(rf'<meta[^>]+(?:property|name)="{re.escape(prop)}"[^>]+content="([^"]*)"', html)
    return unescape(m.group(1)) if m else None


def _next_data(html: str):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _eur(v, currency="EUR"):
    if isinstance(v, dict):
        return _money(v.get(currency)) or None
    return _money(v)


def parse_structured(lot_id: str, url: str, html: str, ship_to: str = "si",
                     currency: str = "EUR") -> Listing | None:
    """Catawiki's real layout (checked on live lots, Nov 2026):
    props.pageProps.lotDetailsData  -> lotTitle, lotSubtitle, description, expertsEstimate{min,max},
                                       specifications[{name,value}], images[{large}], shippingConfig.rates
    props.pageProps.biddingBlockResponse -> localizedCurrentBidAmount, biddingEndTime (ms), reservePriceMet
    """
    nd = _next_data(html)
    try:
        pp = nd["props"]["pageProps"]
        d = pp["lotDetailsData"]
    except (TypeError, KeyError):
        return None
    b = pp.get("biddingBlockResponse") or {}
    live_lot = (b.get("live") or {}).get("lot") or {}

    specs = {s.get("name", "").strip(): str(s.get("value", "")).strip()
             for s in d.get("specifications") or [] if s.get("name")}
    # the spec *name* "Original/ Replica" contains the word replica -> rename so filters only see the value
    spec_text = "\n".join(f"{'Version' if 'replica' in k.lower() else k}: {v}" for k, v in specs.items())

    bid = _money(b.get("localizedCurrentBidAmount"))
    if bid is None:
        bid = _eur(live_lot.get("bid"), currency)
    if not bid:  # no bids yet -> the opening bid is the price
        bid = _money(b.get("localizedStartBidAmount")) or _money(b.get("localizedMinBidAmount"))

    est = d.get("expertsEstimate") or {}
    ship = 0.0
    for r in (d.get("shippingConfig") or {}).get("rates") or []:
        if str(r.get("regionCode", "")).lower() == ship_to.lower():
            ship = (_money(r.get("price")) or 0) / 100  # cents
            break

    images = [im.get("large") or im.get("medium") or im.get("id")
              for im in d.get("images") or [] if isinstance(im, dict)]

    return Listing(
        source="catawiki",
        id=str(lot_id),
        url=url,
        title=(d.get("lotTitle") or "").strip(),
        description="\n".join(filter(None, [d.get("lotSubtitle"), spec_text, d.get("description")])),
        price=bid,
        currency=currency,
        shipping=ship,
        is_auction=True,
        ends_at=_time(b.get("biddingEndTime") or live_lot.get("biddingEndTime")),
        image_urls=[u for u in images if u],
        estimate_low=_eur(est.get("min"), currency),
        estimate_high=_eur(est.get("max"), currency),
        condition=specs.get("Condition", ""),
        extra={
            "specs": specs,
            "reserve_met": b.get("reservePriceMet"),
            "closed": b.get("closed") or d.get("isClosed"),
            "parsed_fields": "structured",
        },
    )


def parse_lot_html(lot_id: str, url: str, html: str, ship_to: str = "si") -> Listing:
    structured = parse_structured(lot_id, url, html, ship_to)
    if structured and structured.title:
        return structured
    # ---- generic fallback if Catawiki changes its layout ----
    found: dict[str, object] = {}

    def take(key, val):
        if key not in found and val not in (None, "", []):
            found[key] = val

    for blob in _json_blobs(html):
        for k, v, _ in _walk(blob):
            if KEY_BID.search(k):
                take("bid", _money(v))
            elif KEY_EST_LOW.search(k):
                take("est_low", _money(v))
            elif KEY_EST_HIGH.search(k):
                take("est_high", _money(v))
            elif KEY_END.search(k):
                take("end", _time(v))
            elif KEY_DESC.match(k) and isinstance(v, str) and len(v) > 20:
                take("desc", re.sub(r"<[^>]+>", " ", v))
            elif KEY_TITLE.match(k) and isinstance(v, str) and len(v) > 8:
                take("title", v)
            elif KEY_COND.search(k) and isinstance(v, str):
                take("cond", v)
            elif KEY_SHIP.search(k):
                take("ship", _money(v))
            # NB: JSON-LD offers.price on Catawiki is the ESTIMATE, not the current bid - don't use it

    # Estimate is often only in visible text: "Expert's estimate €200 - €300"
    if "est_low" not in found:
        m = re.search(r"estimate[^€$£\d]{0,40}[€$£]\s?([\d.,]+)\s*[-–]\s*[€$£]?\s?([\d.,]+)", html, re.I)
        if m:
            found["est_low"], found["est_high"] = _money(m.group(1)), _money(m.group(2))

    images = []
    og = _meta(html, "og:image")
    if og:
        images.append(og)
    for im in IMG_RX.findall(html.replace("\\u002F", "/").replace("\\/", "/")):
        # prefer large versions, skip thumbnails
        if any(s in im for s in ("/thumb", "_s.", "-s.", "/small")):
            continue
        if im not in images:
            images.append(im)

    return Listing(
        source="catawiki",
        id=str(lot_id),
        url=url,
        title=str(found.get("title") or _meta(html, "og:title") or ""),
        description=str(found.get("desc") or _meta(html, "og:description") or ""),
        price=found.get("bid"),
        shipping=found.get("ship") or 0.0,
        is_auction=True,
        ends_at=found.get("end"),
        image_urls=images,
        estimate_low=found.get("est_low"),
        estimate_high=found.get("est_high"),
        condition=str(found.get("cond") or ""),
        extra={"parsed_fields": sorted(found.keys())},
    )
