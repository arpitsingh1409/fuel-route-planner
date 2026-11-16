"""Plan a trip: geocode both ends, fetch the route, then choose where to fuel."""

import math
import time

from django.conf import settings

from fuel.services import geocoding, routing, stations
from fuel.services.optimizer import plan_fuel_stops

MAX_ROUTE_POINTS = 1500


def plan_trip(start: str, finish: str, start_fuel_gallons: float, stop_cost: float) -> dict:
    began = time.perf_counter()
    origin, start_calls = geocoding.resolve(start)
    destination, finish_calls = geocoding.resolve(finish)
    route, route_calls = routing.fetch_route(origin, destination)

    candidates = _candidates(route)
    mpg = settings.VEHICLE_MPG
    plan = plan_fuel_stops(
        [round(station["mile"]) for station in candidates],
        [station["price"] for station in candidates],
        round(route.distance_miles),
        tank_miles=settings.VEHICLE_RANGE_MILES,
        start_miles=round(start_fuel_gallons * mpg),
        mpg=mpg,
        stop_cost=stop_cost,
    )
    fuel_stops = [
        _stop(number, candidates[index], bought / mpg) for number, (index, bought) in enumerate(plan, 1)
    ]
    return {
        "start": _place(start, origin),
        "finish": _place(finish, destination),
        "distance_miles": round(route.distance_miles, 1),
        "duration_hours": round(route.duration_hours, 1),
        "vehicle": {"range_miles": settings.VEHICLE_RANGE_MILES, "mpg": mpg},
        "options": {"start_fuel_gallons": float(start_fuel_gallons), "stop_cost": float(stop_cost)},
        "fuel_stops": fuel_stops,
        "total_gallons": round(sum(bought for _, bought in plan) / mpg, 1),
        "total_fuel_cost": round(sum(stop["cost"] for stop in fuel_stops), 2),
        "route": {"type": "LineString", "coordinates": _thin(route.points)},
        "meta": {
            "external_api_calls": start_calls + finish_calls + route_calls,
            "elapsed_ms": int((time.perf_counter() - began) * 1000),
        },
    }


def _candidates(route: routing.Route) -> list[dict]:
    """Stations along the route, plus the one nearest its start so the trip can begin with a fill-up."""
    first = stations.nearest(*route.points[0])
    found = stations.along_route(route.points, route.miles, settings.MAX_DETOUR_MILES)
    return [first] + [station for station in found if station["opis_id"] != first["opis_id"]]


def _place(query: str, location: geocoding.Location) -> dict:
    return {"query": query, "name": location.name, "lat": location.lat, "lon": location.lon}


def _stop(number: int, station: dict, gallons: float) -> dict:
    return {
        "stop": number,
        "station_id": station["opis_id"],
        **{key: station[key] for key in ("name", "address", "city", "state", "lat", "lon", "located_by")},
        "mile_marker": round(station["mile"], 1),
        "miles_off_route": round(station["miles_off_route"], 1),
        "price_per_gallon": round(station["price"], 3),
        "gallons": round(gallons, 1),
        "cost": round(gallons * station["price"], 2),
    }


def _thin(points) -> list[list[float]]:
    """At most MAX_ROUTE_POINTS [lon, lat] pairs, taken at a fixed stride, ending at the finish."""
    # One fewer than the cap is spread by the stride, leaving room for the last point.
    stride = max(1, math.ceil((len(points) - 1) / (MAX_ROUTE_POINTS - 1)))
    kept = list(range(0, len(points), stride))
    if kept[-1] != len(points) - 1:
        kept.append(len(points) - 1)
    return [[float(points[i, 1]), float(points[i, 0])] for i in kept]
