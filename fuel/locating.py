"""Pure functions that turn the supplied price list into located stations.

The price list has no coordinates. Most addresses are highway descriptions such as
"I-44, EXIT 283 & US-69", so a station is placed at the OpenStreetMap exit with that
number near its town, and at the town centre when the address has no exit number.
"""

import re
from collections import defaultdict
from collections.abc import Iterable

from fuel.services.geo import haversine_miles
from fuel.services.geocoding import STATE_CODES, normalize_place

Point = tuple[float, float]
Candidate = tuple[float, int, Point]  # (miles from town, OSM node id, point)

_EXIT = re.compile(r"EXITS?[\s-]*(\d+)[\s-]?([A-Z])?\b")
_REF_SEPARATORS = re.compile(r"[;,/]")
_NOT_ALPHANUMERIC = re.compile(r"[^0-9A-Z]")
# Interstates and US routes only: state routes are tagged too inconsistently in OSM to compare.
_HIGHWAY = re.compile(r"\b(I|US)[\s-]*(\d+[A-Z]?)\b")


def _tidy(text: str) -> str:
    return " ".join(text.split())


def clean_stations(rows: Iterable[dict]) -> list[dict]:
    """One station per OPIS id at its lowest listed price, US only, ordered by id."""
    best: dict[int, dict] = {}
    for row in rows:
        state = row["State"].strip().upper()
        if state not in STATE_CODES:  # the file also lists Canadian provinces
            continue
        opis_id, price = int(row["OPIS Truckstop ID"]), float(row["Retail Price"])
        if opis_id not in best or price < best[opis_id]["price"]:
            best[opis_id] = {
                "opis_id": opis_id,
                "name": _tidy(row["Truckstop Name"]),
                "address": _tidy(row["Address"]),
                "city": _tidy(row["City"]),
                "state": state,
                "price": price,
            }
    return [best[opis_id] for opis_id in sorted(best)]


def parse_exit(address: str) -> str | None:
    """'I-75, EXIT 144-B' -> '144B'. None when the address names no exit."""
    match = _EXIT.search(address.upper())
    return match.group(1) + (match.group(2) or "") if match else None


def index_exits(osm_nodes: Iterable[dict]) -> dict[str, list[tuple[int, Point]]]:
    """Group OpenStreetMap motorway junctions by exit number. 'ref' can list several, e.g. '12;12A'."""
    exits: dict[str, list[tuple[int, Point]]] = defaultdict(list)
    for node in osm_nodes:
        for ref in _split_refs(node["tags"]["ref"]):
            exits[ref].append((node["id"], (node["lat"], node["lon"])))
    return dict(exits)


def _split_refs(ref: str) -> list[str]:
    """'I 44;US 412' -> ['I44', 'US412']."""
    refs = (_NOT_ALPHANUMERIC.sub("", part) for part in _REF_SEPARATORS.split(ref.upper()))
    return [r for r in refs if r]


def exit_candidates(
    exit_ref: str, town: Point, exits: dict[str, list[tuple[int, Point]]], max_miles: float = 25
) -> list[Candidate]:
    """Exits with this number near the town, nearest first."""
    number = re.match(r"\d+", exit_ref).group()
    for ref in dict.fromkeys([exit_ref, number]):  # exact first, then without the letter
        near = sorted(
            (float(haversine_miles(*town, *point)), node_id, point)
            for node_id, point in exits.get(ref, [])
        )
        near = [candidate for candidate in near if candidate[0] <= max_miles]
        if near:
            return near
    return []


def pick_exit(
    exit_ref: str, town: Point, exits: dict[str, list[tuple[int, Point]]], max_miles: float = 25
) -> Point | None:
    candidates = exit_candidates(exit_ref, town, exits, max_miles)
    return candidates[0][2] if candidates else None


def is_ambiguous(candidates: list[Candidate]) -> bool:
    """Another exit with the same number lies over 2 miles from the nearest one."""
    return any(haversine_miles(*candidates[0][2], *other[2]) > 2 for other in candidates[1:])


def address_highways(address: str) -> set[str]:
    """'I-80/I-94, EXIT 5' -> {'I80', 'I94'}: the highways named before the exit."""
    before_exit = re.split(r"EXIT", address.upper())[0]
    return {kind + number for kind, number in _HIGHWAY.findall(before_exit)}


def highways_by_node(ways: Iterable[dict], node_ids: set[int]) -> dict[int, set[str]]:
    """Highway refs of the OSM ways passing through each of the given nodes."""
    found: dict[int, set[str]] = defaultdict(set)
    for way in ways:
        refs = _split_refs(way.get("tags", {}).get("ref", ""))
        for node_id in node_ids.intersection(way["nodes"]):
            found[node_id].update(refs)
    return {node_id: refs for node_id, refs in found.items() if refs}


def choose_exit(
    candidates: list[Candidate], highways: set[str], node_highways: dict[int, set[str]]
) -> tuple[Point, bool]:
    """The nearest candidate on a named highway, else the nearest. The flag says the highway matched."""
    on_highway = [c for c in candidates if node_highways.get(c[1], set()) & highways]
    return (on_highway or candidates)[0][2], bool(on_highway)


def squash_place(name: str) -> str:
    """Town key that ignores spaces, so the postal 'Mc Lean' matches 'McLean'."""
    return normalize_place(name).replace(" ", "")


# County is the coarsest kept: some unincorporated towns, e.g. Saint Johns FL, only match their county.
_PLACE_TYPES = {"city", "town", "village", "hamlet", "municipality", "county"}


def first_place(results: list[dict], state: str) -> Point | None:
    """First Nominatim result that is a place in the state (needs addressdetails=1).

    Free text also matches shops and parks named after the town, and towns in other states.
    """
    for result in results:
        in_state = result.get("address", {}).get("ISO3166-2-lvl4") == f"US-{state}"
        if in_state and result.get("addresstype") in _PLACE_TYPES:
            return float(result["lat"]), float(result["lon"])
    return None
