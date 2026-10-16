"""
location.py
-----------
Best-effort country/region normalization for scanned job locations.

The public job boards expose ``location`` as free text ("Remote", "Berlin,
Germany", "USA", "Colombo, Sri Lanka"), so country and region are inferred with
a small alias table. This is a display / filter aid for the dashboard -- it is
NOT part of the Risk Engine and never influences a risk verdict.

Design rules (mirroring ``taxonomy.py``):

- Best-effort only: an unrecognized location returns ``("", "")`` rather than a
  guess, so the API filter can fall back to a conservative substring match on
  the raw text (see ``models/storage.py``).
- ``REMOTE`` is used as both the country and the region value for
  Remote / Worldwide / Anywhere listings, so it can appear as a filter option.
- ``EU`` / ``Europe`` are kept as a region-only pseudo entry (country ==
  "Europe"), which is good enough for "avoid overseas roles" filtering.
- Deterministic and total: ``normalize_location`` never raises.
"""

from __future__ import annotations

import re
from typing import Any, Optional

REMOTE = "Remote"

# --- alias table -----------------------------------------------------------
# ordered ``(canonical country, region, aliases)``. Aliases are already in the
# normalized form produced by ``_norm`` (lowercase, punctuation -> space).
_COUNTRIES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    # North America ---------------------------------------------------------
    ("United States", "North America",
     ("us", "u s", "usa", "u s a", "united states", "united states of america",
      "america")),
    ("Canada", "North America", ("ca", "can", "canada")),
    ("Mexico", "North America", ("mx", "mex", "mexico")),
    # Europe ----------------------------------------------------------------
    ("United Kingdom", "Europe",
     ("uk", "u k", "gb", "great britain", "britain", "england", "scotland",
      "wales", "northern ireland", "united kingdom")),
    ("Ireland", "Europe", ("ie", "ireland", "republic of ireland")),
    ("Germany", "Europe", ("de", "ger", "germany", "deutschland")),
    ("France", "Europe", ("fr", "fra", "france")),
    ("Netherlands", "Europe",
     ("nl", "ned", "netherlands", "holland", "the netherlands")),
    ("Spain", "Europe", ("es", "esp", "spain", "espana")),
    ("Italy", "Europe", ("it", "ita", "italy", "italia")),
    ("Portugal", "Europe", ("pt", "prt", "portugal")),
    ("Poland", "Europe", ("pl", "pol", "poland")),
    ("Sweden", "Europe", ("se", "swe", "sweden")),
    ("Norway", "Europe", ("no", "nor", "norway")),
    ("Denmark", "Europe", ("dk", "dnk", "denmark")),
    ("Finland", "Europe", ("fi", "fin", "finland")),
    ("Iceland", "Europe", ("is", "isl", "iceland")),
    ("Switzerland", "Europe", ("ch", "che", "switzerland")),
    ("Austria", "Europe", ("at", "aut", "austria")),
    ("Belgium", "Europe", ("be", "bel", "belgium")),
    ("Luxembourg", "Europe", ("lu", "lux", "luxembourg")),
    ("Romania", "Europe", ("ro", "rou", "romania")),
    ("Ukraine", "Europe", ("ua", "ukr", "ukraine")),
    ("Czechia", "Europe", ("cz", "czechia", "czech republic")),
    ("Greece", "Europe", ("gr", "grc", "greece")),
    ("Hungary", "Europe", ("hu", "hun", "hungary")),
    ("Bulgaria", "Europe", ("bg", "bgr", "bulgaria")),
    ("Croatia", "Europe", ("hr", "hrv", "croatia")),
    ("Serbia", "Europe", ("rs", "srb", "serbia")),
    ("Slovakia", "Europe", ("sk", "svk", "slovakia")),
    ("Slovenia", "Europe", ("si", "svn", "slovenia")),
    ("Lithuania", "Europe", ("lt", "ltu", "lithuania")),
    ("Latvia", "Europe", ("lv", "lva", "latvia")),
    ("Estonia", "Europe", ("ee", "est", "estonia")),
    # region-only pseudo entry (EU / Europe as a whole) ----------------------
    ("Europe", "Europe", ("eu", "europe", "european union")),
    # Asia ------------------------------------------------------------------
    ("India", "Asia", ("in", "ind", "india")),
    ("China", "Asia", ("cn", "chn", "china")),
    ("Japan", "Asia", ("jp", "jpn", "japan")),
    ("South Korea", "Asia", ("kr", "kor", "south korea", "korea")),
    ("Singapore", "Asia", ("sg", "sgp", "singapore")),
    ("Malaysia", "Asia", ("my", "mys", "malaysia")),
    ("Philippines", "Asia", ("ph", "phl", "philippines")),
    ("Indonesia", "Asia", ("id", "idn", "indonesia")),
    ("Vietnam", "Asia", ("vn", "vnm", "vietnam", "viet nam")),
    ("Thailand", "Asia", ("th", "tha", "thailand")),
    ("Bangladesh", "Asia", ("bd", "bgd", "bangladesh")),
    ("Pakistan", "Asia", ("pk", "pak", "pakistan")),
    ("Sri Lanka", "Asia", ("lk", "lka", "sri lanka", "ceylon")),
    ("Nepal", "Asia", ("np", "npl", "nepal")),
    ("Taiwan", "Asia", ("tw", "twn", "taiwan")),
    ("Hong Kong", "Asia", ("hk", "hkg", "hong kong")),
    ("Cambodia", "Asia", ("kh", "khm", "cambodia")),
    ("Myanmar", "Asia", ("mm", "mmr", "myanmar", "burma")),
    # Middle East -----------------------------------------------------------
    ("United Arab Emirates", "Middle East",
     ("ae", "are", "uae", "u a e", "united arab emirates", "dubai",
      "abu dhabi")),
    ("Saudi Arabia", "Middle East", ("sa", "sau", "saudi arabia", "ksa")),
    ("Qatar", "Middle East", ("qa", "qat", "qatar")),
    ("Kuwait", "Middle East", ("kw", "kwt", "kuwait")),
    ("Israel", "Middle East", ("il", "isr", "israel")),
    ("Turkey", "Middle East", ("tr", "tur", "turkey", "turkiye")),
    ("Bahrain", "Middle East", ("bh", "bhr", "bahrain")),
    ("Oman", "Middle East", ("om", "omn", "oman")),
    ("Jordan", "Middle East", ("jo", "jor", "jordan")),
    ("Lebanon", "Middle East", ("lb", "lbn", "lebanon")),
    # Africa ----------------------------------------------------------------
    ("South Africa", "Africa", ("za", "zaf", "south africa")),
    ("Nigeria", "Africa", ("ng", "nga", "nigeria")),
    ("Kenya", "Africa", ("ke", "ken", "kenya")),
    ("Egypt", "Africa", ("eg", "egy", "egypt")),
    ("Ghana", "Africa", ("gh", "gha", "ghana")),
    ("Morocco", "Africa", ("ma", "mar", "morocco")),
    ("Tanzania", "Africa", ("tz", "tza", "tanzania")),
    ("Uganda", "Africa", ("ug", "uga", "uganda")),
    ("Ethiopia", "Africa", ("et", "eth", "ethiopia")),
    ("Algeria", "Africa", ("dz", "dza", "algeria")),
    ("Tunisia", "Africa", ("tn", "tun", "tunisia")),
    ("Rwanda", "Africa", ("rw", "rwa", "rwanda")),
    # South America ---------------------------------------------------------
    ("Brazil", "South America", ("br", "bra", "brazil", "brasil")),
    ("Argentina", "South America", ("ar", "arg", "argentina")),
    ("Colombia", "South America", ("co", "col", "colombia")),
    ("Chile", "South America", ("cl", "chl", "chile")),
    ("Peru", "South America", ("pe", "per", "peru")),
    ("Uruguay", "South America", ("uy", "ury", "uruguay")),
    ("Ecuador", "South America", ("ec", "ecu", "ecuador")),
    # Oceania ---------------------------------------------------------------
    ("Australia", "Oceania", ("au", "aus", "australia")),
    ("New Zealand", "Oceania", ("nz", "nzl", "new zealand")),
)

_COUNTRY_REGION: dict[str, str] = {c: region for c, region, _ in _COUNTRIES}
_ALIAS_TO_COUNTRY: dict[str, str] = {}

# Aliases long enough to match as a word-boundary phrase inside a longer string
# (2-letter ISO codes are intentionally excluded to avoid false positives).
_PHRASE_ALIASES: list[tuple[str, str]] = []


def _norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


for _country, _region, _aliases in _COUNTRIES:
    _ALIAS_TO_COUNTRY[_norm(_country)] = _country
    for _alias in _aliases:
        _ALIAS_TO_COUNTRY[_norm(_alias)] = _country
        if len(_alias) >= 4 and " " not in _alias:
            _PHRASE_ALIASES.append((_norm(_alias), _country))
_PHRASE_ALIASES.sort(key=lambda pair: -len(pair[0]))

# Region-only tokens accepted by the ``region`` filter.
_REGIONS = ("Africa", "Asia", "Europe", "Middle East", "North America",
            "Oceania", "South America", REMOTE)
_REGION_ALIASES: dict[str, str] = {_norm(r): r for r in _REGIONS}
_REGION_ALIASES.update({
    "eu": "Europe", "european union": "Europe",
    "worldwide": REMOTE, "world wide": REMOTE, "anywhere": REMOTE,
    "global": REMOTE, "remote": REMOTE,
})

# Whole-word tokens that mean "this location is remote".
_REMOTE_TOKENS = ("remote", "worldwide", "world wide", "anywhere", "global",
                  "telecommute", "work from home", "wfh")
_REMOTE_EXACT = {
    "remote", "remote only", "fully remote", "100 remote", "remote work",
    "worldwide", "world wide", "anywhere", "anywhere in the world",
    "work from anywhere", "global", "any location", "telecommute",
    "work from home", "wfh", "remote worldwide",
}


def _has_phrase(text: str, phrase: str) -> bool:
    return (" " + phrase + " ") in (" " + text + " ")


def _is_remote(text: str) -> bool:
    """True when a normalized location string means Remote/Worldwide."""
    if text in _REMOTE_EXACT:
        return True
    return any(_has_phrase(text, token) for token in _REMOTE_TOKENS)


def normalize_location(location: Any) -> tuple[str, str]:
    """Best-effort ``(country, region)`` for a free-text location.

    Returns ``("", "")`` when nothing reliable can be inferred. Never raises.
    """
    raw = str(location or "")
    text = _norm(raw)
    if not text:
        return "", ""

    if _is_remote(text):
        return REMOTE, REMOTE

    # 1. the whole string is a known country/alias.
    country = _ALIAS_TO_COUNTRY.get(text)
    if country:
        return country, _COUNTRY_REGION[country]

    # 2. "City, Country" / "City, State, Country": check segments right-to-left.
    segments = [seg.strip() for seg in raw.split(",") if seg.strip()]
    for segment in reversed(segments):
        seg = _norm(segment)
        if not seg:
            continue
        if _is_remote(seg):
            return REMOTE, REMOTE
        country = _ALIAS_TO_COUNTRY.get(seg)
        if country:
            return country, _COUNTRY_REGION[country]

    # 3. a known country name appearing as a whole-word phrase in the text.
    for alias, country in _PHRASE_ALIASES:
        if _has_phrase(text, alias):
            return country, _COUNTRY_REGION[country]

    return "", ""


def canonical_country(value: Any) -> str:
    """Map a user-supplied country filter value to its canonical form.

    Returns "" for unknown values so callers can fall back to a substring match.
    """
    text = _norm(value)
    if not text:
        return ""
    if _is_remote(text):
        return REMOTE
    return _ALIAS_TO_COUNTRY.get(text, "")


def canonical_region(value: Any) -> str:
    """Map a user-supplied region filter value to its canonical form (or "")."""
    text = _norm(value)
    if not text:
        return ""
    return _REGION_ALIASES.get(text, "")


def region_for_country(country: Any) -> Optional[str]:
    """Region for a canonical country name (None when unknown)."""
    return _COUNTRY_REGION.get(str(country or "").strip())
