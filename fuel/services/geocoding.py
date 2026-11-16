"""Turn a typed location into coordinates.

"City, ST" is answered from the bundled US places list with no outside call.
Anything else (a street address, a landmark) goes to Nominatim, restricted to the USA.
"""

import csv
import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache

from django.conf import settings

from fuel.exceptions import LocationNotFound
from fuel.services import external

STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "district of columbia": "DC",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA",
    "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}
STATE_CODES = set(STATES.values())
_COUNTRY = {"usa", "us", "united states", "united states of america"}
_ABBREVIATIONS = {"saint": "st", "fort": "ft", "mount": "mt"}


@dataclass(frozen=True)
class Location:
    name: str
    lat: float
    lon: float


def normalize_place(name: str) -> str:
    """One spelling per place: 'Saint Louis', 'St. Louis' and 'st louis' all match."""
    key = re.sub(r"[.']", "", name.lower())
    key = re.sub(r"\b(saint|fort|mount)\b", lambda m: _ABBREVIATIONS[m.group()], key)
    return " ".join(key.split())


def state_code(state: str) -> str | None:
    state = state.strip()
    if state.upper() in STATE_CODES:
        return state.upper()
    return STATES.get(" ".join(state.lower().split()))


@lru_cache(maxsize=1)
def _places() -> dict[tuple[str, str], tuple[float, float, str]]:
    places = {}
    with (settings.DATA_DIR / "us_places.csv").open(newline="") as f:
        for row in csv.DictReader(f):
            # The file lists the preferred row for a name first, so the first one wins.
            key = (normalize_place(row["name"]), row["state"])
            places.setdefault(key, (float(row["lat"]), float(row["lon"]), row["name"]))
    return places


def _lookup(city: str, state: str) -> Location | None:
    code = state_code(state)
    found = _places().get((normalize_place(city), code)) if code else None
    return Location(f"{found[2]}, {code}", found[0], found[1]) if found else None


def lookup_place(city: str, state: str) -> tuple[float, float] | None:
    location = _lookup(city, state)
    return (location.lat, location.lon) if location else None


def resolve(query: str) -> tuple[Location, int]:
    """Return the location and how many outside calls it took (0 or 1)."""
    parts = [part.strip() for part in query.split(",") if part.strip()]
    if len(parts) > 1 and parts[-1].lower().replace(".", "") in _COUNTRY:
        parts.pop()
    if len(parts) == 2 and (location := _lookup(*parts)):
        return location, 0

    text = " ".join(query.split())
    key = "geocode:" + hashlib.sha256(text.lower().encode()).hexdigest()
    params = {"q": text, "format": "jsonv2", "limit": 1, "countrycodes": "us"}
    results, calls = external.cached(
        key, lambda: external.get_json(f"{settings.NOMINATIM_URL}/search", params)
    )
    if not results:
        raise LocationNotFound(f'Could not find "{text}" in the USA. Try the form "City, ST".')
    top = results[0]
    return Location(top["display_name"], float(top["lat"]), float(top["lon"])), calls
