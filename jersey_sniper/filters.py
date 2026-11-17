"""Text classification: is it an NBA / football jersey, is it a fake, is it signed, what condition."""
from __future__ import annotations

import re

NBA_TEAMS = [
    "hawks", "celtics", "nets", "hornets", "bulls", "cavaliers", "cavs", "mavericks", "mavs",
    "nuggets", "pistons", "warriors", "rockets", "pacers", "clippers", "lakers", "grizzlies",
    "heat", "bucks", "timberwolves", "pelicans", "knicks", "thunder", "magic", "76ers", "sixers",
    "suns", "trail blazers", "blazers", "kings", "spurs", "raptors", "jazz", "wizards",
    "supersonics", "sonics", "bobcats", "bullets",
]
NBA_WORDS = ["nba", "swingman", "basketball", "basketbal", "basket", "pallacanestro", "baloncesto"]

FOOTBALL_WORDS = [
    "football shirt", "soccer", "voetbal", "fussball", "fußball", "calcio", "futbol", "fútbol",
    "maillot", "trikot", "maglia", "camiseta", "matchworn", "match worn", "match-worn",
    "player issue", "player version", "home shirt", "away shirt", "third shirt", "home kit",
    "away kit", "champions league", "premier league", "serie a", "la liga", "bundesliga",
    "ligue 1", "eredivisie", "world cup", "euro 20",
]
FOOTBALL_CLUBS = [
    "manchester united", "man utd", "manchester city", "liverpool", "arsenal", "chelsea",
    "tottenham", "newcastle", "aston villa", "everton", "west ham", "leeds", "real madrid",
    "barcelona", "barça", "atletico", "atlético", "sevilla", "valencia", "bayern", "dortmund",
    "schalke", "leverkusen", "juventus", "ac milan", "inter", "napoli", "roma", "lazio",
    "fiorentina", "psg", "paris saint", "marseille", "lyon", "monaco", "ajax", "psv",
    "feyenoord", "benfica", "porto", "sporting", "celtic", "rangers", "galatasaray",
    "fenerbahce", "boca juniors", "river plate", "santos", "flamengo", "al nassr", "inter miami",
    "argentina", "brazil", "brasil", "germany", "deutschland", "france", "england", "italy",
    "italia", "spain", "españa", "portugal", "netherlands", "holland", "nederland", "belgium",
    "croatia",
]
JERSEY_WORDS = [
    "jersey", "shirt", "trikot", "maillot", "maglia", "camiseta", "tricot", "kit", "voetbalshirt",
    "shirtje", "camisa",
]
# Things that are not the jersey itself, or are another sport
EXCLUDE_WORDS = [
    "t-shirt", "tshirt", "tee ", "hoodie", "sweater", "jacket", "poster", "trading card",
    "photo only", "mini kit", "miniature", "keychain", "funko", "ball only", "shorts only",
    "nfl", "american football", "nhl", "mlb", "hockey", "baseball", "rugby", "cricket",
]

# Counterfeit / copy red flags (title or description)
FAKE_WORDS = [
    "replica", "réplica", "replika", "repro", "reproduction", "copy", "1:1", "aaa", "thai version",
    "thailand", "fan made", "inspired", "unofficial", "unbranded", "mirror quality", "top quality",
    "fake", "not original", "non original", "imitation", "custom made", "retro style",
    "custom jersey", "custom basketball jersey", "custom football shirt", "brand: custom",
]

SIGNED_WORDS = [
    "signed", "autograph", "autographed", "hand signed", "gesigneerd", "signiert", "signé",
    "signe", "firmada", "firmado", "autografata", "autografo", "signature",
]
COA_WORDS = [
    "coa", "certificate", "certificaat", "zertifikat", "certificat", "beckett", "bas ",
    "psa", "psa/dna", "jsa", "fanatics", "upper deck", "icons.com", "authentication",
    "authenticated", "hologram", "steiner", "panini authentic",
]

CONDITION_GOOD = [
    "bnwt", "new with tags", "with tags", "mit etikett", "met labels", "avec étiquette",
    "mint", "excellent", "very good", "like new", "as new", "nieuw", "neu", "neuf", "nuevo",
]
CONDITION_BAD = [
    "hole", "holes", "stain", "stained", "torn", "rip ", "ripped", "damaged", "damage",
    "faded", "cracked", "cracking", "peeling", "missing badge", "missing patch", "bobbling",
    "pilling", "defect", "vlek", "gat", "kapot", "fleck", "loch", "tache", "trou", "poor",
]


def _has(text: str, words) -> list[str]:
    hits = []
    for w in words:
        pattern = r"(?<![a-z0-9])" + re.escape(w.strip()) + r"(?![a-z0-9])"
        if re.search(pattern, text):
            hits.append(w.strip())
    return hits


def classify_sport(text: str) -> str | None:
    t = text.lower()
    if _has(t, EXCLUDE_WORDS):
        return None
    if not _has(t, JERSEY_WORDS):
        return None
    nba = len(_has(t, NBA_WORDS)) * 2 + len(_has(t, NBA_TEAMS))
    foot = len(_has(t, FOOTBALL_WORDS)) * 2 + len(_has(t, FOOTBALL_CLUBS))
    if nba == 0 and foot == 0:
        return None
    return "nba" if nba > foot else "football"


def fake_flags(text: str, replica_word_is_fake: bool = True) -> list[str]:
    """Counterfeit red-flag words found in the text.

    Note: in football, "replica" is also what clubs call the official fan version (genuine).
    With replica_word_is_fake=False the bare word "replica" is ignored.
    """
    t = text.lower()
    hits = _has(t, FAKE_WORDS)
    if not replica_word_is_fake:
        hits = [h for h in hits if h not in ("replica", "réplica", "replika")]
    return hits


def signed_info(text: str) -> tuple[bool, bool]:
    t = text.lower()
    # "not signed" / "unsigned" shouldn't count
    t_clean = re.sub(r"\b(un|not |non[- ]?)signed\b", "", t)
    signed = bool(_has(t_clean, SIGNED_WORDS))
    coa = bool(_has(t, COA_WORDS))
    return signed, coa


def condition_check(text: str) -> tuple[bool, list[str], list[str]]:
    """Returns (acceptable, bad_hits, good_hits)."""
    t = text.lower()
    bad = _has(t, CONDITION_BAD)
    good = _has(t, CONDITION_GOOD)
    return (not bad), bad, good
