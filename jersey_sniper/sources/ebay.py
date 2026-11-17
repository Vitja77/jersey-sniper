"""eBay adapter using the official Browse API (free developer key: developer.ebay.com).
Searches auctions ending soonest + newly listed Buy-It-Now items."""
from __future__ import annotations

import base64
import time
from datetime import datetime, timezone

from ..models import Listing

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
ITEM_URL = "https://api.ebay.com/buy/browse/v1/item/{}"


class EbaySource:
    name = "ebay"

    def __init__(self, cfg: dict, http):
        self.cfg = cfg
        self.http = http
        self._token = None
        self._token_exp = 0

    def _auth(self) -> dict:
        if not self._token or time.time() > self._token_exp - 60:
            basic = base64.b64encode(f"{self.cfg['client_id']}:{self.cfg['client_secret']}".encode()).decode()
            r = self.http.session.post(
                TOKEN_URL,
                headers={"Authorization": f"Basic {basic}",
                         "Content-Type": "application/x-www-form-urlencoded"},
                data={"grant_type": "client_credentials",
                      "scope": "https://api.ebay.com/oauth/api_scope"},
                timeout=20,
            )
            r.raise_for_status()
            j = r.json()
            self._token, self._token_exp = j["access_token"], time.time() + j.get("expires_in", 7200)
        return {"Authorization": f"Bearer {self._token}",
                "X-EBAY-C-MARKETPLACE-ID": self.cfg.get("marketplace", "EBAY_DE")}

    def _search(self, q: str, auction: bool) -> list[dict]:
        params = {
            "q": q,
            "limit": str(self.cfg.get("limit", 50)),
            "sort": "endingSoonest" if auction else "newlyListed",
            "filter": "buyingOptions:{AUCTION}" if auction else "buyingOptions:{FIXED_PRICE}",
        }
        if self.cfg.get("max_price"):
            params["filter"] += f",price:[..{self.cfg['max_price']}],priceCurrency:{self.cfg.get('currency', 'EUR')}"
        r = self.http.session.get(SEARCH_URL, headers=self._auth(), params=params, timeout=25)
        r.raise_for_status()
        return r.json().get("itemSummaries", [])

    def _detail(self, item_id: str) -> dict:
        r = self.http.session.get(ITEM_URL.format(item_id), headers=self._auth(), timeout=25)
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _to_listing(s: dict, d: dict | None = None) -> Listing:
        d = d or {}
        src = d or s
        auction = "AUCTION" in (s.get("buyingOptions") or [])
        price = (s.get("currentBidPrice") if auction else None) or s.get("price") or {}
        ship = 0.0
        for opt in src.get("shippingOptions", []) or []:
            try:
                ship = float(opt.get("shippingCost", {}).get("value", 0))
                break
            except (TypeError, ValueError):
                pass
        imgs = []
        for im in [src.get("image")] + (src.get("additionalImages") or []):
            if im and im.get("imageUrl"):
                imgs.append(im["imageUrl"])
        end = s.get("itemEndDate")
        return Listing(
            source="ebay",
            id=s["itemId"],
            url=s.get("itemWebUrl", ""),
            title=s.get("title", ""),
            description=(d.get("description") or s.get("shortDescription") or "")[:5000],
            price=float(price["value"]) if price.get("value") else None,
            currency=price.get("currency", "EUR"),
            shipping=ship,
            is_auction=auction,
            ends_at=datetime.fromisoformat(end.replace("Z", "+00:00")) if end else None,
            image_urls=imgs,
            condition=" ".join(filter(None, [s.get("condition"), d.get("conditionDescription")])),
        )

    def fetch_listings(self, queries: list[str], prefilter=None):
        """prefilter(listing) -> bool lets the pipeline skip detail calls for obvious misses."""
        seen = set()
        for q in queries:
            for auction in (True, False):
                try:
                    items = self._search(q, auction)
                except Exception as e:  # noqa: BLE001
                    print(f"[ebay] search '{q}' failed: {e}")
                    continue
                for s in items:
                    if s.get("itemId") in seen:
                        continue
                    seen.add(s["itemId"])
                    lst = self._to_listing(s)
                    if prefilter and not prefilter(lst):
                        continue
                    try:
                        yield self._to_listing(s, self._detail(s["itemId"]))
                    except Exception as e:  # noqa: BLE001
                        print(f"[ebay] item {s['itemId']} failed: {e}")
                        yield lst
