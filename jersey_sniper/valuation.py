"""Work out what the shirt is worth, what it will really cost you, and the expected profit."""
from __future__ import annotations

import csv
import re
from pathlib import Path

from .models import Listing


class PriceBook:
    """data/reference_prices.csv: pattern,signed,value,notes
       pattern = regex matched (case-insensitive) against the title,
       signed  = yes | no | any,
       value   = typical resale price in your currency.
    First matching row wins, so put specific rows above generic ones."""

    def __init__(self, path: Path):
        self.rows = []
        if path.exists():
            lines = [ln for ln in path.read_text(encoding="utf-8").splitlines()
                     if ln.strip() and not ln.startswith("#")]
            for r in csv.DictReader(lines):
                try:
                    self.rows.append((re.compile(r["pattern"], re.I), r.get("signed", "any").strip().lower(),
                                      float(r["value"]), r.get("notes", "")))
                except (KeyError, ValueError, re.error):
                    continue

    def lookup(self, title: str, signed: bool) -> tuple[float, str] | None:
        for rx, s, value, notes in self.rows:
            if s == "yes" and not signed or s == "no" and signed:
                continue
            if rx.search(title):
                return value, f"price book: {rx.pattern}"
        return None


def landed_cost(l: Listing, src_cfg: dict) -> float:
    fee = src_cfg.get("buyer_fee_pct", 0.0)
    fixed = src_cfg.get("buyer_fixed_fee", 0.0)
    return (l.price or 0) * (1 + fee) + fixed + (l.shipping or 0)


def market_value(l: Listing, book: PriceBook, signed: bool, has_coa: bool, deal_cfg: dict):
    """Returns (value, source) or (None, reason)."""
    if l.estimate_low:
        # Catawiki experts estimate conservatively; the low end is a safe resale anchor
        return l.estimate_low, "expert estimate (low)"
    hit = book.lookup(l.title, signed and has_coa)
    if hit:
        return hit
    return None, "no reference value"


def profit(value: float, cost: float, deal_cfg: dict) -> float:
    net_sale = value * (1 - deal_cfg.get("resale_fee_pct", 0.13)) - deal_cfg.get("resale_shipping", 0)
    return net_sale - cost
