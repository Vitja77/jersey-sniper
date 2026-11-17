# Jersey Sniper 🏀⚽

Scans **Catawiki** and **eBay** for **NBA and football jerseys** selling well below their value,
reads the **product code off the listing photos** (OCR) to weed out fakes, and alerts you
(terminal, Telegram, Discord) shortly before the auction ends.

## What it checks, in order

1. **Is it an NBA / football jersey?** Recognises team, league and "shirt" words in EN/NL/DE/FR/IT/ES.
   Throws out NFL, NHL, t-shirts, posters and similar.
2. **Counterfeit words.** Rejects listings that say *replica, AAA, thai version, 1:1, copy,
   inspired*, etc.
3. **Condition.** Rejects listings that mention *stain, hole, cracked print, peeling, faded*, etc.
4. **Price.** Adds the buyer's fee and shipping to get the all-in cost. Compares it with the market
   value: Catawiki's expert estimate, or your own `reference_prices.csv`. It then works out the
   profit after resale fees.
   - For auctions, it only alerts in the **last 90 minutes**, because earlier bids mean nothing.
   - A signed shirt only counts at signed value if a **COA** (Beckett, PSA, JSA, Fanatics…) is mentioned.
5. **Authenticity from photos.** Every photo is OCR'd, including sideways shots, to find the style code:
   - Nike / Jordan `CW3858-100` · Adidas `GH7656` · Puma `765722 01` · New Balance `MT930000`
   - The code is checked against **your** `known_codes.csv` and `fake_codes.csv`.
   - A **Lakers code on a Barcelona shirt = FAIL**, which is the classic fake giveaway.

| Level | Meaning |
|---|---|
| PASS | Code read from a photo, in your genuine list, and for the same team |
| LIKELY | Valid code format read from a photo, not in your list yet (Google it) |
| WEAK | Code only typed by the seller, not visible in the photos |
| UNVERIFIED | No code found |
| FAIL | Fake list, wrong team, or counterfeit words |

By default you only get **LIKELY** and **PASS** alerts (`authenticity.min_level`).

## Setup

```bash
# 1. Tesseract OCR engine
#    Windows: https://github.com/UB-Mannheim/tesseract/wiki   (add to PATH)
#    macOS:   brew install tesseract
#    Linux:   sudo apt install tesseract-ocr
# 2. Python packages
pip install -r requirements.txt
# 3. Test the code reader on a photo of a real tag
python sniper.py check-image path/to/tag_photo.jpg
# 4. One scan, showing why each listing was skipped
python sniper.py once -v
# 5. Run continuously
python sniper.py run
```

**Phone alerts:** create a bot with @BotFather on Telegram. Put its token and your chat id
into `config.yaml` under `notify.telegram`.

**eBay:** create a free app at developer.ebay.com, paste the production `client_id` and
`client_secret` into `config.yaml`, then set `enabled: true`.

## Make it accurate (important)

- **`data/reference_prices.csv`**: the rows are **placeholders**. Replace them with real sold
  prices for the shirts you trade. eBay has no expert estimates, so without this file eBay
  listings are never alerted.
- **`data/known_codes.csv`**: each time you confirm a genuine code, add it. More codes means more
  PASS results and more caught fakes.
- **`data/fake_codes.csv`**: add codes you catch on fakes.

## Limits — read before you bid

- **A valid code does not prove a shirt is genuine.** Good fakes copy real codes. The code
  check removes most junk, but still check the photos yourself: stitching, crest, sponsor
  print, and the tag font compared with a known-real tag.
- OCR needs a sharp, close tag photo. If there isn't one, ask the seller for one.
- **Catawiki has no public API.** The adapter reads each lot page's embedded data. It was checked
  on live lots in Nov 2026 and reads the current bid, expert estimate, end time, shipping to your
  country (`ship_to`), photos, and Catawiki's own *Original/Replica*, *Authenticity* and *Condition*
  fields. Custom jerseys and lots marked Replica are rejected. Lots below their reserve price are
  flagged. If Catawiki redesigns, fields can go missing. `python sniper.py debug-lot <lot url>` shows what is
  being extracted. Check Catawiki's terms on automated access and keep `request_delay_s` polite.
- It **alerts; it doesn't bid**. You place the bid yourself.
- In football, "replica" also means the official fan version. Set
  `replica_word_is_fake: false` if you want those too.
