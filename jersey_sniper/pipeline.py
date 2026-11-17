"""Evaluate one listing: sport -> red flags -> condition -> price -> authenticity (OCR last, it's slow)."""
from __future__ import annotations

from .authcheck import CodeDB, level_ok, verify
from .filters import classify_sport, condition_check, fake_flags, signed_info
from .models import Deal, Listing
from .valuation import PriceBook, landed_cost, market_value, profit


class Evaluator:
    def __init__(self, cfg: dict, data_dir, http):
        self.cfg = cfg
        self.http = http
        self.codes = CodeDB(data_dir)
        self.book = PriceBook(data_dir / "reference_prices.csv")

    def cheap_prefilter(self, l: Listing) -> bool:
        sport = classify_sport(l.title)
        return bool(sport and sport in self.cfg["sports"]
                    and not fake_flags(l.title, self.cfg["authenticity"].get("replica_word_is_fake", True)))

    def evaluate(self, l: Listing) -> tuple[Deal | None, str]:
        """Returns (deal, reason). deal is None when rejected."""
        dc, ac = self.cfg["deal"], self.cfg["authenticity"]
        src_cfg = self.cfg["sources"].get(l.source, {})

        sport = classify_sport(l.title + "\n" + l.description[:600])
        if not sport or sport not in self.cfg["sports"]:
            return None, "not an NBA/football jersey"

        flags = fake_flags(l.text, ac.get("replica_word_is_fake", True))
        if flags:
            return None, f"counterfeit words: {', '.join(flags)}"

        ok, bad, good = condition_check(l.text)
        if not ok:
            return None, f"condition: {', '.join(bad)}"

        if l.price is None:
            return None, "no price found"
        if l.price > dc.get("max_price", 1e9):
            return None, "above max_price"

        mins = l.minutes_left()
        if l.is_auction and mins is not None:
            if mins < 0:
                return None, "ended"
            if mins > dc.get("auction_alert_window_minutes", 90):
                return None, "auction not ending soon yet (price not final)"

        signed, coa = signed_info(l.text)
        value, vsrc = market_value(l, self.book, signed, coa, dc)
        if value is None:
            return None, vsrc
        cost = landed_cost(l, src_cfg)
        exp = profit(value, cost, dc)
        disc = 1 - cost / value if value else 0
        if disc < dc.get("min_discount", 0.35) or exp < dc.get("min_profit", 40):
            return None, f"not cheap enough (discount {disc:.0%}, profit {exp:.0f})"

        # Only now run OCR - it's the slow step
        auth = verify(l, self.codes, self.http.get_image, ac)
        if auth.level == "FAIL" or not level_ok(auth.level, ac.get("min_level", "LIKELY")):
            return None, f"authenticity {auth.level}: {'; '.join(auth.reasons)}"

        extra = []
        specs = l.extra.get("specs") or {}
        if l.extra.get("reserve_met") is False:
            extra.append("reserve price NOT met yet - it won't sell at this bid; the real price will be higher")
        if specs.get("Authenticity"):
            auth.reasons.append(f"seller declares on Catawiki: {specs['Authenticity']}")
        if signed and not coa:
            extra.append("signed but no certificate mentioned - resale value of signature ~0 without COA")
        if good:
            extra.append("condition: " + ", ".join(good))
        if l.is_auction and mins is None:
            extra.append("couldn't read end time - check the bid isn't early")
        return Deal(l, sport, auth, value, vsrc, cost, exp, disc, signed, coa, extra), "deal"
