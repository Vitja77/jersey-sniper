"""Pages rebuilt from the data of 3 real Catawiki lots (read 15 Nov 2026). Run: python -m tests.test_catawiki_real"""
import json, yaml
from datetime import datetime, timezone, timedelta
from pathlib import Path
from jersey_sniper.sources.catawiki import parse_lot_html
from jersey_sniper.pipeline import Evaluator
from jersey_sniper.infra import Http

def page(title, sub, specs, est, bid, rate_si, desc, reserve=False, end_ms=None):
    end_ms = end_ms or int((datetime.now(timezone.utc)+timedelta(minutes=40)).timestamp()*1000)
    pp = {"_nextI18Next": {"x": {"title": "All auctions", "auction_current_bid": "Current bid"}},
          "lotDetailsData": {"lotTitle": title, "lotSubtitle": sub, "description": desc,
            "expertsEstimate": {"min": {"EUR": est[0], "GBP": 0}, "max": {"EUR": est[1]}, "type": "expert"},
            "specifications": [{"name": k, "value": v} for k, v in specs],
            "images": [{"large": f"https://assets.catawiki.nl/assets/x/{i}.jpg"} for i in range(3)],
            "shippingConfig": {"rates": [{"currencyCode": "EUR", "price": 3800, "regionCode": "at"},
                                         {"currencyCode": "EUR", "price": rate_si, "regionCode": "si"}]},
            "seo": {"ldSchema": {"offers": {"price": est[0]}}}},
          "biddingBlockResponse": {"localizedCurrentBidAmount": bid, "biddingEndTime": end_ms, "reservePriceMet": reserve}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps({"props":{"pageProps":pp}})}</script></html>'

lots = {
 "108345900": page("Boston Celtics - NBA - Kevin Garnett HOF Signed Boston Celtics Green Jersey Number 5 – Deluxe Framed - NBA Custom Jersey",
   "Replica - Mint - Certificate, framed, Hand signed in person",
   [("Sport","Basketball"),("Type","NBA Custom Jersey"),("Team","Boston Celtics"),("Condition","Mint"),("Original/ Replica","Replica"),("Extras","Certificate, Hand signed in person, framed")],
   (380,450), 220, 4900, "Kevin Garnett HOF hand signed green Boston Celtics jersey"),
 "108003329": page("Real Madrid - Spanish Football League - Cristiano Ronaldo - 2018 - Football jersey",
   "Very good - Hand signed, Limited & numbered edition, framed, with COA, Hand signed in person",
   [("Team","Real Madrid"),("Athlete","Cristiano Ronaldo"),("Condition","Very good"),("Brand","Adidas"),("Extras","Hand signed, with COA, framed"),("Year","2018"),("Authenticity","Original/official")],
   (1100,1300), 660, 3200, "Signed Cristiano Ronaldo Real Madrid 2018 shirt"),
 "108425960": page("NBA - Shawn Kemp - Custom Basketball Jersey", "Good - Limited edition, Hand signed",
   [("Sport","Basketball"),("Type","Custom Basketball Jersey"),("Brand","Custom jersey"),("Condition","Good")],
   (150,200), 90, 2500, "Shawn Kemp signed custom jersey"),
}
cfg = yaml.safe_load(Path("config.yaml").read_text())
ev = Evaluator(cfg, Path("data"), Http())
ev.http.get_image = lambda url: (_ for _ in ()).throw(IOError("offline"))  # no network in test
for lid, html in lots.items():
    l = parse_lot_html(lid, f"https://www.catawiki.com/en/l/{lid}", html, "si")
    print(f"\n{lid}: bid {l.price} | est {l.estimate_low}-{l.estimate_high} | ship {l.shipping} | {l.minutes_left():.0f} min left | imgs {len(l.image_urls)} | reserve_met {l.extra['reserve_met']}")
    print("   ->", ev.evaluate(l)[1])
