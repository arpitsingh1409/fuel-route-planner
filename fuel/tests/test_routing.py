from unittest.mock import patch

import numpy as np
from django.core.cache import cache
from django.test import SimpleTestCase

from fuel.exceptions import NoRouteFound, UpstreamUnavailable
from fuel.services.geocoding import Location
from fuel.services.routing import decode_polyline, fetch_route

# The worked example from the polyline format's documentation.
ENCODED = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
DECODED = [[38.5, -120.2], [40.7, -120.95], [43.252, -126.453]]
A, B = Location("A", 38.5, -120.2), Location("B", 43.252, -126.453)
OSRM_BODY = {"code": "Ok", "routes": [{"distance": 160934.4, "duration": 7200, "geometry": ENCODED}]}


class RoutingTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_decode_polyline_reference_example(self):
        np.testing.assert_allclose(decode_polyline(ENCODED), DECODED)

    @patch("fuel.services.external.get_json", return_value=OSRM_BODY)
    def test_fetch_route_converts_units_and_measures_along_the_line(self, get_json):
        route, calls = fetch_route(A, B)

        self.assertEqual(calls, 1)
        self.assertAlmostEqual(route.distance_miles, 100.0)
        self.assertEqual(route.duration_hours, 2.0)
        np.testing.assert_allclose(route.points, DECODED)
        self.assertEqual(route.miles[0], 0.0)
        self.assertAlmostEqual(route.miles[-1], 100.0)  # scaled to the reported distance
        self.assertTrue(0 < route.miles[1] < 100)
        url, params = get_json.call_args.args
        self.assertTrue(url.endswith("/route/v1/driving/-120.2,38.5;-126.453,43.252"))  # lon,lat
        self.assertEqual(params, {"overview": "full", "geometries": "polyline"})

    @patch("fuel.services.external.get_json", return_value=OSRM_BODY)
    def test_a_repeat_is_served_from_the_cache(self, get_json):
        fetch_route(A, B)
        route, calls = fetch_route(A, B)

        self.assertEqual((calls, get_json.call_count), (0, 1))
        self.assertAlmostEqual(route.distance_miles, 100.0)

    @patch("fuel.services.external.get_json", return_value={"code": "NoRoute", "message": "Impossible route"})
    def test_no_route_is_a_422(self, _):
        with self.assertRaises(NoRouteFound) as raised:
            fetch_route(A, B)
        self.assertEqual(raised.exception.status_code, 422)

    @patch("fuel.services.external.get_json", side_effect=UpstreamUnavailable())
    def test_outage_is_a_503_and_is_not_cached(self, get_json):
        for _ in range(2):
            with self.assertRaises(UpstreamUnavailable) as raised:
                fetch_route(A, B)
        self.assertEqual((raised.exception.status_code, get_json.call_count), (503, 2))
