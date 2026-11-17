"""HTTP client, seen-listings store, and notifications."""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


class Http:
    def __init__(self, timeout: int = 25):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.9"})
        self.timeout = timeout
        self._img_cache: dict[str, bytes] = {}

    def get_text(self, url: str, params=None, retries: int = 2) -> str:
        for attempt in range(retries + 1):
            r = self.session.get(url, params=params, timeout=self.timeout)
            if r.status_code == 429 and attempt < retries:
                time.sleep(30 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.text
        raise RuntimeError("unreachable")

    def get_image(self, url: str) -> bytes:
        if url.startswith(("/", "./")) or "://" not in url:  # local file (tests / check-image)
            return Path(url).read_bytes()
        if url not in self._img_cache:
            r = self.session.get(url, timeout=self.timeout)
            r.raise_for_status()
            self._img_cache[url] = r.content
            if len(self._img_cache) > 300:
                self._img_cache.pop(next(iter(self._img_cache)))
        return self._img_cache[url]


class Store:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path)
        self.db.execute("""CREATE TABLE IF NOT EXISTS seen(
            source TEXT, id TEXT, title TEXT, last_price REAL, alerted INTEGER DEFAULT 0,
            auth TEXT, rejected_reason TEXT, updated REAL, PRIMARY KEY(source, id))""")

    def get(self, source, id_):
        return self.db.execute("SELECT alerted, auth, rejected_reason FROM seen WHERE source=? AND id=?",
                               (source, id_)).fetchone()

    PERMANENT = ("not an NBA", "counterfeit", "condition:", "authenticity", "above max_price", "ended")

    def permanently_rejected(self, lot_id) -> bool:
        row = self.db.execute("SELECT rejected_reason FROM seen WHERE source='catawiki' AND id=?",
                              (str(lot_id),)).fetchone()
        return bool(row and row[0] and row[0].startswith(self.PERMANENT))

    def put(self, l, alerted=False, auth=None, reason=None):
        self.db.execute("""INSERT INTO seen VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(source,id) DO UPDATE SET last_price=excluded.last_price,
            alerted=MAX(alerted, excluded.alerted), auth=COALESCE(excluded.auth, auth),
            rejected_reason=excluded.rejected_reason, updated=excluded.updated""",
                        (l.source, l.id, l.title, l.price, int(alerted), auth, reason, time.time()))
        self.db.commit()


def format_deal(d) -> str:
    l = d.listing
    mins = l.minutes_left()
    left = f"{int(mins // 60)}h {int(mins % 60)}m left" if mins is not None else "buy now" if not l.is_auction else "end time unknown"
    sig = ""
    if d.signed:
        sig = " | SIGNED + COA" if d.has_coa else " | SIGNED (no COA!)"
    lines = [
        f"🏷  {d.sport.upper()} | {l.source} | {left}{sig}",
        f"{l.title}",
        f"Price now {l.price:.0f} {l.currency} -> all-in {d.landed_cost:.0f} | value ~{d.market_value:.0f} ({d.value_source})",
        f"Discount {d.discount:.0%} | expected profit after resale fees ~{d.expected_profit:.0f} {l.currency}",
        f"Authenticity: {d.auth.level} {('codes ' + ', '.join(d.auth.codes)) if d.auth.codes else ''}",
        f"  - " + "\n  - ".join(d.auth.reasons) if d.auth.reasons else "",
    ]
    if d.flags:
        lines.append("Flags: " + "; ".join(d.flags))
    lines.append(l.url)
    return "\n".join(x for x in lines if x)


class Notifier:
    def __init__(self, cfg: dict, http: Http):
        self.cfg = cfg or {}
        self.http = http

    def send(self, deal):
        msg = format_deal(deal)
        if self.cfg.get("console", True):
            print("\n" + "=" * 70 + "\n" + msg + "\n" + "=" * 70)
        tg = dict(self.cfg.get("telegram") or {})
        tg["bot_token"] = os.environ.get("TELEGRAM_BOT_TOKEN") or tg.get("bot_token")
        tg["chat_id"] = os.environ.get("TELEGRAM_CHAT_ID") or tg.get("chat_id")
        if tg.get("bot_token") and tg.get("chat_id"):
            try:
                self.http.session.post(f"https://api.telegram.org/bot{tg['bot_token']}/sendMessage",
                                       data={"chat_id": tg["chat_id"], "text": msg,
                                             "disable_web_page_preview": "false"}, timeout=15)
            except requests.RequestException as e:
                print(f"[notify] telegram failed: {e}")
        hook = self.cfg.get("discord_webhook")
        if hook:
            try:
                self.http.session.post(hook, json={"content": msg[:1990]}, timeout=15)
            except requests.RequestException as e:
                print(f"[notify] discord failed: {e}")
