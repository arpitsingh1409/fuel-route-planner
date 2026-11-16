"""Locate every station in data/fuel-prices.csv and write data/stations.csv.

One-off data preparation: its output is committed, so the API never needs it at
run time. Downloads are cached under data/raw/, which is not committed.

Sources: OpenStreetMap via the Overpass API (highway exits) and Nominatim (the few
towns missing from the bundled places list). (c) OpenStreetMap contributors, ODbL.
"""

import csv
import json
import time
from collections import Counter

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from fuel.locating import (
    address_highways, choose_exit, clean_stations, exit_candidates, highways_by_node, index_exits,
    first_place, parse_exit, squash_place,
)
from fuel.services.geocoding import _places, lookup_place

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
EXITS_QUERY = '[out:json][timeout:180];node["highway"="motorway_junction"]["ref"]({box});out body;'
# The motorway and trunk ways through given exit nodes: junction nodes carry no highway number.
WAYS_QUERY = (
    '[out:json][timeout:180];node(id:{ids});'
    'way(bn)["highway"~"^(motorway|trunk)(_link)?$"];out body;'
)
# The lower 48 states, in six longitude strips so each query stays small.
SOUTH, NORTH = 24.3, 49.5
STRIPS = [-125.0, -115.3, -105.6, -95.9, -86.2, -76.5, -66.8]
HEADERS = {"User-Agent": "fuel-route-planner/1.0"}
FIELDS = ["opis_id", "name", "address", "city", "state", "price", "lat", "lon", "located_by"]


class Command(BaseCommand):
    help = __doc__

    def handle(self, *args, **options):
        raw = settings.DATA_DIR / "raw"
        with (settings.DATA_DIR / "fuel-prices.csv").open(newline="") as f:
            stations = clean_stations(csv.DictReader(f))
        exits = index_exits(self.overpass(raw / "osm", "exits", EXITS_QUERY))
        towns = self.towns(raw / "towns.json", {(s["city"], s["state"]) for s in stations})

        counts, matched = Counter(), []
        for station in stations:
            town = towns.get(f"{station['city']}|{station['state']}")
            if not town:
                counts["dropped: town not found"] += 1
                continue
            exit_ref = parse_exit(station["address"])
            candidates = exit_candidates(exit_ref, town, exits) if exit_ref else []
            if exit_ref and not candidates:
                counts["exit number in address but no matching exit"] += 1
            matched.append((station, town, candidates))

        # Exit numbers repeat across highways, so ask OSM which highway each candidate is on.
        node_ids = {node_id for _, _, candidates in matched for _, node_id, _ in candidates}
        node_highways = self.highways(raw / "osm" / "exit_ways.json", node_ids)

        located = []
        for station, town, candidates in matched:
            point, located_by = town, "town"
            if candidates:
                found, outcome = choose_exit(candidates, address_highways(station["address"]), node_highways)
                if found:
                    point, located_by = found, "exit"
                    counts[f"located by exit, highway {outcome}"] += 1
                else:
                    counts[f"exit rejected, town used: {outcome}"] += 1
            counts[f"located by {located_by}"] += 1
            located.append(
                {**station, "lat": round(point[0], 6), "lon": round(point[1], 6), "located_by": located_by}
            )

        with (settings.DATA_DIR / "stations.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, FIELDS)
            writer.writeheader()
            writer.writerows(located)
        self.stdout.write(f"{len(located)} stations written")
        for label, count in sorted(counts.items()):
            self.stdout.write(f"{count:6d}  {label}")

    def overpass(self, folder, name, query):
        """Run an Overpass query over each strip, keeping every response on disk."""
        folder.mkdir(parents=True, exist_ok=True)
        elements = []
        for i, (west, east) in enumerate(zip(STRIPS, STRIPS[1:])):
            path = folder / f"{name}_{i}.json"
            if not path.exists():
                data = {"data": query.format(box=f"{SOUTH},{west},{NORTH},{east}")}
                path.write_text(self.post_with_retry(data))
                time.sleep(5)
            elements += json.loads(path.read_text())["elements"]
        return elements

    def highways(self, cache_path, node_ids):
        """Highway refs per exit node, querying Overpass only for the nodes not yet cached."""
        cache = json.loads(cache_path.read_text()) if cache_path.exists() else {"node_ids": [], "elements": []}
        missing = sorted(node_ids - set(cache["node_ids"]))
        for start in range(0, len(missing), 1000):  # batches keep each query small
            batch = missing[start:start + 1000]
            response = self.post_with_retry({"data": WAYS_QUERY.format(ids=",".join(map(str, batch)))})
            cache = {
                "node_ids": sorted(set(cache["node_ids"]) | set(batch)),
                "elements": cache["elements"] + json.loads(response)["elements"],
            }
            cache_path.write_text(json.dumps(cache))  # after every batch, so a stopped run resumes
            time.sleep(5)
        return highways_by_node(cache["elements"], node_ids)

    def post_with_retry(self, data):
        for attempt in range(1, 9):
            for url in OVERPASS_URLS:
                try:
                    response = requests.post(url, data=data, headers=HEADERS, timeout=400)
                    body = json.loads(response.text) if response.ok else {}
                    # Overpass answers 200 with a "remark" when it ran out of time or memory mid-query.
                    if "elements" in body and "remark" not in body:
                        return response.text
                except (requests.RequestException, ValueError):
                    pass
                self.stdout.write(f"Overpass busy, retrying ({attempt})")
                time.sleep(15 * attempt)
        raise SystemExit("Overpass did not answer; run the command again later.")

    def towns(self, cache_path, wanted):
        """Town centre per (city, state): the bundled list first, Nominatim for the rest.

        In the cache, null means only the structured Nominatim query was tried and
        false means every lookup failed.
        """
        cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
        squashed = {}
        for (name, state), (lat, lon, _) in _places().items():  # the preferred row comes first
            squashed.setdefault((squash_place(name), state), (lat, lon))
        for city, state in sorted(wanted):
            key = f"{city}|{state}"
            if cache.get(key) is not None:
                continue
            tried_structured = key in cache
            cache[key] = lookup_place(city, state) or squashed.get((squash_place(city), state))
            if cache[key] is None:
                if not tried_structured and (found := self.nominatim({"city": city, "state": state, "limit": 1})):
                    cache[key] = (float(found[0]["lat"]), float(found[0]["lon"]))
                if cache[key] is None:  # a last try for names the places list spells differently
                    cache[key] = first_place(
                        self.nominatim({"q": f"{city}, {state}", "limit": 5, "addressdetails": 1}), state
                    )
                if cache[key] is None:
                    cache[key] = False
                    self.stdout.write(f"Town not found: {key}")
                cache_path.write_text(json.dumps(cache, indent=0, sort_keys=True))
        cache_path.write_text(json.dumps(cache, indent=0, sort_keys=True))
        return cache

    def nominatim(self, params):
        for attempt in range(1, 6):
            time.sleep(1.5 * attempt)  # the public server allows one request per second
            response = requests.get(
                f"{settings.NOMINATIM_URL}/search",
                params=params | {"countrycodes": "us", "format": "jsonv2"},
                headers=HEADERS,
                timeout=30,
            )
            if response.ok and "json" in response.headers.get("content-type", ""):
                return response.json()
            self.stdout.write(f"Nominatim busy ({response.status_code}), retrying")
        raise SystemExit("Nominatim did not answer; run the command again to resume.")
