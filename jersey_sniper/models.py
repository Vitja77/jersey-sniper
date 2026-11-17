from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Listing:
    source: str
    id: str
    url: str
    title: str
    description: str = ""
    price: float | None = None          # current bid (auction) or asking price (buy-now)
    currency: str = "EUR"
    shipping: float = 0.0
    is_auction: bool = True
    ends_at: datetime | None = None
    image_urls: list[str] = field(default_factory=list)
    estimate_low: float | None = None   # e.g. Catawiki expert estimate
    estimate_high: float | None = None
    condition: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.condition}\n{self.description}"

    def minutes_left(self) -> float | None:
        if not self.ends_at:
            return None
        return (self.ends_at - datetime.now(timezone.utc)).total_seconds() / 60


@dataclass
class AuthResult:
    level: str                      # PASS | LIKELY | WEAK | UNVERIFIED | FAIL
    codes: list[str] = field(default_factory=list)
    brand: str | None = None
    reasons: list[str] = field(default_factory=list)


@dataclass
class Deal:
    listing: Listing
    sport: str
    auth: AuthResult
    market_value: float
    value_source: str
    landed_cost: float
    expected_profit: float
    discount: float
    signed: bool
    has_coa: bool
    flags: list[str] = field(default_factory=list)
