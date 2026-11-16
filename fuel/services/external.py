"""The only place that talks to outside services, so calls are easy to count and cache."""

from collections.abc import Callable

import requests
from django.conf import settings
from django.core.cache import cache

from fuel.exceptions import UpstreamUnavailable

TIMEOUT_SECONDS = 15

# One session keeps the connection open, which saves a TLS handshake on later calls.
_session = requests.Session()
_session.headers["User-Agent"] = "fuel-route-planner/1.0"


def get_json(url: str, params: dict | None = None):
    """GET a JSON body. A 4xx body is returned as-is because OSRM reports 'no route' that way."""
    try:
        response = _session.get(url, params=params, timeout=TIMEOUT_SECONDS)
        if response.status_code == 429 or response.status_code >= 500:
            raise UpstreamUnavailable()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        raise UpstreamUnavailable() from exc


def cached[T](key: str, fetch: Callable[[], T]) -> tuple[T, int]:
    """Return (value, outside calls made): 1 when fetched, 0 when served from the cache."""
    value = cache.get(key)
    if value is not None:
        return value, 0
    value = fetch()
    cache.set(key, value, settings.EXTERNAL_CACHE_SECONDS)
    return value, 1
