import io
from unittest import mock

from django.test import SimpleTestCase

from fuel.locating import (
    address_highways, choose_exit, clean_stations, exit_candidates, highways_by_node, index_exits,
    first_place, is_ambiguous, parse_exit, pick_exit, squash_place,
)
from fuel.management.commands.locate_stations import Command


def row(opis_id, state, price, city="Somewhere", name="STOP"):
    return {
        "OPIS Truckstop ID": str(opis_id), "Truckstop Name": name, "Address": "I-1, EXIT 1",
        "City": city, "State": state, "Rack ID": "1", "Retail Price": price,
    }


class CleanStationsTests(SimpleTestCase):
    def test_keeps_lowest_price_per_station_and_drops_canada(self):
        rows = [
            row(105, "MI", "3.339"), row(105, "MI", "3.269"), row(105, "MI", "3.429"),
            row(9, "ON", "3.0"), row(7, "DE", "3.2", city="New Castle   "),
        ]

        stations = clean_stations(rows)

        self.assertEqual([(s["opis_id"], s["price"]) for s in stations], [(7, 3.2), (105, 3.269)])
        self.assertEqual(stations[0]["city"], "New Castle")


class ExitTests(SimpleTestCase):
    def test_parse_exit(self):
        cases = {
            "I-44, EXIT 283 & US-69": "283", "I-75, EXIT 144-B": "144B", "I-4, EXIT-55": "55",
            "I-35,  EXIT 271": "271", "I-10, EXIT 12 A": "12A", "US-46": None, "US-13 & US-40": None,
        }
        for address, want in cases.items():
            with self.subTest(address=address):
                self.assertEqual(parse_exit(address), want)

    def test_index_exits_splits_shared_refs_and_keeps_node_ids(self):
        nodes = [
            {"id": 5, "lat": 1.0, "lon": 2.0, "tags": {"ref": "12;12A"}},
            {"id": 6, "lat": 3.0, "lon": 4.0, "tags": {"ref": "144 B"}},
        ]
        self.assertEqual(
            index_exits(nodes),
            {"12": [(5, (1.0, 2.0))], "12A": [(5, (1.0, 2.0))], "144B": [(6, (3.0, 4.0))]},
        )

    def test_pick_exit_takes_nearest_match_within_25_miles(self):
        town = (36.54, -95.22)
        exits = {"283": [(1, (35.0, -97.0)), (2, (36.55, -95.20))]}

        self.assertEqual(pick_exit("283", town, exits), (36.55, -95.20))
        self.assertIsNone(pick_exit("283", (40.0, -80.0), exits))
        self.assertIsNone(pick_exit("999", town, exits))

    def test_pick_exit_falls_back_to_the_number_when_the_letter_is_unknown(self):
        town = (36.54, -95.22)
        self.assertEqual(pick_exit("144B", town, {"144": [(1, (36.55, -95.20))]}), (36.55, -95.20))


class HighwayCheckTests(SimpleTestCase):
    town = (36.54, -95.22)
    # Two exits numbered 283 near the town, about 7 miles apart; the far one is on I-44.
    exits = {"283": [(1, (36.55, -95.20)), (2, (36.60, -95.33))]}

    def test_exit_candidates_carry_node_ids_nearest_first(self):
        self.assertEqual([c[1] for c in exit_candidates("283", self.town, self.exits)], [1, 2])

    def test_is_ambiguous_when_another_candidate_is_over_2_miles_away(self):
        candidates = exit_candidates("283", self.town, self.exits)
        self.assertTrue(is_ambiguous(candidates))
        self.assertFalse(is_ambiguous(candidates[:1]))
        close = exit_candidates("283", self.town, {"283": [(1, (36.55, -95.20)), (3, (36.551, -95.201))]})
        self.assertFalse(is_ambiguous(close))

    def test_address_highways_reads_interstates_and_us_routes_before_the_exit(self):
        cases = {
            "I-44, EXIT 283 & US-69": {"I44"}, "I-80/I-94, EXIT 5": {"I80", "I94"},
            "I-35E, EXIT 10": {"I35E"}, "I-40/US-64, EXIT 3": {"I40", "US64"}, "HWY 6, EXIT 2": set(),
        }
        for address, want in cases.items():
            with self.subTest(address=address):
                self.assertEqual(address_highways(address), want)

    def test_highways_by_node_reads_refs_of_the_ways_through_each_node(self):
        ways = [
            {"type": "way", "nodes": [1, 7, 2], "tags": {"highway": "motorway", "ref": "I 44;US 412"}},
            {"type": "way", "nodes": [2, 9], "tags": {"highway": "motorway_link"}},
            {"type": "way", "nodes": [8, 1], "tags": {"highway": "trunk", "ref": "US 69"}},
        ]
        self.assertEqual(
            highways_by_node(ways, {1, 2}), {1: {"I44", "US412", "US69"}, 2: {"I44", "US412"}}
        )

    def test_choose_exit_prefers_the_named_highway(self):
        candidates = exit_candidates("283", self.town, self.exits)
        self.assertEqual(choose_exit(candidates, {"I44"}, {2: {"I44"}, 1: {"US69"}}), ((36.60, -95.33), True))

    def test_choose_exit_falls_back_to_the_nearest_when_the_highway_is_unconfirmed(self):
        candidates = exit_candidates("283", self.town, self.exits)
        self.assertEqual(choose_exit(candidates, {"I44"}, {1: {"US69"}}), ((36.55, -95.20), False))
        self.assertEqual(choose_exit(candidates, set(), {2: {"I44"}}), ((36.55, -95.20), False))


class TownTests(SimpleTestCase):
    def test_squash_place_ignores_spaces_and_spelling(self):
        for postal, official in [("Mc Lean", "McLean"), ("Brookpark", "Brook Park"), ("Saint Johns", "St. Johns")]:
            with self.subTest(postal=postal):
                self.assertEqual(squash_place(postal), squash_place(official))

    def test_first_place_skips_shops_and_places_in_other_states(self):
        def result(lat, kind, state):
            return {"lat": lat, "lon": "-80.2", "addresstype": kind, "address": {"ISO3166-2-lvl4": f"US-{state}"}}

        results = [result("39.9", "amenity", "PA"), result("41.1", "village", "IL"), result("40.6", "village", "PA")]
        self.assertEqual(first_place(results, "PA"), (40.6, -80.2))
        self.assertIsNone(first_place(results[:2], "PA"))


class OverpassRetryTests(SimpleTestCase):
    def post_with(self, *bodies):
        responses = [mock.Mock(ok=True, text=body) for body in bodies]
        with mock.patch("fuel.management.commands.locate_stations.requests.post", side_effect=responses), \
                mock.patch("fuel.management.commands.locate_stations.time.sleep"):
            return Command(stdout=io.StringIO()).post_with_retry({"data": "q"})

    def test_retries_a_body_that_reports_a_runtime_error(self):
        cut_short = '{"elements": [], "remark": "runtime error: Query timed out"}'
        clean = '{"elements": [{"id": 1}]}'
        self.assertEqual(self.post_with(cut_short, clean), clean)

    def test_retries_a_body_that_is_not_json(self):
        clean = '{"elements": []}'
        self.assertEqual(self.post_with('<html>"elements"</html>', clean), clean)
