import random
from functools import lru_cache, partial

from django.test import SimpleTestCase

from fuel.exceptions import NoFeasiblePlan
from fuel.services.optimizer import plan_fuel_stops

plan = partial(plan_fuel_stops, tank_miles=500, start_miles=0, mpg=10, stop_cost=0)


def fuel_cost(stops, miles, prices, total, tank, start, mpg):
    """Drive the plan, failing if the tank ever runs dry or overflows; return the fuel bill."""
    fuel, position, cost, bought = start, 0, 0.0, dict(stops)
    for i, (mile, price) in enumerate(zip(miles, prices)):
        fuel -= mile - position
        position = mile
        assert fuel >= 0, "ran dry before a station"
        fuel += bought.get(i, 0)
        assert fuel <= tank, "bought more than the tank holds"
        cost += bought.get(i, 0) / mpg * price
    assert fuel - (total - position) >= 0, "ran dry before the destination"
    return cost


def greedy_cost(miles, prices, total, tank, start, mpg):
    """The textbook rule when stops are free: if a cheaper station is within range buy just
    enough to reach it, otherwise fill up. Returns None when the trip cannot be made."""
    nodes = [*zip(miles, prices), (total, 0.0)]  # the destination acts as a free station
    fuel, position, cost = start, 0, 0.0
    for i, (mile, price) in enumerate(nodes[:-1]):
        fuel -= mile - position
        position = mile
        if fuel < 0:
            return None
        cheaper = next((m for m, p in nodes[i + 1:] if p < price and m - mile <= tank), None)
        buy = max(0, (cheaper - mile if cheaper is not None else tank) - fuel)
        cost += buy / mpg * price
        fuel += buy
    return cost if fuel - (total - position) >= 0 else None


def brute_force_cost(miles, prices, total, tank, start, mpg, penalty):
    """Try every whole-mile purchase at every station. Only usable on tiny cases."""
    @lru_cache(maxsize=None)
    def best(i, fuel):
        position = miles[i - 1] if i else 0
        if i == len(miles):
            return 0.0 if fuel >= total - position else float("inf")
        fuel -= miles[i] - position
        if fuel < 0:
            return float("inf")
        return min(
            buy / mpg * prices[i] + (penalty if buy else 0) + best(i + 1, fuel + buy)
            for buy in range(tank - fuel + 1)
        )
    return best(0, start)


def random_case(rng, tanks, max_stations):
    tank = rng.choice(tanks)
    total = rng.randint(0, 4 * tank)
    miles = sorted(rng.randint(0, total) for _ in range(rng.randint(0, max_stations)))
    if miles and rng.random() < 0.7:
        miles[0] = 0  # most trips have somewhere to fuel at the start
    prices = [rng.choice([2.8, 3.0, 3.0, 3.25, 3.5, 4.1]) for _ in miles]
    start = rng.choice([0, 0, rng.randint(0, tank)])
    return miles, prices, total, tank, start


class PlanFuelStopsTests(SimpleTestCase):
    def test_buys_just_enough_to_reach_a_cheaper_station(self):
        self.assertEqual(plan([0, 100], [4.0, 3.0], 300), [(0, 100), (1, 200)])

    def test_fills_up_before_an_expensive_stretch(self):
        self.assertEqual(plan([0, 400], [3.0, 4.0], 700), [(0, 500), (1, 200)])

    def test_does_not_stop_at_a_station_that_is_no_cheaper(self):
        self.assertEqual(plan([0, 100], [3.0, 3.0], 300), [(0, 300)])

    def test_two_stations_at_the_same_place_and_price_make_one_stop(self):
        # Rounding noise must not make an equally priced purchase look like a saving.
        stops = plan([0, 9, 9, 12], [3.349, 3.239, 3.239, 3.192], 100)
        self.assertEqual(stops, [(0, 9), (1, 3), (3, 88)])

    def test_start_fuel_that_covers_the_trip_needs_no_stop(self):
        self.assertEqual(plan([50], [3.0], 200, start_miles=200), [])

    def test_start_fuel_is_used_before_buying(self):
        self.assertEqual(plan([100], [3.0], 400, start_miles=150), [(0, 250)])

    def test_zero_length_trip(self):
        self.assertEqual(plan([0], [3.0], 0), [])

    def test_gap_longer_than_the_tank_is_infeasible(self):
        with self.assertRaises(NoFeasiblePlan):
            plan([0, 600], [3.0, 3.0], 700)

    def test_empty_tank_with_no_station_at_the_start_is_infeasible(self):
        with self.assertRaises(NoFeasiblePlan):
            plan([10], [3.0], 100)

    def test_no_stations_and_not_enough_fuel_is_infeasible(self):
        with self.assertRaises(NoFeasiblePlan):
            plan([], [], 100, start_miles=50)

    def test_stop_cost_skips_a_stop_that_saves_less_than_it_costs(self):
        self.assertEqual(plan([0, 100], [3.00, 2.99], 300, stop_cost=5), [(0, 300)])

    def test_the_same_trip_stops_when_stops_are_free(self):
        self.assertEqual(plan([0, 100], [3.00, 2.99], 300, stop_cost=0), [(0, 100), (1, 200)])

    def test_matches_the_classic_greedy_when_stops_are_free(self):
        rng = random.Random(7)
        for _ in range(300):
            miles, prices, total, tank, start = random_case(rng, [20, 35, 60], 15)
            want = greedy_cost(miles, prices, total, tank, start, mpg=10)
            with self.subTest(miles=miles, prices=prices, total=total, tank=tank, start=start):
                if want is None:
                    with self.assertRaises(NoFeasiblePlan):
                        plan(miles, prices, total, tank_miles=tank, start_miles=start)
                else:
                    stops = plan(miles, prices, total, tank_miles=tank, start_miles=start)
                    got = fuel_cost(stops, miles, prices, total, tank, start, mpg=10)
                    self.assertAlmostEqual(got, want, places=6)

    def test_matches_brute_force_when_stops_cost_money(self):
        rng = random.Random(11)
        for _ in range(300):
            miles, prices, total, tank, start = random_case(rng, [4, 5, 6], 4)
            want = brute_force_cost(miles, prices, total, tank, start, mpg=10, penalty=0.05)
            with self.subTest(miles=miles, prices=prices, total=total, tank=tank, start=start):
                if want == float("inf"):
                    with self.assertRaises(NoFeasiblePlan):
                        plan(miles, prices, total, tank_miles=tank, start_miles=start, stop_cost=0.05)
                else:
                    stops = plan(miles, prices, total, tank_miles=tank, start_miles=start, stop_cost=0.05)
                    got = fuel_cost(stops, miles, prices, total, tank, start, mpg=10)
                    self.assertAlmostEqual(got + 0.05 * len(stops), want, places=6)
