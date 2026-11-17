#!/usr/bin/env python3
"""Jersey Sniper - finds underpriced genuine NBA & football jerseys on Catawiki and eBay.

  python sniper.py run                 # loop forever, scan every poll_minutes
  python sniper.py once                # one scan, then exit
  python sniper.py once -v             # ...and print why each listing was rejected
  python sniper.py check-image tag.jpg # test the code reader on your own photo
  python sniper.py debug-lot <catawiki lot url>   # show what the parser extracts from a lot
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import yaml

from jersey_sniper.authcheck import detect_brand, extract_codes, ocr_image
from jersey_sniper.infra import Http, Notifier, Store
from jersey_sniper.pipeline import Evaluator
from jersey_sniper.sources import CatawikiSource, EbaySource

ROOT = Path(__file__).parent


def load_cfg(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def scan(cfg, http, ev, store, notifier, verbose=False):
    found = 0
    srcs = []
    if cfg["sources"]["catawiki"].get("enabled"):
        cw = CatawikiSource(cfg["sources"]["catawiki"], http)
        srcs.append(cw.fetch_listings(cfg["queries"]["catawiki"], store.permanently_rejected))
    ec = cfg["sources"]["ebay"]
    ec["client_id"] = os.environ.get("EBAY_CLIENT_ID") or ec.get("client_id")
    ec["client_secret"] = os.environ.get("EBAY_CLIENT_SECRET") or ec.get("client_secret")
    if ec.get("client_id"):
        ec["enabled"] = True
    if ec.get("enabled"):
        if not ec.get("client_id"):
            print("[ebay] enabled but no client_id/client_secret in config - skipping")
        else:
            srcs.append(EbaySource(ec, http).fetch_listings(cfg["queries"]["ebay"], ev.cheap_prefilter))

    for gen in srcs:
        for l in gen:
            prev = store.get(l.source, l.id)
            if prev and prev[0]:          # already alerted
                continue
            deal, reason = ev.evaluate(l)
            if deal:
                notifier.send(deal)
                store.put(l, alerted=True, auth=deal.auth.level)
                found += 1
            else:
                store.put(l, reason=reason)
                if verbose:
                    print(f"  skip [{l.source} {l.id}] {l.title[:60]!r}: {reason}")
    return found


def telegram_setup(http):
    token = input("Paste your bot token from @BotFather: ").strip()
    me = http.session.get(f"https://api.telegram.org/bot{token}/getMe", timeout=15).json()
    if not me.get("ok"):
        print("That token doesn't work - copy it again from BotFather."); return
    input(f"Now open Telegram, find @{me['result']['username']}, press START (or send 'hi'), then press Enter here...")
    upd = http.session.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=15).json()
    chats = [u["message"]["chat"]["id"] for u in upd.get("result", []) if "message" in u]
    if not chats:
        print("No message found - send the bot a message and run this again."); return
    chat_id = chats[-1]
    http.session.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat_id, "text": "✅ Jersey Sniper is connected!"}, timeout=15)
    print(f"\nWorked! Check Telegram for a test message.\n\nTELEGRAM_BOT_TOKEN = {token}\nTELEGRAM_CHAT_ID   = {chat_id}\n"
          "\nPut these two into GitHub -> Settings -> Secrets and variables -> Actions.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run", "once", "check-image", "debug-lot", "telegram-setup"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("-c", "--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    cfg = load_cfg(Path(a.config))
    http = Http()

    if a.cmd == "telegram-setup":
        telegram_setup(http)
        return

    if a.cmd == "check-image":
        data = http.get_image(a.arg)
        text = ocr_image(data, cfg["authenticity"].get("ocr_lang", "eng"))
        brand = detect_brand(text)
        print("OCR text:\n" + "-" * 40 + f"\n{text.strip()}\n" + "-" * 40)
        print(f"brand detected: {brand}")
        print(f"codes found: {extract_codes(text, brand) or 'none'}")
        return

    if a.cmd == "debug-lot":
        l = CatawikiSource(cfg["sources"]["catawiki"], http).fetch_lot(a.arg)
        for k, v in l.__dict__.items():
            print(f"{k:14} {str(v)[:200]}")
        return

    ev = Evaluator(cfg, ROOT / "data", http)
    store = Store(ROOT / "data" / "seen.sqlite")
    notifier = Notifier(cfg.get("notify"), http)

    while True:
        t0 = time.time()
        print(f"[{time.strftime('%H:%M:%S')}] scanning...")
        try:
            n = scan(cfg, http, ev, store, notifier, a.verbose)
            print(f"[{time.strftime('%H:%M:%S')}] done in {time.time() - t0:.0f}s, {n} new deal(s)")
        except KeyboardInterrupt:
            sys.exit(0)
        except Exception as e:  # noqa: BLE001
            print(f"scan error: {e}")
        if a.cmd == "once":
            break
        time.sleep(cfg.get("poll_minutes", 5) * 60)


if __name__ == "__main__":
    main()
