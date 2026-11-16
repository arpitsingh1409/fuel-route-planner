from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from fuel.exceptions import LocationNotFound
from fuel.services.geocoding import lookup_place, resolve


class ResolveTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_local_lookup_needs_no_outside_call(self):
        for query in ["New York, NY", "  new york ,ny ", "New York, New York", "New York, NY, USA"]:
            with self.subTest(query=query):
                location, calls = resolve(query)
                self.assertEqual(calls, 0)
                self.assertAlmostEqual(location.lat, 40.7, delta=0.3)
                self.assertEqual(location.name, "New York, NY")

    def test_saint_and_st_are_the_same_place(self):
        self.assertEqual(resolve("Saint Louis, Missouri")[0], resolve("St. Louis, MO")[0])

    def test_lookup_place_accepts_code_or_state_name(self):
        self.assertEqual(lookup_place("Big Cabin", "OK"), lookup_place("big cabin", "Oklahoma"))
        self.assertIsNone(lookup_place("Big Cabin", "NY"))

    @patch("fuel.services.external.get_json")
    def test_unknown_text_falls_back_to_geocoder_once(self, get_json):
        get_json.return_value = [{"lat": "38.8977", "lon": "-77.0365", "display_name": "White House"}]
        query = "1600 Pennsylvania Ave NW, Washington, DC"

        location, calls = resolve(query)

        self.assertEqual((calls, location.lat, location.name), (1, 38.8977, "White House"))
        self.assertEqual(get_json.call_args.args[1]["countrycodes"], "us")
        self.assertEqual(resolve(query)[1], 0)
        self.assertEqual(get_json.call_count, 1)

    @patch("fuel.services.external.get_json", return_value=[])
    def test_unfindable_place_is_a_400(self, _):
        with self.assertRaises(LocationNotFound) as raised:
            resolve("zzzz nowhere")
        self.assertEqual(raised.exception.status_code, 400)
