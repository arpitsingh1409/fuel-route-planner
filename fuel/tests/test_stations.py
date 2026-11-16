import tempfile
from pathlib import Path

import numpy as np
from django.core.management import call_command
from django.test import TestCase

from fuel.exceptions import NoFeasiblePlan
from fuel.models import FuelStation
from fuel.services import stations
from fuel.services.geo import haversine_miles


def straight_route(lon_from, lon_to, step=0.005, lat=40.0):
    """A west-to-east line along one latitude. One degree of longitude here is about 53 miles."""
    lons = np.arange(lon_from, lon_to + step / 2, step)
    points = np.column_stack([np.full_like(lons, lat), lons])
    steps = haversine_miles(points[:-1, 0], points[:-1, 1], points[1:, 0], points[1:, 1])
    return points, np.concatenate([[0.0], np.cumsum(steps)])


def make(name, lat, lon, price=3.0):
    return FuelStation.objects.create(
        opis_id=FuelStation.objects.count() + 1, name=name, address="I-80, EXIT 1", city="Town",
        state="NE", price=price, lat=lat, lon=lon, located_by="exit",
    )


class AlongRouteTests(TestCase):
    def setUp(self):
        stations.clear_cache()
        self.points, self.miles = straight_route(-100.0, -99.0)

    def test_finds_stations_within_offset_in_route_order(self):
        make("A", 40.00, -99.50)
        make("B", 40.05, -99.80)  # about 3.5 miles north of the line
        make("C", 40.20, -99.50)  # about 14 miles north: too far

        found = stations.along_route(self.points, self.miles, max_offset=5)

        self.assertEqual([s["name"] for s in found], ["B", "A"])
        self.assertAlmostEqual(found[0]["miles_off_route"], 3.45, delta=0.2)
        self.assertAlmostEqual(found[0]["mile"], 10.6, delta=1.0)
        self.assertAlmostEqual(found[1]["mile"], 26.5, delta=1.0)
        self.assertEqual((found[1]["price"], found[1]["located_by"], found[1]["state"]), (3.0, "exit", "NE"))

    def test_offset_limit_holds_anywhere_on_a_long_route(self):
        points, miles = straight_route(-100.0, -90.0, step=0.5)  # about 530 miles, sparse vertices
        make("inside", 40.068, -94.87)   # about 4.7 miles off, between two vertices
        make("outside", 40.085, -94.87)  # about 5.9 miles off

        found = stations.along_route(points, miles, max_offset=5)

        self.assertEqual([s["name"] for s in found], ["inside"])
        self.assertAlmostEqual(found[0]["mile"], 271.8, delta=1.5)

    def test_no_stations_means_nothing_found(self):
        self.assertEqual(stations.along_route(self.points, self.miles, max_offset=5), [])


class NearestTests(TestCase):
    def setUp(self):
        stations.clear_cache()

    def test_nearest_ignores_the_offset_limit(self):
        make("near", 40.20, -99.50)
        make("far", 45.00, -99.50)

        found = stations.nearest(40.0, -99.5)

        self.assertEqual((found["name"], found["mile"]), ("near", 0.0))
        self.assertAlmostEqual(found["miles_off_route"], 13.8, delta=0.2)

    def test_nearest_with_no_stations_is_infeasible(self):
        with self.assertRaises(NoFeasiblePlan):
            stations.nearest(40.0, -99.5)


class LoadStationsTests(TestCase):
    CSV = (
        "opis_id,name,address,city,state,price,lat,lon,located_by\n"
        '7,WOODSHED OF BIG CABIN,"I-44, EXIT 283 & US-69",Big Cabin,OK,3.00733333,36.5,-95.2,exit\n'
        "35,ACI TRUCK STOP,US-46,Columbia,NJ,3.079,40.9,-75.1,town\n"
    )

    def setUp(self):
        stations.clear_cache()

    def test_load_stations_replaces_the_table_and_refreshes_the_index(self):
        make("stale", 40.0, -99.5)
        self.assertEqual(stations.nearest(40.0, -99.5)["name"], "stale")  # warm the index
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "stations.csv").write_text(self.CSV)
            with self.settings(DATA_DIR=Path(folder)):
                call_command("load_stations", verbosity=0)
                call_command("load_stations", verbosity=0)  # running it twice changes nothing

        self.assertEqual(list(FuelStation.objects.values_list("opis_id", flat=True)), [7, 35])
        woodshed = FuelStation.objects.get(pk=7)
        self.assertEqual((woodshed.address, woodshed.price), ("I-44, EXIT 283 & US-69", 3.00733333))
        self.assertEqual(stations.nearest(40.0, -99.5)["name"], "WOODSHED OF BIG CABIN")
