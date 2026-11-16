"""Find the stations along a route.

The station table is small and static, so it is held in memory as points on the unit
sphere. Distances to a route then come from one matrix product, which measured faster
at this size than a hexagonal (H3) index or a k-d tree.
"""

from functools import lru_cache

import numpy as np

from fuel.exceptions import NoFeasiblePlan
from fuel.models import FuelStation
from fuel.services.geo import EARTH_RADIUS_MILES, unit_vectors

FIELDS = ["opis_id", "name", "address", "city", "state", "price", "lat", "lon", "located_by"]
FINE_MILES = 1  # spacing of the route samples a station is measured against
COARSE_EVERY = 10  # the first pass uses every tenth sample


@lru_cache(maxsize=1)
def _index() -> tuple[list[dict], np.ndarray]:
    rows = list(FuelStation.objects.values(*FIELDS))
    lat, lon = (np.array([row[axis] for row in rows], dtype=float) for axis in ("lat", "lon"))
    return rows, unit_vectors(lat, lon)


def clear_cache() -> None:
    _index.cache_clear()


def along_route(points: np.ndarray, miles: np.ndarray, max_offset: float) -> list[dict]:
    """Stations within max_offset miles of the route, in the order they are passed.

    points: (N, 2) latitude and longitude along the route; miles: miles driven at each.
    Each result is the station's fields plus 'mile' and 'miles_off_route'.
    """
    rows, vectors = _index()
    if not rows:
        return []
    # Sample the line at even spacing so sparse vertices on straight roads cannot hide a station.
    sample_miles = np.append(np.arange(0, miles[-1], FINE_MILES), miles[-1])
    samples = unit_vectors(
        np.interp(sample_miles, miles, points[:, 0]), np.interp(sample_miles, miles, points[:, 1])
    )
    # Two passes keep the matrices small: a coarse one over every station discards most
    # of them, then a fine one measures the survivors.
    _, offset = _nearest_sample(vectors, samples[::COARSE_EVERY])
    near = np.flatnonzero(offset <= max_offset + FINE_MILES * COARSE_EVERY)
    sample, offset = _nearest_sample(vectors[near], samples)
    keep = offset <= max_offset
    found = [
        {**rows[i], "mile": float(sample_miles[s]), "miles_off_route": float(d)}
        for i, s, d in zip(near[keep], sample[keep], offset[keep])
    ]
    return sorted(found, key=lambda station: station["mile"])


def nearest(lat: float, lon: float) -> dict:
    """The station closest to a point, however far, shaped like an along_route result at mile 0."""
    rows, vectors = _index()
    if not rows:
        raise NoFeasiblePlan("No fuel stations are loaded. Run `python manage.py load_stations`.")
    index, offset = _nearest_sample(unit_vectors(lat, lon)[None, :], vectors)
    return {**rows[index[0]], "mile": 0.0, "miles_off_route": float(offset[0])}


def _nearest_sample(vectors: np.ndarray, samples: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """For each vector, the index of its nearest sample and the distance to it in miles."""
    cosines = vectors @ samples.T
    index = cosines.argmax(axis=1)
    angle = np.arccos(np.clip(cosines[np.arange(len(index)), index], -1.0, 1.0))
    return index, EARTH_RADIUS_MILES * angle
