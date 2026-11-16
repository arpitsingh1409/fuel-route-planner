from unittest.mock import patch

import numpy as np
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from fuel.exceptions import UpstreamUnavailable
from fuel.models import FuelStation
from fuel.services import routing, stations
from fuel.services.geocoding import Location

S, F = "New York, NY", "Los Angeles, CA"


def encode_polyline(points) -> str:
    """Google's encoded polyline format (precision 5); the inverse of routing.decode_polyline."""
    chars, previous = [], [0, 0]
    for point in points:
        for axis in (0, 1):
            value = round(point[axis] * 1e5)
            delta, previous[axis] = value - previous[axis], value
            delta = ~(delta << 1) if delta < 0 else delta << 1
            while delta >= 0x20:
                chars.append(chr((0x20 | (delta & 0x1F)) + 63))
                delta >>= 5
            chars.append(chr(delta + 63))
    return "".join(chars)


def osrm_body(points, miles):
    geometry = encode_polyline(points)
    return {"code": "Ok", "routes": [{"distance": miles * 1609.344, "duration": 36000, "geometry": geometry}]}


# A straight west-to-east line along latitude 40, scaled by OSRM's distance to exactly 700 miles.
LINE = osrm_body([(40.0, lon) for lon in np.arange(-100.0, -86.795, 0.01)], 700)
POINT = osrm_body([(40.0, -100.0)], 0)


class RouteApiTests(TestCase):
    def setUp(self):
        cache.clear()
        stations.clear_cache()
        self.url = reverse("route")
        with patch("fuel.services.external.get_json", return_value=LINE):
            route, _ = routing.fetch_route(Location("A", 0, 0), Location("B", 0, 0))
        cache.clear()
        for opis_id, (mile, price) in enumerate([(0, 3.50), (100, 3.40), (200, 3.00), (600, 4.00)], 1):
            FuelStation.objects.create(
                opis_id=opis_id, name=f"Stop {mile}", address="I-80, EXIT 1", city="Town", state="NE",
                price=price, lat=np.interp(mile, route.miles, route.points[:, 0]),
                lon=np.interp(mile, route.miles, route.points[:, 1]), located_by="exit",
            )
        patcher = patch("fuel.services.external.get_json", return_value=LINE)
        self.get_json = patcher.start()
        self.addCleanup(patcher.stop)

    def test_plans_the_cheapest_stops(self):
        r = self.client.get(self.url, {"start": S, "finish": F})
        body = r.json()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            [(s["mile_marker"], s["gallons"]) for s in body["fuel_stops"]], [(0.0, 10.0), (100.0, 10.0), (200.0, 50.0)]
        )
        self.assertEqual(body["total_gallons"], 70.0)
        self.assertEqual(body["total_fuel_cost"], 219.0)  # 10 x 3.50 + 10 x 3.40 + 50 x 3.00
        self.assertEqual(body["options"], {"start_fuel_gallons": 0.0, "stop_cost": 0.0})
        self.assertEqual(body["meta"]["external_api_calls"], 1)
        self.assertEqual(body["route"]["type"], "LineString")

    def test_repeat_request_makes_no_outside_call(self):
        self.client.get(self.url, {"start": S, "finish": F})
        self.assertEqual(self.client.get(self.url, {"start": S, "finish": F}).json()["meta"]["external_api_calls"], 0)

    def test_stop_cost_trades_money_for_fewer_stops(self):
        body = self.client.get(self.url, {"start": S, "finish": F, "stop_cost": 5}).json()
        self.assertEqual([(s["mile_marker"], s["gallons"]) for s in body["fuel_stops"]], [(0.0, 20.0), (200.0, 50.0)])
        self.assertEqual(body["total_fuel_cost"], 220.0)  # fuel money only: 20 x 3.50 + 50 x 3.00

    def test_full_tank_start_buys_less(self):
        body = self.client.get(self.url, {"start": S, "finish": F, "start_fuel_gallons": 50}).json()
        self.assertEqual(body["total_gallons"], 20.0)

    def test_same_start_and_finish(self):
        self.get_json.return_value = POINT
        body = self.client.get(self.url, {"start": S, "finish": S}).json()
        self.assertEqual((body["fuel_stops"], body["total_fuel_cost"]), ([], 0))

    def test_bad_input_is_a_400(self):
        for params in [
            {}, {"start": S}, {"start": S, "finish": F, "start_fuel_gallons": -1},
            {"start": S, "finish": F, "start_fuel_gallons": 51}, {"start": S, "finish": F, "start_fuel_gallons": "x"},
            {"start": S, "finish": F, "stop_cost": -1}, {"start": S, "finish": F, "stop_cost": 101},
            {"start": "x" * 201, "finish": F},
        ]:
            with self.subTest(params=params):
                self.assertEqual(self.client.get(self.url, params).status_code, 400)

    def test_routing_outage_is_a_503(self):
        self.get_json.side_effect = UpstreamUnavailable()
        self.assertEqual(self.client.get(self.url, {"start": S, "finish": F}).status_code, 503)
