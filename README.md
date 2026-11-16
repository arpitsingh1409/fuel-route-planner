# Fuel Route Planner

A Django REST Framework API that takes a start and finish in the USA, fetches the driving route, and works out where a vehicle with a 500-mile range and 10 miles per gallon should buy fuel, and how much, so that the fuel bill is as low as possible. Prices come from the supplied truck-stop price list. The response carries the route geometry, the fuel stops, the total cost, and a link to a map page that draws them.

## Quick start

Python 3.12 or newer. No API keys or signups are needed.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py load_stations
python manage.py runserver
```

Then open:

- JSON: http://127.0.0.1:8000/api/route/?start=New%20York,%20NY&finish=Los%20Angeles,%20CA
- Map: http://127.0.0.1:8000/api/route/map/?start=New%20York,%20NY&finish=Los%20Angeles,%20CA

## The API

`GET /api/route/` returns the plan as JSON. `GET /api/route/map/` takes the same parameters and returns an HTML page that draws the route and stops with Leaflet on OpenStreetMap tiles. Every JSON response includes `map_url` for the same trip.

| Parameter | Required | Default | Meaning |
|---|---|---|---|
| `start` | yes | | Start location in the USA, at most 200 characters. "City, ST" (or "City, State") is resolved locally; anything else, such as a street address or landmark, is geocoded. |
| `finish` | yes | | Finish location, same rules as `start`. |
| `start_fuel_gallons` | no | `0` | Fuel already in the tank, 0 to 50 gallons. |
| `stop_cost` | no | `0` | Dollars charged per stop when choosing stops, 0 to 100. It changes which stops are chosen; every reported cost is fuel money only. |

Example: Chicago to Houston with `stop_cost=5`. Abridged: the route has 1,490 points, cut to two here, and stop 2 of 4 is left out.

```json
{
  "start": {"query": "Chicago, IL", "name": "Chicago, IL", "lat": 41.837045, "lon": -87.684939},
  "finish": {"query": "Houston, TX", "name": "Houston, TX", "lat": 29.785743, "lon": -95.388806},
  "distance_miles": 1083.1,
  "duration_hours": 19.9,
  "vehicle": {"range_miles": 500, "mpg": 10},
  "options": {"start_fuel_gallons": 0.0, "stop_cost": 5.0},
  "fuel_stops": [
    {
      "stop": 1, "station_id": 72318, "name": "THORNTONS #330", "address": "I-55 & SR-50",
      "city": "Cicero", "state": "IL", "lat": 41.844537, "lon": -87.75929, "located_by": "town",
      "mile_marker": 0.0, "miles_off_route": 3.9, "price_per_gallon": 3.549, "gallons": 3.0, "cost": 10.65
    },
    {
      "stop": 3, "station_id": 69861, "name": "HUCKS FOOD & FUEL #379", "address": "I-57, EXIT 53",
      "city": "Marion", "state": "IL", "lat": 37.735054, "lon": -88.958966, "located_by": "exit",
      "mile_marker": 313.0, "miles_off_route": 0.1, "price_per_gallon": 2.929, "gallons": 47.5, "cost": 139.13
    },
    {
      "stop": 4, "station_id": 72594, "name": "Quiktrip #7900", "address": "I-30 & FM-989",
      "city": "Texarkana", "state": "TX", "lat": 33.449204, "lon": -94.085008, "located_by": "town",
      "mile_marker": 788.0, "miles_off_route": 0.5, "price_per_gallon": 2.857, "gallons": 29.5, "cost": 84.29
    }
  ],
  "total_gallons": 108.3,
  "total_fuel_cost": 321.21,
  "route": {"type": "LineString", "coordinates": [[-87.68489, 41.83705], [-87.68457, 41.83494], "... 1,488 more [lon, lat] points"]},
  "meta": {"external_api_calls": 1, "elapsed_ms": 1289},
  "map_url": "http://127.0.0.1:8000/api/route/map/?start=Chicago%2C+IL&finish=Houston%2C+TX&start_fuel_gallons=0.0&stop_cost=5.0"
}
```

`route` is a GeoJSON LineString of at most 1,500 points. `meta.external_api_calls` counts the outside calls this request made (0 when everything was cached).

| Status | Cause |
|---|---|
| 400 | A parameter is missing or out of range, or a location cannot be found in the USA. |
| 422 | OSRM finds no drivable route, or part of the route has no station within 500 miles (also returned if no stations are loaded). |
| 503 | The routing or geocoding service timed out, failed, returned a 5xx, or rate-limited the request (429). |

The map page returns the same statuses with the message shown on the page.

## How it works

1. Validate the query parameters.
2. Resolve `start` and `finish`. "City, ST" comes from the bundled places list (0 calls); anything else is one Nominatim call each.
3. Fetch the fastest driving route from OSRM (1 call).
4. Find the stations within 5 miles of the route and their mile along it, and add the station nearest the route's start at mile 0.
5. Choose the stops and amounts (below), then build the response.

A typical request makes exactly 1 outside call; the worst case is 3. Outside results are cached for 24 hours, so a repeated request makes none.

## How fuel stops are chosen

The planner is exact, not a heuristic. It is a dynamic programme over the fuel level in whole miles (0 to 500): at each station, in route order, it keeps the cheapest way to be there holding each possible amount of fuel, then walks back from the cheapest arrival to recover where and how much was bought. Each station costs O(500) work, done with NumPy running minimums. It minimises fuel cost plus `stop_cost` for every stop.

With `stop_cost=0` (the default) the result is the strictly cheapest fuel bill, the same as the textbook rule "if a cheaper station is within range, buy just enough to reach it; otherwise fill up". That plan often makes many small purchases, so `stop_cost` lets the caller trade a little money for fewer stops. New York to Los Angeles (281 gallons):

| `stop_cost` | Stops | Fuel cost |
|---|---|---|
| $0 | 20 (6 of them under 2 gallons) | $859.45 |
| $1 | 10 | $860.87 |
| $2 | 9 | $862.20 |
| $5 | 8 | $865.11 |
| $10 | 7 | $870.37 |

Chicago to Houston: 12 stops for $318.22 at $0; 4 stops for $321.21 at $5. Seattle to Miami (3,303 miles): 24 stops for $1,027.49 at $0; 9 stops for $1,034.61 at $5.

## Assumptions and decisions

- **The tank starts empty**, so the total covers fuel for every mile driven and can be sanity-checked as distance / 10 x price. To make that possible on any trip, the station nearest the start of the route is always available at mile 0. `start_fuel_gallons` overrides this.
- **The route is the fastest one OSRM returns and is not bent toward cheaper fuel.** Bending it would need a routing call per candidate detour, and at 10 mpg each detour mile costs about 35 cents each way.
- **"On the route" means within 5 miles of the route line.** The margin mainly absorbs the uncertainty of town-located stations. Detour miles are not costed.
- **Public OSRM for routing**, because it needs no API key, so the project runs with no signup. Set `OSRM_URL` to use a self-hosted OSRM (`NOMINATIM_URL` likewise).
- **"City, ST" is resolved locally** from `data/us_places.csv`, so a typical request makes one outside call.
- **Outside calls are cached for 24 hours** in Django's cache (per-process memory by default). Failures are not cached.
- **No straight-line fallback.** If routing fails the API returns 503; a made-up route would choose the wrong stations.
- **Duplicate stations keep their lowest price.** The price list has 8,151 rows; 620 are in Canadian provinces and are dropped, leaving 6,626 distinct stations by OPIS Truckstop ID, of which 6,620 could be located.
- **Whole miles.** Planning works in whole miles, so gallons are reported to a tenth.

## Where the station locations come from

The price list has no coordinates, and only a handful of addresses are street addresses; most are highway descriptions such as `I-44, EXIT 283 & US-69`.

- If the address names an exit, the station is placed at the OpenStreetMap motorway junction with that exit number within 25 miles of the station's town (an exact match such as `144B` first, then the bare number). When exits with the same number lie more than 2 miles apart, the one on the Interstate or US route named in the address is preferred, read from the OpenStreetMap ways through each exit; if that cannot be confirmed, the one nearest the town is used.
- Otherwise it is placed at its town centre, from the US Census Gazetteer, with Nominatim for towns it lacks.
- Each station records the method in `located_by`: `exit` is precise, `town` is approximate. In a check on Oklahoma, a third of exit-located stations were more than 5 miles from their town centre, which is why exits are used where possible.

Of the 6,620 stations, 3,483 are located by exit and 3,137 by town centre. Exit numbers were ambiguous for 397 stations: the highway check confirmed the nearest exit for 315, moved 38 to an exit on the named highway, and could not decide 44, which keep the nearest. Six stations are left out because their town could not be found.

This work runs once and its output, `data/us_places.csv` and `data/stations.csv`, is committed, so a reviewer only needs `migrate` and `load_stations`. To rebuild it:

```bash
python manage.py build_places      # Census Gazetteer -> data/us_places.csv
python manage.py locate_stations   # data/fuel-prices.csv + Overpass + Nominatim -> data/stations.csv
```

Downloads are cached under `data/raw/`, which is not committed.

## Performance

Measured on a laptop against the public OSRM server:

- New York to Los Angeles, 2,810 miles: the first request takes about 1.5 seconds with 1 outside call, almost all of it the routing call. The same request again takes about 8 ms with 0 outside calls. The planning work itself is about 6 ms.
- A street address or landmark adds one geocoding call per end, so the worst case is 3 outside calls.

Finding stations near the route is one NumPy matrix product over the stations, held in memory as unit vectors, in two passes: a coarse pass against every tenth 1-mile route sample discards most stations, then a fine pass measures the rest.

## Tests

```bash
python manage.py test
```

54 tests, run against mocked outside services. The notable ones:

- **Optimizer against the textbook rule**: 300 random trips with free stops, checked against the greedy rule's cost, including which trips are infeasible.
- **Optimizer against brute force**: 300 small random trips with a stop cost, checked against trying every whole-mile purchase at every station.
- **Plan validity**: every plan is replayed to check the tank never runs dry or overflows.
- **Station search**: a station 4.7 miles off a sparse 530-mile route is found and one 5.9 miles off is not.
- **API**: a repeated request makes no outside call; a routing outage is a 503 and is not cached; bad input is a 400; the map page shows errors with the right status.
- **Data preparation**: Canadian rows are dropped, duplicates keep the lowest price, exit numbers are parsed and matched, and an ambiguous exit goes to the highway named in the address.

## Project layout

```
config/settings.py              vehicle range, mpg, 5-mile margin, OSRM/Nominatim URLs, cache
fuel/views.py                   JSON endpoint and map page
fuel/serializers.py             query parameter validation
fuel/exceptions.py              API errors and their statuses
fuel/models.py                  FuelStation
fuel/services/planner.py        one request end to end
fuel/services/optimizer.py      the dynamic programme
fuel/services/stations.py       stations near a route (NumPy)
fuel/services/routing.py        OSRM call and polyline decoding
fuel/services/geocoding.py      "City, ST" lookup, Nominatim fallback
fuel/services/external.py       the only code that calls outside services; caching
fuel/locating.py                price-list cleaning and exit matching
fuel/management/commands/       build_places, locate_stations, load_stations
fuel/templates/fuel/map.html    Leaflet map page
fuel/tests/                     tests
data/                           fuel-prices.csv (supplied), us_places.csv, stations.csv
```

## Limits and what would change at larger scale

- Town-located stations are approximate, which the 5-mile margin only partly absorbs.
- The public OSRM server has no uptime guarantee; production would self-host OSRM via `OSRM_URL`.
- The cache is per process; several workers would share Redis or Memcached through `CACHES`.
- Fuel can only be bought at stations in the supplied list.
- Planning works in whole miles, so gallons are in tenths.
- There is no authentication or rate limiting.
- Station search scans every station. A benchmark on a New York to Los Angeles route with 6,626 stations gave: two-pass NumPy 4.7 ms, k-d tree 5.7 ms, Uber's H3 hexagonal index at its best resolution (4) 6.1 ms, single-pass NumPy 7.5 ms; H3 at resolution 9 took 1.2 seconds because the route needs 779,000 cells. An index starts to pay off from roughly 66,000 stations.

## Data sources and licences

- Fuel prices: the price list supplied with the assignment (`data/fuel-prices.csv`).
- Places: US Census Bureau Gazetteer 2025 places file (public domain).
- Exit locations via the Overpass API, and some town centres via Nominatim: OpenStreetMap, © OpenStreetMap contributors, under the ODbL. The coordinates in `data/stations.csv` are therefore derived data under the ODbL.
- Routing: OSRM (public demo server by default).
- Map tiles: OpenStreetMap.
