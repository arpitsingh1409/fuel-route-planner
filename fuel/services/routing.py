"""Driving routes from OSRM: one call per start/finish pair, cached afterwards."""

from dataclasses import dataclass

import numpy as np
from django.conf import settings

from fuel.exceptions import NoRouteFound
from fuel.services import external
from fuel.services.geo import haversine_miles
from fuel.services.geocoding import Location

METERS_PER_MILE = 1609.344


@dataclass(frozen=True)
class Route:
    distance_miles: float
    duration_hours: float
    points: np.ndarray  # (N, 2) latitude, longitude
    miles: np.ndarray  # (N,) miles driven on reaching each point


def fetch_route(start: Location, finish: Location) -> tuple[Route, int]:
    """Return the route and how many outside calls it took (0 when cached)."""
    key = f"route:{start.lat:.4f},{start.lon:.4f};{finish.lat:.4f},{finish.lon:.4f}"
    return external.cached(key, lambda: _request(start, finish))


def _request(start: Location, finish: Location) -> Route:
    url = f"{settings.OSRM_URL}/route/v1/driving/{start.lon},{start.lat};{finish.lon},{finish.lat}"
    # The encoded polyline is about a third the size of GeoJSON for the same line.
    body = external.get_json(url, {"overview": "full", "geometries": "polyline"})
    if body.get("code") != "Ok" or not body.get("routes"):
        raise NoRouteFound()
    found = body["routes"][0]
    points = decode_polyline(found["geometry"])
    distance = found["distance"] / METERS_PER_MILE

    steps = haversine_miles(points[:-1, 0], points[:-1, 1], points[1:, 0], points[1:, 1])
    miles = np.concatenate([[0.0], np.cumsum(steps)])
    if miles[-1] > 0:
        miles *= distance / miles[-1]  # agree exactly with the distance OSRM reports
    return Route(distance, found["duration"] / 3600, points, miles)


def decode_polyline(encoded: str) -> np.ndarray:
    """Decode Google's encoded polyline format (precision 5) into (N, 2) lat/lon degrees."""
    deltas, value, shift = [], 0, 0
    for char in encoded:
        chunk = ord(char) - 63
        value |= (chunk & 0x1F) << shift
        shift += 5
        if chunk < 0x20:  # last chunk of this number
            deltas.append(~(value >> 1) if value & 1 else value >> 1)
            value = shift = 0
    return np.cumsum(np.array(deltas, dtype=np.int64).reshape(-1, 2), axis=0) / 1e5
